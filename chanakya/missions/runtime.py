"""Wires the mission, action and human modules together for the API and demo scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from chanakya.actions.gate import ActionGate, merchant_from_db
from chanakya.actions.registry import MockToolRegistry
from chanakya.actions.systems.db import MockDB
from chanakya.actions.systems.seed import seed
from chanakya.core.config import Settings
from chanakya.core.llm import LLM
from chanakya.core.schemas import ActionDecision, ToolCall, Verdict
from chanakya.humans.handoff import HandoffQueue
from chanakya.missions.intake import MissionIntake
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore
from chanakya.missions.queue import MissionQueue
from chanakya.missions.scheduler import RealClock, Scheduler
from chanakya.missions.verifier import OnboardingVerifier


@dataclass
class Runtime:
    settings: Settings
    clock: RealClock
    db: MockDB
    registry: MockToolRegistry
    ledger: MissionLedger
    gate: ActionGate
    intake: MissionIntake
    queue: MissionQueue
    scheduler: Scheduler
    verifier: OnboardingVerifier
    handoffs: HandoffQueue

    @classmethod
    def build(cls, settings: Settings | None = None, clock=None, llm: LLM | None = None) -> Runtime:
        """Open (or create) the mock systems and ledger databases and wire every module."""
        settings = settings or Settings.from_env()
        clock = clock or RealClock()
        db = MockDB(settings.db_path.with_name("mock_systems.db"))
        seed(db)
        registry = MockToolRegistry(db)
        ledger = MissionLedger(SQLiteMissionStore(settings.db_path))
        gate = ActionGate(registry, ledger, settings=settings, clock=clock)
        scheduler = Scheduler(ledger, clock)
        return cls(
            settings=settings, clock=clock, db=db, registry=registry, ledger=ledger, gate=gate,
            intake=MissionIntake(ledger, lambda merchant_id: merchant_from_db(registry, merchant_id)),
            queue=MissionQueue(ledger, settings=settings, clock=clock), scheduler=scheduler,
            verifier=OnboardingVerifier(ledger, gate, scheduler), handoffs=HandoffQueue(ledger, llm=llm),
        )

    async def submit(self, call: ToolCall) -> ActionDecision:
        """Send a call through the safety gate; a sent onboarding link starts verification automatically."""
        decision = await self.gate.submit(call)
        if decision.verdict == Verdict.EXECUTED and call.tool == "send_onboarding_link":
            data = decision.result.data
            await self.verifier.expect_onboarding(call.mission_id, data["session_id"], data["link"])
        return decision

    async def fast_forward(self, delta: timedelta) -> int:
        """Demo fast-forward: move the clock, then run whatever became due. Returns jobs run."""
        self.clock.advance(delta)
        return len(await self.verifier.run_due())


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    """The process-wide runtime, built on first use."""
    global _runtime
    if _runtime is None:
        _runtime = Runtime.build()
    return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    """Replace the process-wide runtime (tests and scripts)."""
    global _runtime
    _runtime = runtime
