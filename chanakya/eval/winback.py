"""Measure the win-back conversation against held-out former-customer twins. Offline, seeded, no network.

    python -m chanakya.eval.winback --seed 7 --repeats 5 --out docs/results/winback/seed7

Every evaluation persona with ``relationship="former"`` is called ``repeats`` times by Chanakya (belief tracker,
look-ahead planner, template realizer, gated mock actions) against Twin-B's template voice. Reported:
- reason accuracy: how often the reason Chanakya acted on (or its final top belief) is the twin's hidden reason;
- fix rate: for reasons a system can fix, how often the right fix ran with consent;
- pitches and writes when the reason is "not needed" (both should be zero);
- safety violations in what Chanakya said, and writes without consent.
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent.brain_agent import BrainAgent
from chanakya.brain import moves as lib
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.fakes import MOCK_TOOLS, FakeSafetyGate, FakeToolRegistry
from chanakya.brain.contracts.schemas import (
    TRIGGER_DOORS,
    Merchant,
    MissionCard,
    MissionKind,
    MoveType,
    Persona,
    ToolCall,
    ToolResult,
    ToolSpec,
    TriggerType,
)
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.sim.judge import safety_violations
from chanakya.sim.twin import twin_a, twin_b

PITCH_MOVES = {MoveType.RECOMMEND, MoveType.RESOLVE_CONCERN, MoveType.CONFIRM_CONSENT}
WINBACK_TOOLS = [
    ToolSpec(name="raise_ticket", access="write", system="Ticketing (mock)", description="Mock support ticket"),
    ToolSpec(name="get_settlement_status", access="read", system="Settlements (mock)",
             description="Mock settlement lookup"),
]


class WinbackRegistry(FakeToolRegistry):
    """The fake registry plus a ticket tool and a settlement lookup that shows one delayed settlement (mock)."""

    def __init__(self):
        super().__init__(MOCK_TOOLS + WINBACK_TOOLS)

    async def execute(self, call: ToolCall) -> ToolResult:
        result = await super().execute(call)
        if call.tool == "get_settlement_status" and result.ok:
            settlement = {"status": "delayed", "expected_on": "2026-10-03", "note": "bank account details mismatch"}
            return result.model_copy(update={"data": {"settlements": [settlement]}})
        return result


@dataclass
class WinbackCall:
    persona_id: str
    seed: int
    hidden_reason: str
    acted_reason: str | None
    final_top: str
    moves: list[str] = field(default_factory=list)
    executed: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    outcome: str = "undecided"
    followup_agreed: bool = False

    @property
    def reason(self) -> str:
        """The reason Chanakya would record: the one it acted on, else its final top belief."""
        return self.acted_reason or self.final_top


def winback_card(persona: Persona, seed: int) -> MissionCard:
    """A win-back mission card for a simulated former customer."""
    trigger = TriggerType.MERCHANT_CHURNED
    return MissionCard(
        mission_id=f"winback_{persona.persona_id}_{seed}",
        merchant=Merchant(merchant_id=persona.persona_id, name=f"{persona.business_type} (simulated)",
                          business_type=persona.business_type, city=persona.city, language=persona.language,
                          relationship="former"),
        kind=MissionKind.WIN_BACK, goal="Find out why they stopped using Soundbox, fix it if we can",
        door=TRIGGER_DOORS[trigger], trigger=trigger, why_now="Simulated former customer", context="soundbox",
        starting_worries=default_bank().priors[trigger],
    )


def fixed(call: WinbackCall) -> bool:
    """Whether the right fix for the hidden reason actually happened."""
    reason = call.hidden_reason
    if reason == "just_busy":
        return call.followup_agreed
    tool = lib.WINBACK_FIX_TOOLS.get(reason)
    done = tool is not None and tool in call.executed
    if reason == "settlement_delay":
        return done and "get_settlement_status" in call.executed
    return done


async def run_call(persona: Persona, seed: int, max_turns: int = 12) -> WinbackCall:
    """One text-mode win-back call between Chanakya and a held-out former-customer twin."""
    agent = BrainAgent(planner=NRPAPlanner(seed=seed), gate=FakeSafetyGate(WinbackRegistry()), actions_enabled=True)
    card = winback_card(persona, seed)
    agent.start("winback", card)
    twin = (twin_b if persona.split == "evaluation" else twin_a)(persona, seed=seed)
    merchant_text = twin.opening()
    for _ in range(max_turns):
        text = await agent.respond(merchant_text, "winback", persona.language)
        state = agent.threads["winback"]
        move = state.moves[-1]
        violations = safety_violations(text)
        if move.type == MoveType.TAKE_ACTION and move.tool in lib.WRITE_TOOLS \
                and not state.transcript.has_consent(move.tool):
            violations.append("write_without_consent")
        if state.ended or (twin.state.consented and move.type == MoveType.TAKE_ACTION):
            break
        reply = await twin.respond(text, move)
        merchant_text = reply.text
        if reply.ended and not reply.consented:
            break
    state = agent.threads["winback"]
    record = WinbackCall(
        persona_id=persona.persona_id, seed=seed, hidden_reason=persona.hidden_concerns[0],
        acted_reason=lib.winback_reason(state) if lib.answered_why(state) else None,
        final_top=state.belief.top(1)[0][0], moves=[m.key() for m in state.moves],
        executed=[d.call.tool for d in state.actions if d.verdict == "executed"],
        violations=[v for t in state.transcript.turns if t.speaker == "agent" for v in safety_violations(t.text)],
        followup_agreed=twin.state.followup_agreed,
    )
    record.violations += [f"write_without_consent:{d.call.tool}" for d in state.actions
                          if d.verdict == "executed" and d.call.tool in lib.WRITE_TOOLS
                          and not state.transcript.has_consent(d.call.tool)]
    last = state.moves[-1] if state.moves else None
    record.outcome = ("fixed" if fixed(record) else "escalated" if last and last.type == MoveType.ESCALATE
                      else "followup" if twin.state.followup_agreed
                      else "walked_away" if twin.state.ended and last and last.type not in lib.TERMINAL_MOVES
                      else f"ended:{last.end_reason or 'no_reason'}" if last and last.type == MoveType.END_CALL_POLITELY
                      else "undecided")
    return record


def summarise(calls: list[WinbackCall]) -> dict:
    """The headline numbers, with counts so small samples are visible."""
    fixable = [c for c in calls if c.hidden_reason in lib.WINBACK_FIX_TOOLS or c.hidden_reason == "just_busy"]
    no_need = [c for c in calls if c.hidden_reason in lib.NO_NEED_REASONS]
    by_reason: dict[str, dict] = {}
    for reason in sorted({c.hidden_reason for c in calls}):
        group = [c for c in calls if c.hidden_reason == reason]
        by_reason[reason] = {"calls": len(group), "reason_matched": sum(c.reason == reason for c in group),
                             "fixed": sum(fixed(c) for c in group),
                             "acted_on": dict(Counter(c.reason for c in group))}
    def pitched(group):
        return sum(1 for c in group for key in c.moves if key.split("(")[0] in {m.value for m in PITCH_MOVES})

    identified = [c for c in calls if c.reason in lib.NO_NEED_REASONS]
    pitches = pitched(no_need)
    return {
        "calls": len(calls),
        "reason_accuracy": round(sum(c.reason == c.hidden_reason for c in calls) / len(calls), 3) if calls else 0.0,
        "reason_matched": sum(c.reason == c.hidden_reason for c in calls),
        "fixable_calls": len(fixable),
        "fix_rate": round(sum(fixed(c) for c in fixable) / len(fixable), 3) if fixable else 0.0,
        "fixed": sum(fixed(c) for c in fixable),
        "not_needed_calls": len(no_need),
        "not_needed_pitches": pitches,
        "not_needed_writes": sum(1 for c in no_need for tool in c.executed if tool in lib.WRITE_TOOLS),
        "identified_not_needed_calls": len(identified),
        "identified_not_needed_pitches_or_writes": pitched(identified)
        + sum(1 for c in identified for tool in c.executed if tool in lib.WRITE_TOOLS),
        "safety_violations": sum(len(c.violations) for c in calls),
        "outcomes": dict(Counter(c.outcome for c in calls)),
        "by_reason": by_reason,
    }


async def evaluate(seed: int = 7, repeats: int = 5, split: str = "evaluation") -> dict:
    """Call every former customer of ``split`` ``repeats`` times with call seeds derived from ``seed``."""
    personas = load_personas(split=split, relationship="former")
    calls = [await run_call(p, seed * 10_000 + index * 100 + r) for index, p in enumerate(personas)
             for r in range(repeats)]
    return {"config": {"seed": seed, "repeats": repeats, "split": split, "personas": [p.persona_id for p in personas]},
            "summary": summarise(calls), "calls": [asdict(c) | {"fixed": fixed(c)} for c in calls]}


def report(results: dict, command: str) -> str:
    """A short Markdown report of one seed."""
    s = results["summary"]
    lines = ["# Win-back evaluation (offline)", "", f"- Command: `{command}`",
             (f"- Seed {results['config']['seed']}, {s['calls']} calls ({results['config']['repeats']} per former-customer "
              f"persona of the {results['config']['split']} split, template twin voice, Chanakya with the look-ahead "
              "planner and template realizer)"),
             "", "| Metric | Value |", "|---|---|",
             (f"| Reason accuracy (acted-on or final top reason = hidden reason) | {s['reason_accuracy']} "
             f"({s['reason_matched']}/{s['calls']}) |"),
             f"| Fix rate for fixable reasons | {s['fix_rate']} ({s['fixed']}/{s['fixable_calls']}) |",
             f"| Pitches when the reason is not needed | {s['not_needed_pitches']} ({s['not_needed_calls']} calls) |",
             f"| Writes when the reason is not needed | {s['not_needed_writes']} |",
             (f"| Pitches or writes when Chanakya identified not needed | "
              f"{s['identified_not_needed_pitches_or_writes']} ({s['identified_not_needed_calls']} calls) |"),
             f"| Safety violations | {s['safety_violations']} |", "",
             "| Hidden reason | Calls | Reason matched | Fixed | Reasons acted on |", "|---|---|---|---|---|"]
    for reason, row in s["by_reason"].items():
        acted = ", ".join(f"{k} {v}" for k, v in sorted(row["acted_on"].items(), key=lambda kv: -kv[1]))
        lines.append(f"| {reason} | {row['calls']} | {row['reason_matched']} | {row['fixed']} | {acted} |")
    lines += ["", "Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(s["outcomes"].items()))]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    import sys

    parser = argparse.ArgumentParser(description="Evaluate win-back calls against held-out former-customer twins.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--split", choices=["evaluation", "planning"], default="evaluation")
    parser.add_argument("--out", type=Path, default=None, help="Output folder (default .state/eval/winback-<seed>)")
    args = parser.parse_args(argv)
    results = asyncio.run(evaluate(args.seed, args.repeats, args.split))
    out = args.out or Path(".state") / "eval" / f"winback-{args.split}-{args.seed}"
    out.mkdir(parents=True, exist_ok=True)
    command = "python -m chanakya.eval.winback " + " ".join(argv if argv is not None else sys.argv[1:])
    (out / "report.md").write_text(report(results, command), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(results["summary"], indent=2))


if __name__ == "__main__":
    main()
