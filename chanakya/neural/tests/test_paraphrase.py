"""The labelled-line generator keeps test lines apart from training lines and from the Concern Bank."""

import asyncio
import json
import random
from types import SimpleNamespace

from chanakya.brain.concern_bank import default_bank
from chanakya.neural.paraphrase import LANGUAGES, NONE, SPLITS, clean, generate, load, prompt


class FakeLLM:
    """Returns two lines per request, one of them shared by every request; no network."""

    def __init__(self):
        self.settings = SimpleNamespace(models={"twin_a": "model-a", "twin_b": "model-b"})
        self.calls = 0

    async def complete(self, role, messages, **kwargs):
        self.calls += 1
        return json.dumps({"lines": [f"line {self.calls} from {role}", "the same line every time"]})


def test_every_split_concern_and_language_is_requested_once_with_the_right_model():
    bank, llm = default_bank(), FakeLLM()
    rows = asyncio.run(generate(llm, seed=3, bank=bank))
    assert llm.calls == len(SPLITS) * (len(bank.ids) + 1) * len(LANGUAGES)
    assert {r["model"] for r in rows if r["split"] == "train"} == {"model-a"}
    assert {r["model"] for r in rows if r["split"] == "test"} == {"model-b"}
    assert {r["concern"] for r in rows} == {*bank.ids, NONE}
    assert sum(r["text"] == "the same line every time" for r in rows) == 1, "duplicates are dropped"


def test_bank_phrasings_and_test_lines_close_to_train_lines_are_dropped():
    bank = default_bank()
    phrasing = bank.phrasings("hidden_charges")[0]
    rows = [
        {"text": phrasing, "split": "train"},
        {"text": "Mera bhai bhi yahi machine use karta hai", "split": "train"},
        {"text": "Mera bhai bhi yahi machine use karta hai!", "split": "test"},
        {"text": "Settlement kitne din mein aata hai account mein?", "split": "test"},
    ]
    assert [r["text"] for r in clean(rows, bank)] == ["Mera bhai bhi yahi machine use karta hai",
                                                     "Settlement kitne din mein aata hai account mein?"]


def test_prompts_are_seeded_and_never_ask_for_prices(tmp_path):
    first = prompt("is worried about rent", "hinglish", 5, random.Random(1))
    assert first == prompt("is worried about rent", "hinglish", 5, random.Random(1))
    assert "No prices" in first and "Latin script" in first
    path = tmp_path / "lines.jsonl"
    path.write_text('{"text": "a", "split": "train"}\n{"text": "b", "split": "test"}\n', encoding="utf-8")
    assert [r["text"] for r in load("test", path)] == ["b"]
