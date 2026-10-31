import json
import re
import unittest
from pathlib import Path

from agent.batch_pageindex import BatchPageIndex
from agent.documents import DocumentStore


class SalesCatalogTests(unittest.TestCase):
    def test_product_evidence_is_readable_through_inherited_batch_lookup(self):
        path = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "Paytm_Products.json"
        store = DocumentStore({"Paytm_Products": json.loads(path.read_text(encoding="utf-8"))})
        index = BatchPageIndex(store)
        sources = [target for target in store.targets.values() if target.kind == "source"]
        self.assertEqual(len(sources), 29)
        seen = set()
        evidence = []
        for start in range(0, len(sources), 6):  # the tool reads at most six sources per request
            evidence += index.read({"source_ids": [s.id for s in sources[start:start + 6]]}, seen, 32000).evidence
        self.assertEqual(len(evidence), 29)
        self.assertTrue(all(re.search(r"Source[^:.]*: https://", item["text"]) for item in evidence))
        self.assertTrue(all(re.search(r"Reviewed 2026-10-(26|31)\.", item["text"]) for item in evidence))
        self.assertTrue(any("without a website" in item["text"] for item in evidence))
        self.assertTrue(any("never ask" in item["text"] for item in evidence))
        self.assertFalse(any("—" in item["text"] for item in evidence), "spoken text never uses an em dash")

    def test_no_concern_answer_is_grounded_in_the_offers_section(self):
        """Calls never mention an offer, so no Concern Bank answer may cite the cashback section."""
        path = Path(__file__).resolve().parent.parent / "data" / "concerns" / "concerns.json"
        linked = {node for concern in json.loads(path.read_text(encoding="utf-8"))["concerns"]
                  for condition in concern["resolve_conditions"] for node in condition["knowledge_node_ids"]}
        self.assertNotIn("merchant_offers", linked)
