"""Walk-away calibration: how scripted agents fare against the twins.

``python -m chanakya.sim.calibration`` prints the decline and consent rates the tests check.
"""

import asyncio
import statistics
from collections.abc import Callable

from chanakya.brain.concern_bank import load_personas
from chanakya.brain.contracts.schemas import Move, MoveType, Persona

from .twin import SimulatedMerchant, twin_a

SEND = "send_onboarding_link"


def naive_script(persona: Persona) -> list[Move]:
    """An untreated agent: pitches and asks for a yes without ever addressing a concern."""
    pitch = Move(type=MoveType.RECOMMEND, product="soundbox")
    ask = Move(type=MoveType.CONFIRM_CONSENT, tool=SEND)
    return [Move(type=MoveType.DISCLOSE_AND_GREET), pitch, ask, Move(type=MoveType.DISCOVER_NEED), pitch, ask]


def oracle_script(persona: Persona) -> list[Move]:
    """An agent that knows the hidden concerns: probe and resolve each, recommend, then ask."""
    moves = [Move(type=MoveType.DISCLOSE_AND_GREET), Move(type=MoveType.DISCOVER_NEED)]
    for concern in persona.hidden_concerns:
        moves += [Move(type=MoveType.PROBE_CONCERN, concern=concern), Move(type=MoveType.RESOLVE_CONCERN, concern=concern)]
    return moves + [Move(type=MoveType.RECOMMEND, product="soundbox"), Move(type=MoveType.CONFIRM_CONSENT, tool=SEND)]


async def play(twin: SimulatedMerchant, moves: list[Move]) -> str:
    """Play scripted moves; return ``consented``, ``declined`` (said no or hung up) or ``undecided``."""
    twin.opening()
    for move in moves:
        reply = await twin.respond(f"[{move.key()}]", move)
        if reply.consented:
            return "consented"
        if reply.ended:
            return "declined"
    return "declined" if twin.state.declined else "undecided"


def rates(script: Callable[[Persona], list[Move]], seeds: range = range(5), split: str = "planning") -> dict:
    """Outcome shares for ``script`` across non-adversarial personas and ``seeds``."""
    personas = [p for p in load_personas(split=split) if not p.adversarial]

    async def run():
        return [await play(twin_a(p, seed=seed), script(p)) for seed in seeds for p in personas]

    outcomes = asyncio.run(run())
    return {kind: round(outcomes.count(kind) / len(outcomes), 3) for kind in ("consented", "declined", "undecided")}


def main() -> None:
    for name, script in (("naive", naive_script), ("oracle", oracle_script)):
        per_seed = [rates(script, range(seed, seed + 1))["declined"] for seed in range(5)]
        print(name, rates(script), "declined per seed:", per_seed, "stdev", round(statistics.pstdev(per_seed), 3))


if __name__ == "__main__":
    main()
