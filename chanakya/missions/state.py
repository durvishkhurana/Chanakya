"""Mission state machine (docs/IDEA.md 3.1)."""

from __future__ import annotations

from chanakya.core.interfaces import IllegalTransitionError
from chanakya.core.schemas import TERMINAL_STATES, MissionState

S = MissionState

ALLOWED: dict[MissionState, frozenset[MissionState]] = {
    S.CREATED: frozenset({S.SCHEDULED, S.CONTACTING, S.CLOSED_NOT_INTERESTED, S.ESCALATED, S.FAILED}),
    S.SCHEDULED: frozenset({S.CONTACTING, S.CLOSED_UNREACHABLE, S.CLOSED_NOT_INTERESTED, S.ESCALATED, S.FAILED}),
    S.CONTACTING: frozenset({S.IN_CONVERSATION, S.SCHEDULED, S.CLOSED_UNREACHABLE, S.FAILED}),
    S.IN_CONVERSATION: frozenset(
        {S.ACTION_PENDING, S.SCHEDULED, S.ESCALATED, S.CLOSED_NOT_INTERESTED, S.FAILED}
    ),
    S.ACTION_PENDING: frozenset({S.IN_CONVERSATION, S.AWAITING_CONFIRMATION, S.VERIFYING, S.ESCALATED, S.FAILED}),
    S.AWAITING_CONFIRMATION: frozenset(
        {S.VERIFYING, S.SCHEDULED, S.ESCALATED, S.CLOSED_NOT_INTERESTED, S.FAILED}
    ),
    S.VERIFYING: frozenset(
        {S.DONE, S.AWAITING_CONFIRMATION, S.SCHEDULED, S.ESCALATED, S.CLOSED_NOT_INTERESTED, S.FAILED}
    ),
    **{terminal: frozenset() for terminal in TERMINAL_STATES},
}


def check_transition(current: MissionState, target: MissionState) -> None:
    """Raise IllegalTransitionError unless ``current -> target`` is allowed."""
    if target not in ALLOWED[current]:
        raise IllegalTransitionError(f"{current} -> {target} is not allowed")
