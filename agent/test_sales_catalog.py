import json
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
        self.assertEqual(len(sources), 6)
        seen = set()
        result = index.read({"source_ids": [source.id for source in sources]}, seen, 32000)
        self.assertEqual(len(result.evidence), 6)
        self.assertTrue(all("https://" in item["text"] for item in result.evidence))
        self.assertTrue(all("2026-10-26" in item["text"] for item in result.evidence))
        self.assertTrue(any("without a website" in item["text"] for item in result.evidence))
