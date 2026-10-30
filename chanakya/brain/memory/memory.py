"""Nearest-moment memory: what worked when a merchant said something like this, with a belief like this one.

Each remembered moment is the e5 embedding of the merchant's line plus the belief over the 13 worries at that
point, the (abstracted) move the agent made next, and how that call ended. A lookup finds the k most similar
moments and ranks their moves by the Wilson lower bound of similarity-weighted outcomes, so it replaces the
Strategy Forest's 24 fixed trigram clusters behind the same ``moves_for(state)`` hook.
"""

import hashlib
import json
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

from chanakya.brain.concern_bank import DATA, default_bank
from chanakya.brain.contracts.schemas import DialogueState, Move
from chanakya.brain.forest.forest import abstract, instantiate, wilson_lower

logger = logging.getLogger(__name__)

MEMORY = DATA / "neural" / "memory.npz"
K = 24
TEXT_WEIGHT = 0.65  # the merchant's words count most; the belief separates moments that read alike
DISCOUNT = 0.9  # credit fades with distance from the call's outcome, as in the forest


def belief_vector(probabilities: dict[str, float], concern_ids: list[str]) -> np.ndarray:
    """The belief as a unit vector in a fixed concern order."""
    vector = np.asarray([probabilities.get(cid, 0.0) for cid in concern_ids], dtype=np.float64)
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def moments(transcripts: list[dict]) -> list[dict]:
    """Decision points: each agent move with the merchant line before it, the belief then, and its credit."""
    found = []
    for transcript in transcripts:
        turns = transcript["turns"]
        agents = [i for i, t in enumerate(turns) if t["speaker"] == "agent" and t.get("move")]
        for position, index in enumerate(agents):
            merchant = next((turns[j]["text"] for j in range(index - 1, -1, -1) if turns[j]["speaker"] == "merchant"),
                            "")
            turn = turns[index]
            weight = DISCOUNT ** (len(agents) - position - 1)
            found.append({"text": merchant, "belief": turn.get("belief", {}),
                          "move": abstract(turn["move"], turn.get("top_concern")),
                          "success": weight * (transcript["outcome"] == "consented"), "weight": weight})
    return found


class SemanticMemory:
    """Remembered moments and a k-nearest lookup over them; implements the planner's ``moves_for`` hook."""

    def __init__(self, encoder, text: np.ndarray, belief: np.ndarray, moves: list[str], successes: np.ndarray,
                 weights: np.ndarray, concern_ids: list[str], metadata: dict | None = None, k: int = K):
        self.encoder = encoder
        self.text = np.asarray(text, dtype=np.float32)
        self.belief = np.asarray(belief, dtype=np.float32)
        self.moves = list(moves)
        self.successes = np.asarray(successes, dtype=np.float64)
        self.weights = np.asarray(weights, dtype=np.float64)
        self.concern_ids = list(concern_ids)
        self.metadata = metadata or {}
        self.k = k
        self.last_lookup_ms = 0.0

    @classmethod
    def build(cls, transcripts: list[dict], encoder, seed: int = 0, k: int = K) -> "SemanticMemory":
        """Embed every decision point of ``transcripts``."""
        concern_ids = default_bank().ids
        found = moments(transcripts)
        text = encoder.encode([m["text"] for m in found])
        belief = np.vstack([belief_vector(m["belief"], concern_ids) for m in found])
        digest = hashlib.sha256(json.dumps(transcripts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        metadata = {"encoder": encoder.name, "seed": seed, "date": datetime.now(UTC).date().isoformat(),
                    "data_hash": digest, "transcripts": len(transcripts), "moments": len(found)}
        return cls(encoder, text, belief, [m["move"] for m in found], np.asarray([m["success"] for m in found]),
                   np.asarray([m["weight"] for m in found]), concern_ids, metadata, k)

    def lookup(self, merchant_text: str, probabilities: dict[str, float],
               limit: int = 4) -> list[tuple[str, float, int]]:
        """The best moves in the k most similar moments, by Wilson lower bound of similarity-weighted outcomes."""
        started = time.perf_counter()
        query = self.encoder.encode([merchant_text])[0].astype(np.float32)
        similarity = TEXT_WEIGHT * (self.text @ query) + (1 - TEXT_WEIGHT) * (
            self.belief @ belief_vector(probabilities, self.concern_ids).astype(np.float32))
        k = min(self.k, len(similarity))
        nearest = np.argpartition(-similarity, k - 1)[:k]
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
        for index in nearest:
            weight = max(float(similarity[index]), 0.0)
            entry = totals[self.moves[index]]
            entry[0] += weight * self.successes[index]
            entry[1] += weight * self.weights[index]
            entry[2] += 1
        ranked = sorted(((move, wilson_lower(s, n), count) for move, (s, n, count) in totals.items()),
                        key=lambda item: (-item[1], -item[2], item[0]))[:limit]
        self.last_lookup_ms = (time.perf_counter() - started) * 1000
        return ranked

    def moves_for(self, state: DialogueState, limit: int = 3) -> list[tuple[Move, float]]:
        """Concrete candidate moves for a live state with their values, best first (the forest's interface)."""
        from chanakya.brain import moves as lib

        open_concerns = lib.open_concerns(state)
        top = open_concerns[0][0] if open_concerns else None
        found = []
        for key, value, _ in self.lookup(state.last_merchant_text(), state.belief.probabilities, limit=limit + 3):
            move = instantiate(key, top)
            if move is not None and all(move.key() != m.key() for m, _ in found):
                found.append((move, value))
        return found[:limit]

    def save(self, path: Path = MEMORY) -> None:
        """Write the moments (vectors as float16) and metadata to a ``.npz``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, text=self.text.astype(np.float16), belief=self.belief.astype(np.float16),
                            moves=np.asarray(self.moves), successes=self.successes, weights=self.weights,
                            concern_ids=np.asarray(self.concern_ids), metadata=np.asarray(json.dumps(self.metadata)))

    @classmethod
    def load(cls, encoder, path: Path = MEMORY, k: int = K) -> "SemanticMemory":
        """Read a memory; it only answers queries embedded by the encoder that built it."""
        with np.load(path) as data:
            metadata = json.loads(str(data["metadata"]))
            if metadata.get("encoder") != encoder.name:
                raise ValueError(f"{path} was built with {metadata.get('encoder')}, not {encoder.name}")
            return cls(encoder, data["text"].astype(np.float32), data["belief"].astype(np.float32),
                       data["moves"].tolist(), data["successes"], data["weights"], data["concern_ids"].tolist(),
                       metadata, k)


class MemoryUnavailableError(RuntimeError):
    """The neural memory needs the e5 encoder and data/neural/memory.npz."""


@lru_cache(maxsize=1)
def default_memory() -> SemanticMemory:
    """The committed memory with the real encoder; raises MemoryUnavailableError when either is missing."""
    from chanakya.neural.encoder import load_encoder

    encoder = load_encoder()
    if encoder is None or not MEMORY.exists():
        raise MemoryUnavailableError("PLANNER_MEMORY=neural needs the e5 encoder and data/neural/memory.npz")
    return SemanticMemory.load(encoder)


def configured_memory(planner_memory: str):
    """The planner's memory for a ``PLANNER_MEMORY`` setting; ``neural`` falls back to the forest with one log line."""
    from chanakya.brain.forest.forest import default_forest

    if planner_memory == "neural":
        try:
            return default_memory()
        except MemoryUnavailableError as error:
            logger.warning("%s; using the Strategy Forest", error)
    return default_forest()
