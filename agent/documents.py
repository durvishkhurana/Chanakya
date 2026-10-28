"""Read PageIndex exports without model calls or LangChain tool wrappers."""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"


def text_parts(text: str, max_bytes: int = 6000) -> list[str]:
    """Keep every character, preferring line boundaries within each UTF-8 budget."""
    parts, current, size = [], [], 0
    for line in text.splitlines(keepends=True):
        width = len(line.encode("utf-8"))
        if current and size + width > max_bytes:
            parts.append("".join(current))
            current, size = [], 0
        if width <= max_bytes:
            current.append(line)
            size += width
            continue
        # A single oversized line still needs a hard bound, without losing characters.
        for char in line:
            width = len(char.encode("utf-8"))
            if current and size + width > max_bytes:
                parts.append("".join(current))
                current, size = [], 0
            current.append(char)
            size += width
    if current:
        parts.append("".join(current))
    return parts


@dataclass(frozen=True)
class Target:
    id: str
    kind: str
    document: str
    title: str
    summary: str = ""
    page: int | None = None
    node_id: str | None = None
    text: str = ""
    children: tuple[str, ...] = ()

    def description(self) -> dict:
        return {
            "kind": self.kind,
            "document": self.document,
            "title": self.title,
            "summary": self.summary,
            "page": self.page,
            "node_id": self.node_id,
        }

    def evidence(self) -> dict:
        if self.kind != "source" or not self.text.strip():
            raise ValueError("Navigation targets are not source evidence")
        return {"source_id": self.id, **self.description(), "text": self.text}


class DocumentStore:
    """Stable opaque target IDs keep Jev's option keys short and unambiguous."""

    def __init__(self, documents: dict):
        self.documents = documents
        self.targets: dict[str, Target] = {}
        self.roots: list[str] = []
        for name, data in sorted(documents.items()):

            def add_text(
                title,
                text,
                summary="",
                page=None,
                node_id=None,
                document=name,
            ):
                parts = text_parts(text)
                sources = []
                for index, part in enumerate(parts, 1):
                    label = (
                        f"{title} (part {index}/{len(parts)})"
                        if len(parts) > 1
                        else title
                    )
                    sources.append(
                        self._add(
                            kind="source",
                            document=document,
                            title=label,
                            summary=summary[:400],
                            page=page,
                            node_id=node_id,
                            text=part,
                        )
                    )
                if len(sources) > 1:
                    return [
                        self._outline(
                            sources,
                            document,
                            title,
                            "Read the text parts in order, including table headings and policy conditions.",
                        )
                    ]
                return sources

            def visit(nodes, ancestors=()):
                sections = []
                for node in nodes:
                    title = (*ancestors, node.get("title", "Untitled section"))
                    label = " / ".join(title)
                    text = node.get("text") or ""
                    contents = []
                    if text.strip():
                        contents.extend(
                            add_text(
                                label,
                                text,
                                node.get("prefix_summary") or node.get("summary") or "",
                                node.get("page_index", node.get("start_index")),
                                node.get("node_id"),
                            )
                        )
                    children = node.get("nodes", [])
                    contents.extend(visit(children, title))
                    if children and contents:
                        sections.append(
                            self._outline(
                                contents,
                                name,  # noqa: B023 - visit() runs within this loop iteration.
                                label,
                                node.get("prefix_summary") or node.get("summary") or "",
                            )
                        )
                    else:
                        sections.extend(contents)
                return sections

            sections = visit(data.get("tree", {}).get("result", []))
            # Offer original pages too: a node's text can omit a table or have gaps.
            pages = []
            for page in data.get("pages", {}).get("result", []):
                text = page.get("markdown") or ""
                if text.strip():
                    number = page.get("page_index")
                    pages.extend(add_text(f"Page {number}", text, text[:200], page=number))
            if pages:
                sections.append(
                    self._outline(
                        pages,
                        name,
                        "Original pages",
                        "Read original page text to check tables, footnotes, or gaps in section text.",
                    )
                )
            metadata = data.get("metadata", {})
            self.roots.append(
                self._outline(
                    sections,
                    name,
                    metadata.get("name") or name,
                    metadata.get("description") or "",
                )
            )
        # Also bound the initial menu when the corpus grows beyond one Choice.
        while len(self.roots) > 120:
            roots = self.roots
            self.roots = [
                self._add(
                    kind="outline",
                    document="",
                    title=f"Documents {offset + 1}-{min(offset + 120, len(roots))}",
                    children=tuple(roots[offset : offset + 120]),
                )
                for offset in range(0, len(roots), 120)
            ]

    def _outline(self, children, document, title, summary=""):
        # Respect semantic sections first; only group wide sibling lists.
        while len(children) > 12:
            grouped = []
            for offset in range(0, len(children), 12):
                group = children[offset : offset + 12]
                labels = [self.targets[key].title for key in group]
                grouped.append(
                    self._add(
                        kind="outline",
                        document=document,
                        title=f"{labels[0]} ... {labels[-1]}",
                        summary="Sections: " + "; ".join(labels)[:400],
                        children=tuple(group),
                    )
                )
            children = grouped
        return self._add(
            kind="outline",
            document=document,
            title=title,
            summary=summary[:400],
            children=tuple(children),
        )

    def _add(self, **fields) -> str:
        target_id = f"t{len(self.targets):05d}"
        self.targets[target_id] = Target(id=target_id, **fields)
        return target_id

    @classmethod
    def load(cls, directory: Path = DATA_DIR):
        documents = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        }
        return cls(documents)
