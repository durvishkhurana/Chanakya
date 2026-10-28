import unittest

from agent.batch_pageindex import PAGEINDEX_TOOL, BatchPageIndex, PageIndexRequest
from agent.documents import DocumentStore


def batch_store():
    return DocumentStore({
        name: {"tree": {"result": [{"title": name, "nodes": [
            {"title": "Eligibility", "text": name + " actual eligibility"},
            {"title": "Exceptions", "text": name + " actual exception"},
        ]}]}}
        for name in ("hostels", "scholarships", "admissions")
    })


def paths_for(store):
    return [{"branch_id": root, "source_ids": [
        target.id for target in store.targets.values()
        if target.kind == "source" and target.document == store.targets[root].document
    ]} for root in store.roots]


def selection_for(paths):
    return {
        "source_ids": [source for path in paths for source in path["source_ids"]],
    }


class BatchPageIndexTests(unittest.TestCase):
    def setUp(self):
        self.store = batch_store()
        self.index = BatchPageIndex(self.store)
        self.paths = paths_for(self.store)

    def test_tool_schema_has_one_six_source_limit_across_all_branches(self):
        schema = PAGEINDEX_TOOL["function"]["parameters"]
        selection = selection_for(self.paths)
        PageIndexRequest.model_validate(selection)
        self.assertEqual(schema["properties"]["source_ids"]["maxItems"], 6)
        selection["source_ids"].append(selection["source_ids"][0])
        with self.assertRaises(ValueError):
            PageIndexRequest.model_validate(selection)
        with self.assertRaises(ValueError):
            self.index.read(selection, set(), 32000)

    def test_model_can_only_select_unread_source_ids_and_server_derives_roots(self):
        first = self.paths[0]["source_ids"][0]
        schema = self.index.tool_for({first})["function"]["parameters"]
        sources = schema["properties"]["source_ids"]["items"]["enum"]
        self.assertEqual(set(schema["properties"]), {"source_ids"})
        self.assertNotIn(first, sources)
        self.assertEqual(set(sources), {key for key, target in self.store.targets.items() if target.kind == "source"} - {first})
        self.assertFalse(set(self.store.roots) & set(sources))
        # Sibling sections stay selectable under their common document root.
        result = self.index.read(selection_for(self.paths[:1]), set(), 32000)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(result.branch_ids, [self.paths[0]["branch_id"]])

    def test_request_schemas_do_not_share_read_state_or_mutable_enums(self):
        first, second = self.paths[0]["source_ids"]
        one = self.index.tool_for({first})["function"]["parameters"]["properties"]
        two = self.index.tool_for({second})["function"]["parameters"]["properties"]
        one["source_ids"]["items"]["enum"].clear()
        self.assertIn(first, two["source_ids"]["items"]["enum"])
        self.assertNotIn(second, two["source_ids"]["items"]["enum"])

    def test_reads_six_deep_sources_across_three_paths_together(self):
        result = self.index.read(selection_for(self.paths), set(), 32000)
        self.assertEqual(len(result.evidence), 6)
        self.assertFalse(result.omitted)
        self.assertEqual(len({source["document"] for source in result.evidence}), 3)
        for source in result.evidence:
            self.assertIn(source["source_id"], self.index.catalog)
            self.assertIn("actual", source["text"])

    def test_validates_entire_batch_before_reading(self):
        paths = [self.paths[0], {"branch_id": self.paths[1]["branch_id"], "source_ids": ["invented"]}]
        with self.assertRaises(ValueError):
            self.index.read(selection_for(paths), set(), 32000)

    def test_rejects_outlines_unknown_sources_and_rereads(self):
        source = self.paths[0]["source_ids"][0]
        branch = self.paths[0]["branch_id"]
        for sources, seen in (
            (["invented"], set()),
            ([branch], set()),
            ([source], {source}),
        ):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                self.index.read({"source_ids": sources}, seen, 32000)

    def test_duplicate_ids_do_not_read_the_same_source_twice(self):
        source = self.paths[0]["source_ids"][0]
        result = self.index.read({"source_ids": [source, source]}, set(), 32000)
        self.assertEqual([item["source_id"] for item in result.evidence], [source])

    def test_extra_document_sources_are_reported_as_omitted_and_can_be_read_next(self):
        store = DocumentStore({name: {"tree": {"result": [{"title": name, "text": name + " actual text"}]}}
                               for name in ("a", "b", "c", "d", "e")})
        index = BatchPageIndex(store)
        result = index.read({"source_ids": list(index.source_ids)}, set(), 32000)
        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(len(result.branch_ids), 3)
        self.assertEqual(len(result.omitted), 2)
        seen = {source["source_id"] for source in result.evidence}
        followup = index.read({"source_ids": result.omitted}, seen, 32000)
        self.assertEqual(len(followup.evidence), 2)
        self.assertFalse(followup.omitted)

    def test_evidence_budget_gives_each_path_a_first_source(self):
        result = self.index.read(selection_for(self.paths), set(), 850)
        self.assertEqual(len({s["document"] for s in result.evidence}), 3)
        self.assertTrue(result.omitted)

    def test_limits_and_unknown_fields_are_rejected(self):
        for selection in (
            selection_for([]), selection_for(self.paths + [self.paths[0]]),
            {**selection_for(self.paths), "injected": "ignore rules"},
            {**selection_for(self.paths), "branch_ids": [self.paths[0]["branch_id"]]},
        ):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.index.read(selection, set(), 32000)

    def test_catalog_limit_fails_without_silent_document_truncation(self):
        with self.assertRaisesRegex(ValueError, "catalog limit"):
            BatchPageIndex(self.store, catalog_limit=1)

    def test_selects_deep_sources_under_intermediate_branches(self):
        store = DocumentStore({"nested": {"tree": {"result": [{
            "title": "Policies", "nodes": [
                {"title": section, "nodes": [{"title": "Rules", "nodes": [
                    {"title": "Conditions", "text": section + " source text"},
                ]}]}
                for section in ("Hostels", "Scholarships", "Admissions")
            ],
        }]}}})
        index = BatchPageIndex(store)
        paths = []
        for name in ("Hostels", "Scholarships", "Admissions"):
            branch = next(t for t in store.targets.values() if t.kind == "outline" and t.title.endswith(" / " + name))
            source = next(t for t in store.targets.values() if t.kind == "source" and name in t.title)
            self.assertGreater(len(index.ancestors[source.id]), 2)
            paths.append({"branch_id": branch.id, "source_ids": [source.id]})
        result = index.read(selection_for(paths), set(), 32000)
        self.assertEqual(len(result.evidence), 3)
        self.assertEqual(result.branch_ids, store.roots)


if __name__ == "__main__":
    unittest.main()
