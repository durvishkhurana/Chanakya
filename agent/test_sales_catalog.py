import json
import re
import unittest
from pathlib import Path

from agent.batch_pageindex import BatchPageIndex
from agent.documents import DocumentStore


class SalesCatalogTests(unittest.TestCase):
    def test_product_evidence_is_readable_through_inherited_batch_lookup(self):
        path = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "Paytm_Products.json"
        store = DocumentStore({"Paytm_Products": json.loads(path.read_text())})
        index = BatchPageIndex(store)
        sources = [target for target in store.targets.values() if target.kind == "source"]
        self.assertEqual(len(sources), 15)
        seen = set()
        evidence = []
        for start in range(0, len(sources), 6):  # the tool reads at most six sources per request
            evidence += index.read({"source_ids": [s.id for s in sources[start:start + 6]]}, seen, 32000).evidence
        self.assertEqual(len(evidence), 15)
        self.assertTrue(all(re.search(r"Source[^:.]*: https://", item["text"]) for item in evidence))
        self.assertTrue(all(re.search(r"Reviewed 2026-10-(26|31)\.", item["text"]) for item in evidence))
        self.assertTrue(any("without a website" in item["text"] for item in evidence))
        self.assertTrue(any("never ask" in item["text"] for item in evidence))
        self.assertFalse(any("—" in item["text"] for item in evidence), "spoken text never uses an em dash")
