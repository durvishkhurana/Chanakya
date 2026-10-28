"""Direct, validated multi-path reads from the local PageIndex corpus."""

import json
from copy import deepcopy
from dataclasses import dataclass

from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from .decision_tracing import _trace_inputs


class PageIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_ids: list[str] = Field(min_length=1, max_length=6)


PAGEINDEX_TOOL = {
    "type": "function",
    "function": {
        "name": "read_pageindex",
        "strict": True,
        "description": (
            "Read actual product source text before stating Paytm product facts. Select source IDs "
            "directly from any tree depth in ONE request. Put ALL selected sources in "
            "ONE source_ids list of at most six distinct IDs TOTAL, covering relevant "
            "conditions and exceptions. The server derives their document branches and "
            "reads at most three documents per batch; extra documents are reported as "
            "omitted. Prefer overview sources covering the whole question. Catalog titles and summaries are "
            "navigation hints, not factual evidence. Do not fetch already-read sources."
        ),
        "parameters": PageIndexRequest.model_json_schema(),
    },
}


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class BatchRead:
    evidence: list[dict]
    omitted: list[str]
    branch_ids: list[str]


class BatchPageIndex:
    def __init__(self, store, catalog_limit=96000):
        self.store = store
        self.ancestors = {}

        def visit(target_id, parents):
            target = store.targets[target_id]
            self.ancestors[target_id] = frozenset(parents)
            entry = {"id": target_id, "title": target.title.rsplit(" / ", 1)[-1]}
            if target.kind == "outline":
                if target.summary:
                    entry["summary"] = " ".join(target.summary.split())[:120]
                entry["children"] = [visit(child, (*parents, target_id)) for child in target.children]
            else:
                if target.page is not None:
                    entry["page"] = target.page
                # Original pages lack semantic titles, so a short hint aids selection.
                if target.title.startswith("Page "):
                    entry["hint"] = " ".join(target.summary.split())[:100]
            return entry

        catalog = [visit(root, ()) for root in store.roots]
        self.catalog = compact_json(catalog)
        self.catalog_bytes = len(self.catalog.encode("utf-8"))
        if self.catalog_bytes > catalog_limit:
            raise ValueError("PageIndex catalog exceeds the normal LLM catalog limit")
        self.source_ids = tuple(key for key, target in store.targets.items() if target.kind == "source")
        self.source_roots = {
            key: min(
                (ancestor for ancestor in self.ancestors[key] if store.targets[ancestor].document == store.targets[key].document),
                key=lambda ancestor: len(self.ancestors[ancestor]),
            ) for key in self.source_ids
        }

    def tool_for(self, seen):
        """Constrain model choices without sharing mutable schemas across turns."""
        tool = deepcopy(PAGEINDEX_TOOL)
        properties = tool["function"]["parameters"]["properties"]
        properties["source_ids"]["items"]["enum"] = [key for key in self.source_ids if key not in seen]
        return tool

    @traceable(name="read_pageindex", run_type="tool", process_inputs=_trace_inputs)
    def read(self, selection, seen, byte_budget):
        request = PageIndexRequest.model_validate(selection)
        ids = list(dict.fromkeys(request.source_ids))
        for source_id in ids:
            source = self.store.targets.get(source_id)
            if source is None or source.kind != "source" or source_id in seen:
                raise ValueError("PageIndex source must name actual unread source text")
        paths, omitted = {}, []
        for source_id in ids:
            branch_id = self.source_roots[source_id]
            if branch_id not in paths:
                if len(paths) == 3:
                    omitted.append(source_id)
                    continue
                paths[branch_id] = []
            paths[branch_id].append(source_id)
        # Give each selected branch a chance before taking a second source from one.
        ordered = [
            sources[index]
            for index in range(max(len(sources) for sources in paths.values()))
            for sources in paths.values() if index < len(sources)
        ]
        evidence = []
        for source_id in ordered:
            source = self.store.targets[source_id].evidence()
            if len(compact_json([*evidence, source]).encode("utf-8")) > byte_budget:
                omitted.append(source_id)
                continue
            evidence.append(source)
        return BatchRead(evidence, omitted, list(dict.fromkeys(self.source_roots[source["source_id"]] for source in evidence)))
