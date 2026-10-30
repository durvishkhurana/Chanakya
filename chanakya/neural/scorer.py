"""The embedding worry scorer (task N1) and the one place that picks a scorer from ``WORRY_SCORER``."""

import logging
import os
from pathlib import Path

from chanakya.brain.belief import LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import DATA

logger = logging.getLogger(__name__)

HEAD = DATA / "neural" / "worry_head.npz"


class EmbeddingScorer:
    """Implements the belief tracker's scorer interface with the encoder and the trained worry head.

    Its scores are calibrated probabilities, so it exposes ``base_rates``: the tracker then turns each score
    into a Bayesian odds ratio against the training base rate instead of the lexical scorer's tuned sharpening.
    """

    name = "embedding"

    def __init__(self, encoder, head):
        self.encoder = encoder
        self.head = head
        self.base_rates = head.base_rates

    async def score(self, text: str, history) -> dict[str, float]:
        probabilities = self.head.probabilities(self.encoder.encode([text]))[0]
        return {cid: float(p) for cid, p in zip(self.head.concerns, probabilities, strict=True)}


def load_embedding_scorer(head_path: Path = HEAD) -> EmbeddingScorer | None:
    """The embedding scorer, or None when the encoder, its libraries or the trained head are missing."""
    try:
        from chanakya.neural.encoder import load_encoder
        from chanakya.neural.head import WorryHead
    except ImportError as error:
        logger.info("embedding scorer unavailable: %s", error)
        return None
    encoder = load_encoder()
    if encoder is None or not head_path.exists():
        return None
    return EmbeddingScorer(encoder, WorryHead.load(head_path))


def configured_worry_scorer() -> str | None:
    """``WORRY_SCORER`` when it is set; None keeps the caller's own default."""
    if not os.getenv("WORRY_SCORER", "").strip():
        return None
    from chanakya.core.config import Settings

    return Settings.from_env().worry_scorer


def select_scorer(kind: str | None, bank, llm=None, timeout_s: float | None = None):
    """The scorer for ``kind``. None means the old default: the LLM scorer when there is an LLM, else lexical.

    ``embedding`` falls back to lexical, with one log line, when the model or head is missing.
    """
    if kind is None:
        kind = "llm" if llm is not None else "lexical"
    if kind == "embedding":
        scorer = load_embedding_scorer()
        if scorer is not None:
            return scorer
        logger.warning("WORRY_SCORER=embedding but the model or head is missing; using the lexical scorer")
        return LexicalScorer(bank)
    if kind == "llm" and llm is not None:
        return LLMScorer(llm, bank, timeout_s=timeout_s)
    return LexicalScorer(bank)
