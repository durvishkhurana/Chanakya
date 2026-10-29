"""Load and validate the Concern Bank, the trigger priors and the merchant personas."""

import json
from functools import lru_cache
from pathlib import Path

from chanakya.brain.contracts.schemas import Concern, Persona, TriggerType

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def knowledge_node_ids(directory: Path = DATA / "knowledge") -> set[str]:
    """Return every node ID in the sourced PageIndex knowledge files."""
    ids: set[str] = set()

    def walk(nodes):
        for node in nodes:
            if node.get("node_id"):
                ids.add(node["node_id"])
            walk(node.get("nodes", []))

    for path in sorted(directory.glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")).get("tree", {}).get("result", []))
    return ids


def load_concerns(path: Path = DATA / "concerns" / "concerns.json") -> dict[str, Concern]:
    """Return the Concern Bank keyed by concern ID, validated against the core schema."""
    concerns = [Concern.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))["concerns"]]
    bank = {concern.concern_id: concern for concern in concerns}
    if len(bank) != len(concerns):
        raise ValueError("Duplicate concern IDs in the Concern Bank")
    return bank


def load_priors(path: Path = DATA / "concerns" / "priors.json") -> dict[TriggerType, dict[str, float]]:
    """Return the starting worries for each trigger type."""
    raw = json.loads(path.read_text(encoding="utf-8"))["priors"]
    return {TriggerType(trigger): dict(entry["worries"]) for trigger, entry in raw.items()}


def load_personas(path: Path = DATA / "personas" / "personas.json", split: str | None = None) -> list[Persona]:
    """Return personas, optionally only the ``planning`` or ``evaluation`` split."""
    personas = [Persona.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))["personas"]]
    return [persona for persona in personas if split is None or persona.split == split]


def validate(concerns: dict[str, Concern], priors: dict[TriggerType, dict[str, float]],
             personas: list[Persona], node_ids: set[str]) -> list[str]:
    """Return every consistency problem across the bank, priors, personas and knowledge."""
    problems = []
    for concern in concerns.values():
        for condition in concern.resolve_conditions:
            for node in condition.knowledge_node_ids:
                if node not in node_ids:
                    problems.append(f"{concern.concern_id}: unknown knowledge node {node}")
        for language in ("hindi", "hinglish", "punjabi", "english"):
            if not concern.phrasings.get(language):
                problems.append(f"{concern.concern_id}: no {language} phrasings")
    for trigger in TriggerType:
        worries = priors.get(trigger)
        if worries is None:
            problems.append(f"{trigger.value}: no starting-worries prior")
            continue
        if abs(sum(worries.values()) - 1) > 1e-6:
            problems.append(f"{trigger.value}: prior does not sum to 1")
        problems.extend(f"{trigger.value}: unknown concern {c}" for c in worries if c not in concerns)
    seen = set()
    for persona in personas:
        if persona.persona_id in seen:
            problems.append(f"{persona.persona_id}: duplicate persona ID")
        seen.add(persona.persona_id)
        problems.extend(f"{persona.persona_id}: unknown concern {c}" for c in persona.hidden_concerns
                        if c not in concerns)
    return problems


class ConcernBank:
    """The validated Concern Bank with trigger priors smoothed over every concern."""

    def __init__(self, concerns: dict[str, Concern], priors: dict[TriggerType, dict[str, float]]):
        self.concerns = concerns
        self.priors = priors

    @property
    def ids(self) -> list[str]:
        """Concern IDs in a stable order."""
        return sorted(self.concerns)

    def prior_for(self, trigger: TriggerType, smoothing: float = 0.05) -> dict[str, float]:
        """Return a full distribution over every concern for ``trigger``.

        ``smoothing`` is the total mass spread evenly across all concerns, so a concern missing from
        the trigger's table can still rise when the merchant raises it.
        """
        if not 0 <= smoothing < 1:
            raise ValueError("smoothing must be in [0, 1)")
        base = self.priors[trigger]
        share = smoothing / len(self.concerns)
        return {cid: (1 - smoothing) * base.get(cid, 0.0) + share for cid in self.ids}

    def phrasings(self, concern_id: str) -> list[str]:
        """All example phrasings for a concern across languages."""
        return [text for texts in self.concerns[concern_id].phrasings.values() for text in texts]


@lru_cache(maxsize=1)
def default_bank() -> ConcernBank:
    """Load, validate and cache the repository's Concern Bank."""
    concerns, priors = load_concerns(), load_priors()
    problems = validate(concerns, priors, load_personas(), knowledge_node_ids())
    if problems:
        raise ValueError("Concern Bank is inconsistent: " + "; ".join(problems))
    return ConcernBank(concerns, priors)
