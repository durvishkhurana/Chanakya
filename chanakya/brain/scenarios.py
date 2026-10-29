"""The demo storyline as runnable scenarios (docs/IDEA.md section 8). Fictional merchants, mock systems only.

    python scripts/demo/scenarios.py            # all four, in-process, offline
    python scripts/demo/scenarios.py card_machine_sale --live   # Chanakya speaks through the configured LLM

Each merchant is scripted but reacts to what Chanakya actually does: they raise their worry when asked, give an
explicit yes when asked for consent, and otherwise acknowledge. The brain, the safety gate, the mock systems,
verification and the hand-off queue are the real ones, so the ledger shows exactly what a live call would.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from chanakya.actions.systems.tools import complete_onboarding
from chanakya.brain.contracts.schemas import MoveType
from chanakya.brain.mission_call import MissionCall
from chanakya.core import schemas as core

S = core.MissionState


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    merchant_id: str
    kind: core.SignalKind
    door: core.Door
    details: dict
    language: str
    opener: str
    worries: tuple[str, ...]
    consent: str | None
    filler: str
    expect: frozenset[core.MissionState]
    max_turns: int = 12


SCENARIOS = {
    s.name: s for s in [
        Scenario(
            "card_machine_sale", "Card-machine sale: resolve the per-swipe worry, send the WhatsApp link, verified DONE",
            "mer_anita", core.SignalKind.CARD_ATTEMPTS_NO_POS, core.Door.DATA, {"attempts": 12}, "hi-IN",
            "Haan ji, boliye?", ("Har card swipe pe kitna katega? Wahi dar hai.",),
            "Haan, theek hai, WhatsApp pe bhej do link.", "Achha, theek hai.", frozenset({S.DONE})),
        Scenario(
            "callback_followup", "Callback request: link sent, merchant forgets, reminder goes out, then verified DONE",
            "mer_ramesh", core.SignalKind.CALLBACK_REQUEST, core.Door.MERCHANT, {"product": "soundbox"}, "hi-IN",
            "Haan, maine callback maanga tha.", ("Koi hidden charge toh nahi hai na?",),
            "Haan ji, bhej dijiye link.", "Achha.", frozenset({S.DONE})),
        Scenario(
            "soundbox_service", "Offline Soundbox: find the real problem, book a technician with consent",
            "mer_gurpreet", core.SignalKind.SOUNDBOX_UNUSED, core.Door.DATA, {"days": 8}, "pa-IN",
            "ਹਾਂ ਜੀ, ਦੱਸੋ?", ("Soundbox ਠੀਕ ਤਰ੍ਹਾਂ ਨਹੀਂ ਬੋਲਦਾ।", "ਮਸ਼ੀਨ ਵਾਰ-ਵਾਰ ਬੰਦ ਹੋ ਜਾਂਦੀ ਹੈ।"),
            "ਹਾਂ ਜੀ, ਠੀਕ ਹੈ, technician ਭੇਜ ਦਿਓ।", "ਅੱਛਾ, ਠੀਕ ਹੈ।", frozenset({S.AWAITING_CONFIRMATION})),
        Scenario(
            "distressed_handoff", "Distressed merchant: stop selling, hand to a person with a context card",
            "mer_sharma", core.SignalKind.UPI_RISING_NO_SOUNDBOX, core.Door.DATA, {"growth_pct": 64}, "hi-IN",
            "Haan, boliye.", ("Mera payment fail ho gaya hai, ghar pe sab bahut pareshan hain, kisi insaan se baat karao.",),
            None, "Haan.", frozenset({S.ESCALATED})),
    ]
}


@dataclass
class ScenarioResult:
    scenario: str
    mission_id: str
    lines: list[tuple[str, str]] = field(default_factory=list)
    checks: list[tuple[str, bool]] = field(default_factory=list)
    state: str = ""
    outcome: str | None = None

    @property
    def ok(self) -> bool:
        return all(ok for _, ok in self.checks)


def merchant_reply(scenario: Scenario, last_move: MoveType | None, worries_left: list[str]) -> str:
    """What the scripted merchant says next, given Chanakya's last move."""
    if last_move == MoveType.CONFIRM_CONSENT and scenario.consent:
        return scenario.consent
    if worries_left:
        return worries_left.pop(0)
    return scenario.filler


async def open_mission(runtime, scenario: Scenario) -> core.Mission:
    """Open the scenario's mission through intake, or reuse the merchant's open mission for the same goal."""
    signal = core.MerchantSignal(merchant_id=scenario.merchant_id, kind=scenario.kind, door=scenario.door,
                                 source="demo scenario", details=scenario.details)
    mission, _ = await runtime.intake.ingest(signal)
    return mission


