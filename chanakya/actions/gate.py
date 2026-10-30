"""Safety gate: the only way an action reaches a business system."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from chanakya.actions.policy import Facts, evaluate
from chanakya.actions.registry import InvalidArgumentsError, MockToolRegistry
from chanakya.core.config import Settings
from chanakya.core.interfaces import Planner, UnknownToolError
from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    EventKind,
    Merchant,
    PlanContext,
    ToolCall,
    ToolKind,
    Transcript,
    Turn,
    Verdict,
    utcnow,
)
from chanakya.missions.ledger import MissionLedger


def merchant_from_db(registry: MockToolRegistry, merchant_id: str) -> Merchant | None:
    """Load a merchant from the mock CRM tables."""
    row = registry.db.one("SELECT * FROM merchants WHERE id = ?", merchant_id)
    if row is None:
        return None
    return Merchant(
        id=row["id"], name=row["name"], business_type=row["business_type"], city=row["city"],
        language=row["language"], contact_window={"start_hour": row["start_hour"], "end_hour": row["end_hour"]},
        do_not_call=bool(row["do_not_call"]), has_soundbox=bool(row["has_soundbox"]),
        has_card_machine=bool(row["has_card_machine"]), phone_last4=row["phone_last4"],
        relationship=row["relationship"], churned_at=row["churned_at"],
    )


class ActionGate:
    """Membership check, policy rules, pre-write reconsideration, execution, and an audit entry for every attempt."""

    def __init__(self, registry: MockToolRegistry, ledger: MissionLedger, planner: Planner | None = None,
                 settings: Settings | None = None, clock: Callable[[], datetime] = utcnow):
        self.registry = registry
        self.ledger = ledger
        self.planner = planner
        self.settings = settings or Settings()
        self.clock = clock

    async def submit(self, call: ToolCall) -> ActionDecision:
        """Check, then execute or block the call; the decision is always written to the mission ledger."""
        decision = await self._decide(call)
        if self.ledger.store.get(call.mission_id) is not None:
            await self.ledger.attach_action(call.mission_id, decision)
        return decision

    async def _decide(self, call: ToolCall) -> ActionDecision:
        try:
            call = self.registry.validate(call)
        except UnknownToolError:
            return ActionDecision(call=call, verdict=Verdict.REJECTED, reason=f"unknown tool {call.tool}")
        except InvalidArgumentsError as error:
            return ActionDecision(call=call, verdict=Verdict.REJECTED, reason=f"invalid arguments: {error}")
        tool = self.registry.get(call.tool)

        mission = self.ledger.store.get(call.mission_id)
        if mission is None:
            return ActionDecision(call=call, verdict=Verdict.REJECTED, reason="unknown mission", kind=tool.kind)
        if not mission.is_open:
            return ActionDecision(call=call, verdict=Verdict.BLOCKED, reason=f"mission is {mission.state}", kind=tool.kind)

        events = self.ledger.store.events(mission.id)
        facts = Facts(
            call=call, tool=tool, mission=mission,
            merchant=merchant_from_db(self.registry, mission.card.merchant_id), events=events,
            local_time=self.clock().astimezone(ZoneInfo(self.settings.timezone)),
            calling_hours=self.settings.calling_hours,
        )
        reason = evaluate(facts)
        if reason:
            return ActionDecision(call=call, verdict=Verdict.BLOCKED, reason=reason, kind=tool.kind)

        if tool.kind == ToolKind.WRITE and tool.irreversible and self.planner is not None:
            context = PlanContext(mission=mission, belief=self._belief(mission, events),
                                  transcript=self._transcript(mission.id, events))
            if not await self.planner.reconsider(context, call):
                return ActionDecision(call=call, verdict=Verdict.BLOCKED, reason="planner reconsidered", kind=tool.kind)

        result = self.registry.execute(call)
        verdict = Verdict.EXECUTED if result.ok else Verdict.FAILED
        return ActionDecision(call=call, verdict=verdict, reason="ok" if result.ok else result.error or "failed",
                              kind=tool.kind, result=result)

    @staticmethod
    def _belief(mission, events) -> BeliefState:
        latest = [e for e in events if e.kind == EventKind.BELIEF_UPDATED]
        if latest:
            return BeliefState.model_validate(latest[-1].payload)
        return BeliefState(probabilities=mission.card.starting_worries or {"unknown": 1.0})

    @staticmethod
    def _transcript(mission_id: str, events) -> Transcript:
        turns = [Turn.model_validate(e.payload) for e in events if e.kind == EventKind.TURN_COMPLETED]
        return Transcript(mission_id=mission_id, turns=turns)
