"""What is known at a look-ahead leaf, as a fixed-length vector for the value network."""

import numpy as np

from chanakya.brain import moves as lib
from chanakya.brain.contracts.schemas import DialogueState, MoveType
from chanakya.sim.judge import TwinState, consent_chance

MOVE_TYPES = [m.value for m in MoveType]
FEATURES = [
    "willingness", "patience", "unresolved", "voiced_unresolved", "resolved", "twin_turns", "declined",
    "worry_voiced", "disclosed", "consent_asks", "belief_top1", "belief_top2", "belief_top3", "consent_chance",
    "rollout_turns", *[f"last_{m.lower()}" for m in MOVE_TYPES], "last_none",
]


def last_move_type(state: TwinState) -> str | None:
    """The type of the twin's last agent move, from its key such as ``RESOLVE_CONCERN(hidden_charges)``."""
    return state.last_move_key.split("(")[0] if state.last_move_key else None


def leaf_features(state: TwinState, dialogue: DialogueState | None, turns: int) -> np.ndarray:
    """The simulated twin's hidden state, the conversation so far and the look-ahead depth, as numbers."""
    top = [p for _, p in lib.open_belief(dialogue).top(3)] if dialogue is not None else []
    top += [0.0] * (3 - len(top))
    asks = sum(1 for m in dialogue.moves if m.type == MoveType.CONFIRM_CONSENT) if dialogue is not None else 0
    last = last_move_type(state)
    one_hot = [1.0 if last == m else 0.0 for m in MOVE_TYPES] + [1.0 if last is None else 0.0]
    values = [
        state.willingness, state.patience, len(state.unresolved) / 3, len(state.voiced & state.unresolved) / 3,
        len(state.resolved) / 3, min(state.turns, 16) / 16, float(state.declined), float(state.last_voiced is not None),
        float(state.disclosed), min(asks, 3) / 3, *top, consent_chance(state), turns / 4, *one_hot,
    ]
    return np.asarray(values, dtype=np.float64)