async def finish_onboarding(runtime, mission_id: str, after_reminder: bool) -> None:
    """The merchant completes the mock onboarding page, straight away or only after a reminder."""
    sessions = runtime.db.all("SELECT id FROM onboarding_sessions WHERE mission_id = ? ORDER BY created_at DESC",
                              mission_id)
    if not sessions:
        return
    if after_reminder:
        await runtime.fast_forward(timedelta(hours=2))  # first check: not done yet, a reminder is scheduled
        await runtime.fast_forward(timedelta(days=1))  # the WhatsApp reminder goes out
    complete_onboarding(runtime.db, sessions[0]["id"])
    if not await runtime.verifier.check_now(sessions[0]["id"]):
        await runtime.fast_forward(timedelta(hours=2))


async def run_scenario(runtime, name: str, llm=None, pause: float = 0.0, mission: core.Mission | None = None,
                       on_line: Callable[[str, str], Awaitable[None] | None] | None = None) -> ScenarioResult:
    """Play one scenario end to end on ``runtime`` (on ``mission`` if already opened) and check its outcome."""
    scenario = SCENARIOS[name]
    mission = mission or await open_mission(runtime, scenario)
    result = ScenarioResult(name, mission.id)
    call = MissionCall(runtime, mission.id, llm=llm)
    await call.start()

    async def line(speaker: str, text: str) -> None:
        result.lines.append((speaker, text))
        if on_line is not None:
            maybe = on_line(speaker, text)
            if asyncio.iscoroutine(maybe):
                await maybe
        if pause:
            await asyncio.sleep(pause)

    worries, merchant = list(scenario.worries), scenario.opener
    for _ in range(scenario.max_turns):
        await line("merchant", merchant)
        reply = await call.say(merchant, scenario.language)
        if reply is None:
            break
        await line("chanakya", reply)
        if not call.open or call.mission.state == S.AWAITING_CONFIRMATION:
            break
        merchant = merchant_reply(scenario, call.state.moves[-1].type, worries)

    if name in {"card_machine_sale", "callback_followup"}:
        await finish_onboarding(runtime, mission.id, after_reminder=name == "callback_followup")

    final = runtime.ledger.store.get(mission.id)
    result.state, result.outcome = final.state.value, final.outcome
    events = runtime.ledger.store.events(mission.id)
    kinds = [e.kind for e in events]
    executed = [e.payload["call"]["tool"] for e in events
                if e.kind == core.EventKind.ACTION_DECISION and e.payload["verdict"] == "executed"]
    result.checks = [
        (f"mission ends {'/'.join(s.value for s in scenario.expect)}", final.state in scenario.expect),
        ("Chanakya disclosed it is an AI before anything else", core.EventKind.AI_DISCLOSED in kinds),
        ("every turn, belief and plan is in the ledger",
         {core.EventKind.TURN_COMPLETED, core.EventKind.BELIEF_UPDATED, core.EventKind.PLAN_COMPUTED} <= set(kinds)),
    ]
    if scenario.consent:
        tool = {"soundbox_service": "book_field_visit"}.get(name, "send_onboarding_link")
        consent_seq = next((e.seq for e in events if e.kind == core.EventKind.CONSENT_GIVEN), None)
        action_seq = next((e.seq for e in events if e.kind == core.EventKind.ACTION_DECISION
                           and e.payload["call"]["tool"] == tool and e.payload["verdict"] == "executed"), None)
        result.checks.append((f"{tool} ran only after explicit consent",
                              consent_seq is not None and action_seq is not None and consent_seq < action_seq))
    if name == "callback_followup":
        reminders = [e for e in events if e.kind == core.EventKind.ACTION_DECISION
                     and e.payload["call"]["tool"] == "send_summary" and e.payload["verdict"] == "executed"]
        result.checks.append(("a WhatsApp reminder went out before DONE", bool(reminders)))
    if name == "distressed_handoff":
        cards = [c for c in runtime.handoffs.list() if c.mission_id == mission.id]
        result.checks.append(("a person got an urgent hand-off card", bool(cards) and cards[0].urgent))
        result.checks.append(("nothing was sold or sent", not executed))
    return result


async def run_all(runtime, names=None, llm=None, **kwargs) -> list[ScenarioResult]:
    """Run the named scenarios (all by default) one after another."""
    return [await run_scenario(runtime, name, llm=llm, **kwargs) for name in (names or list(SCENARIOS))]
