"""Hesitation cues from transcript timing and wording: pause before answering, fillers, speech rate."""

import re
from dataclasses import dataclass

from chanakya.brain.contracts.schemas import Turn

FILLERS = re.compile(
    r"\b(umm+|hmm+|uh+|er+|matlab|woh|dekhiye|dekho|actually|basically|like|i mean|pata nahi|shayad)\b"
    r"|हम्म|मतलब|देखिए|शायद|पता नहीं|ਹੰਮ|ਮਤਲਬ|ਸ਼ਾਇਦ|\.\.\.|…",
    re.IGNORECASE,
)
# A short "haan" or "theek hai" answer after a long pause reads as polite deflection, not agreement.
DEFLECTIONS = re.compile(r"^\s*(haan|han|ha|theek hai|ok|okay|achha|accha|hmm|हाँ|ठीक है|अच्छा|ਹਾਂ|ਠੀਕ ਹੈ)\W*$",
                         re.IGNORECASE)
LONG_PAUSE_MS = 1500
SLOW_WORDS_PER_SECOND = 1.5
# Worries merchants tend to hold back rather than say outright; hesitation points towards them.
UNSPOKEN_CONCERNS = ("hidden_charges", "trust_in_caller", "data_privacy", "rental_cost", "setup_hassle")


@dataclass(frozen=True)
class Hesitation:
    """How hesitant a turn sounds, from 0 (fluent) to 1 (very hesitant), with its parts."""

    score: float
    pause: float
    fillers: float
    slow: float
    deflection: bool


def hesitation(turn: Turn) -> Hesitation:
    """Score hesitation from the turn's pause, fillers, speech rate and short deflections."""
    pause = min(1.0, (turn.pause_before_ms or 0) / (2 * LONG_PAUSE_MS))
    words = max(1, len(turn.text.split()))
    fillers = min(1.0, len(FILLERS.findall(turn.text)) / max(2, words / 3))
    slow = 0.0
    if turn.duration_ms:
        rate = words / (turn.duration_ms / 1000)
        slow = min(1.0, max(0.0, (SLOW_WORDS_PER_SECOND - rate) / SLOW_WORDS_PER_SECOND))
    deflection = bool(DEFLECTIONS.match(turn.text)) and (turn.pause_before_ms or 0) >= LONG_PAUSE_MS
    score = min(1.0, 0.45 * pause + 0.35 * fillers + 0.2 * slow + (0.25 if deflection else 0.0))
    return Hesitation(round(score, 3), round(pause, 3), round(fillers, 3), round(slow, 3), deflection)
