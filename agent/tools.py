import json
from pathlib import Path

from langchain_core.tools import tool

# ──────────────────────────────────────────────
#  Load local PageIndex data (downloaded by cloud_index.py)
# ──────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "knowledge"

# Load all document data into memory
_DOCS = {}
if DATA_DIR.exists():
    for json_file in sorted(DATA_DIR.glob("*.json")):
        name = json_file.stem  # e.g. "Brief_Intro"
        with open(json_file, "r", encoding="utf-8") as f:
            _DOCS[name] = json.load(f)


def _get_tree_nodes(tree_data):
    """Recursively flatten tree nodes for display."""
    nodes = []
    for node in tree_data:
        entry = {
            "title": node.get("title", ""),
            "node_id": node.get("node_id", ""),
            "page_index": node.get("page_index", 0),
        }
        if node.get("summary"):
            entry["summary"] = node["summary"][:200]
        if node.get("prefix_summary"):
            entry["summary"] = node["prefix_summary"][:200]
        nodes.append(entry)
        # Recurse into child nodes
        if "nodes" in node:
            nodes.extend(_get_tree_nodes(node["nodes"]))
    return nodes


# ──────────────────────────────────────────────
#  Agent Tools - Local PageIndex Data
# ──────────────────────────────────────────────

@tool
def list_documents() -> str:
    """List all available product documents with their names and descriptions.
    Call this first to see which documents are available for querying.

    Returns:
        JSON list of documents with name, description, and page count.
    """
    docs = []
    for name, data in _DOCS.items():
        meta = data.get("metadata", {})
        docs.append({
            "name": name,
            "doc_name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "page_count": meta.get("pageNum", 0),
        })
    return json.dumps(docs, indent=2)


@tool
def get_document_structure(doc_name: str) -> str:
    """Get the hierarchical tree structure of a document to identify relevant sections.
    Use this to find which sections and pages contain information relevant to the query.
    Look at section titles, summaries, and page_index values.

    Args:
        doc_name: The document name from list_documents() (e.g. 'Brief_Intro', 'Fees_Hostel_Details').

    Returns:
        JSON tree structure with section titles, summaries, and page indices.
    """
    if doc_name not in _DOCS:
        return json.dumps({"error": f"Document '{doc_name}' not found. Use list_documents() first."})

    tree = _DOCS[doc_name].get("tree", {})
    result = tree.get("result", [])
    nodes = _get_tree_nodes(result)
    return json.dumps(nodes, indent=2)


@tool
def get_page_content(doc_name: str, page_index: int) -> str:
    """Get the text content of a specific page from a document.
    Use the page_index values from get_document_structure() to know which page to fetch.

    Args:
        doc_name: The document name (e.g. 'Brief_Intro', 'Fees_Hostel_Details').
        page_index: The page number to fetch (1-indexed, from the tree structure).

    Returns:
        The markdown text content of the page.
    """
    if doc_name not in _DOCS:
        return json.dumps({"error": f"Document '{doc_name}' not found. Use list_documents() first."})

    pages = _DOCS[doc_name].get("pages", {}).get("result", [])
    for page in pages:
        if page.get("page_index") == page_index:
            return page.get("markdown", "")

    return json.dumps({"error": f"Page {page_index} not found in '{doc_name}'."})


@tool
def get_node_text(doc_name: str, node_id: str) -> str:
    """Get the full text content of a specific section node from the document tree.
    Use after get_document_structure() to read a section's complete text.

    Args:
        doc_name: The document name (e.g. 'Brief_Intro', 'Fees_Hostel_Details').
        node_id: The node_id from get_document_structure() (e.g. '0001', '0003').

    Returns:
        The full text content of the section.
    """
    if doc_name not in _DOCS:
        return json.dumps({"error": f"Document '{doc_name}' not found."})

    def find_node(nodes, target_id):
        for node in nodes:
            if node.get("node_id") == target_id:
                return node.get("text", node.get("summary", ""))
            if "nodes" in node:
                result = find_node(node["nodes"], target_id)
                if result:
                    return result
        return None

    tree = _DOCS[doc_name].get("tree", {})
    result = tree.get("result", [])
    text = find_node(result, node_id)

    if text:
        return text
    return json.dumps({"error": f"Node '{node_id}' not found in '{doc_name}'."})


# All tools as a flat list for the agent
all_tools = [
    get_document_structure,
    get_page_content,
    get_node_text,
]
