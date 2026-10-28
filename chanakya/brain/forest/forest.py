"""Strategy Forest: which move worked best in a conversation state like this one (after METRO, arXiv 2604.11427).

States are embedded as hashed character-trigram vectors (works across Hindi, Hinglish, Punjabi and
English without a model download), clustered with seeded k-means, and every (cluster, move) keeps the
outcomes of the calls it appeared in. Move values are Wilson lower bounds, so a move seen succeeding
twice is not trusted over one with a long record.
"""

import json
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from chanakya.brain.belief import trigrams
from chanakya.core.schemas import DialogueState, Move

DIMENSIONS = 512
Z = 1.96


def embed(text: str) -> list[float]:
    """A unit-length hashed trigram vector. Deterministic: Python's string hash is not used."""
    vector = [0.0] * DIMENSIONS
    for gram in trigrams(text):
        h = 2166136261
        for byte in gram.encode("utf-8"):
            h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
        vector[h % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two unit vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def wilson_lower(successes: float, trials: float, z: float = Z) -> float:
    """Lower bound of the Wilson score interval (Wilson, 1927)."""
    if trials <= 0:
        return 0.0
    p = successes / trials
    centre = p + z * z / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return max(0.0, (centre - margin) / (1 + z * z / trials))


def _hash(token: str, size: int) -> int:
    h = 2166136261
    for byte in token.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return h % size


CONTEXT_DIMENSIONS = 64
CONTEXT_WEIGHT = 0.45


def state_vector(merchant_text: str, last_move: str | None, top_concern: str | None) -> list[float]:
    """The merchant's words dominate; the previous move and the top worry get their own small blocks."""
    words = embed(merchant_text)
    move_block, concern_block = [0.0] * CONTEXT_DIMENSIONS, [0.0] * CONTEXT_DIMENSIONS
    move_block[_hash(last_move or "START", CONTEXT_DIMENSIONS)] = CONTEXT_WEIGHT
    concern_block[_hash(top_concern or "none", CONTEXT_DIMENSIONS)] = CONTEXT_WEIGHT
    vector = words + move_block + concern_block
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@dataclass
class Step:
    """One decision point in a transcript: the state the agent saw and the move it made."""

    merchant_text: str
    last_move: str | None
    top_concern: str | None
    move: str
    steps_to_end: int


@dataclass
class Node:
    """One cluster of similar states with the outcome record of each move made from it."""

    centroid: list[float]
    label: str
    stats: dict[str, list[float]] = field(default_factory=dict)  # move key -> [successes, trials]

    def ranked(self, limit: int = 4) -> list[tuple[str, float, int]]:
        """Moves by Wilson lower bound, with their trial counts."""
        scored = [(move, wilson_lower(s, n), int(n)) for move, (s, n) in self.stats.items()]
        return sorted(scored, key=lambda item: (-item[1], -item[2], item[0]))[:limit]


class StrategyForest:
    """Cluster states, value moves by outcome, look up the best moves for a new state."""

    def __init__(self, nodes: list[Node] | None = None, discount: float = 0.9):
        self.nodes = nodes or []
        self.discount = discount
        self.last_lookup_ms = 0.0

    @staticmethod
    def kmeans(vectors: list[list[float]], k: int, seed: int, rounds: int = 12) -> list[list[float]]:
        """Seeded spherical k-means; returns unit centroids."""
        rng = random.Random(seed)
        centroids = [list(v) for v in rng.sample(vectors, min(k, len(vectors)))]
        for _ in range(rounds):
            groups = defaultdict(list)
            for vector in vectors:
                groups[max(range(len(centroids)), key=lambda i: cosine(vector, centroids[i]))].append(vector)
            for index, members in groups.items():
                summed = [sum(column) for column in zip(*members, strict=True)]
                norm = math.sqrt(sum(v * v for v in summed)) or 1.0
                centroids[index] = [v / norm for v in summed]
        return centroids

    @classmethod
    def fit(cls, transcripts: list[dict], k: int = 24, seed: int = 0, discount: float = 0.9) -> "StrategyForest":
        """Build the forest from labelled transcripts (see ``steps``)."""
        steps = [(step, t["outcome"]) for t in transcripts for step in cls.steps(t)]
        vectors = [state_vector(s.merchant_text, s.last_move, s.top_concern) for s, _ in steps]
        centroids = cls.kmeans(vectors, k, seed)
        forest = cls([Node(centroid=c, label="") for c in centroids], discount)
        examples = defaultdict(list)
        for (step, outcome_), vector in zip(steps, vectors, strict=True):
            index = forest.nearest_index(vector)
            forest._record(forest.nodes[index], step, outcome_)
            examples[index].append(step.merchant_text)
        for index, node in enumerate(forest.nodes):
            node.label = (examples[index] or [""])[0][:60]
        return forest

    @staticmethod
    def steps(transcript: dict) -> list[Step]:
        """Decision points of a transcript: each agent move with the merchant turn just before it."""
        turns = transcript["turns"]
        agent_moves = [i for i, t in enumerate(turns) if t["speaker"] == "agent" and t.get("move")]
        result, last = [], None
        for position, index in enumerate(agent_moves):
            merchant = next((turns[j]["text"] for j in range(index - 1, -1, -1) if turns[j]["speaker"] == "merchant"), "")
            top = turns[index].get("top_concern")
            result.append(Step(merchant, last, top, abstract(turns[index]["move"], top), len(agent_moves) - position - 1))
            last = turns[index]["move"]
        return result

    def _record(self, node: Node, step: Step, outcome_: str) -> None:
        # Credit decays with distance from the outcome: earlier moves get less of it.
        weight = self.discount ** step.steps_to_end
        successes, trials = node.stats.get(step.move, [0.0, 0.0])
        node.stats[step.move] = [successes + weight * (outcome_ == "consented"), trials + weight]

    def nearest_index(self, vector: list[float]) -> int:
        """Index of the closest cluster."""
        return max(range(len(self.nodes)), key=lambda i: cosine(vector, self.nodes[i].centroid))

    def lookup(self, merchant_text: str, last_move: str | None, top_concern: str | None,
               limit: int = 4) -> list[tuple[str, float, int]]:
        """One embedding lookup: the best moves for this state, by Wilson lower bound."""
        started = time.perf_counter()
        node = self.nodes[self.nearest_index(state_vector(merchant_text, last_move, top_concern))]
        moves = node.ranked(limit)
        self.last_lookup_ms = (time.perf_counter() - started) * 1000
        return moves

    def lookup_state(self, state: DialogueState, limit: int = 4) -> list[tuple[str, float, int]]:
        """Lookup for a live dialogue state."""
        top = state.belief.top(1)[0][0] if state.belief.probabilities else None
        return self.lookup(state.last_merchant_text(), state.moves[-1].key() if state.moves else None, top, limit)

    def moves_for(self, state: DialogueState, limit: int = 3) -> list[tuple[Move, float]]:
        """Concrete candidate moves for a live state with their Wilson values, best first."""
        from chanakya.brain import moves as lib

        open_concerns = lib.open_concerns(state)
        top = open_concerns[0][0] if open_concerns else None
        last = state.moves[-1].key() if state.moves else None
        found = []
        for key, value, _ in self.lookup(state.last_merchant_text(), last, top, limit=limit + 3):
            move = instantiate(key, top)
            if move is not None and all(move.key() != m.key() for m, _ in found):
                found.append((move, value))
        return found[:limit]

    def update(self, transcript: dict) -> None:
        """Add a completed mission's outcome so move values improve over time."""
        for step in self.steps(transcript):
            vector = state_vector(step.merchant_text, step.last_move, step.top_concern)
            self._record(self.nodes[self.nearest_index(vector)], step, transcript["outcome"])

    def save(self, path: Path) -> None:
        """Write the forest as JSON."""
        data = {"discount": self.discount, "nodes": [
            {"label": n.label, "centroid": [round(v, 5) for v in n.centroid], "stats": n.stats} for n in self.nodes]}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "StrategyForest":
        """Read a forest written by ``save``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Node(n["centroid"], n["label"], n["stats"]) for n in data["nodes"]], data["discount"])


TOP = "@top"


def abstract(key: str, top_concern: str | None) -> str:
    """Generalise a move aimed at the belief's top worry, e.g. ``RESOLVE_CONCERN(@top)``."""
    if top_concern and key.endswith(f"({top_concern})") and key.split("(")[0] in {"PROBE_CONCERN", "RESOLVE_CONCERN"}:
        return key.replace(f"({top_concern})", f"({TOP})")
    return key


def instantiate(key: str, top_concern: str | None) -> Move | None:
    """A concrete move for this state, filling ``@top`` with the current top open worry."""
    if TOP in key:
        if not top_concern:
            return None
        key = key.replace(TOP, top_concern)
    return parse_move(key)


def parse_move(key: str) -> Move:
    """Turn a move key such as ``RESOLVE_CONCERN(rental_cost)`` back into a ``Move``."""
    from chanakya.brain.moves import PRODUCTS, READ_TOOLS, WRITE_TOOLS
    from chanakya.core.schemas import MoveType

    name, _, target = key.partition("(")
    target = target.rstrip(")") or None
    move_type = MoveType(name)
    if move_type in {MoveType.PROBE_CONCERN, MoveType.RESOLVE_CONCERN}:
        return Move(type=move_type, concern=target)
    if move_type == MoveType.RECOMMEND:
        return Move(type=move_type, product=target if target in PRODUCTS else None)
    if move_type in {MoveType.CONFIRM_CONSENT, MoveType.TAKE_ACTION}:
        return Move(type=move_type, tool=target if target in WRITE_TOOLS | READ_TOOLS else None)
    return Move(type=move_type)


def default_forest() -> "StrategyForest | None":
    """The forest mined into data/forest/forest.json, or ``None`` if it has not been generated."""
    from chanakya.brain.concern_bank import DATA

    path = DATA / "forest" / "forest.json"
    return StrategyForest.load(path) if path.exists() else None
