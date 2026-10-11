"""XQL response enrichment helpers — markdown-only, no vector store.

There is no vector store here. Semantic search belongs to the runtime's
`SqliteKnowledgeBase` (spec §6.10 standalone impl) — see
`bundles/spark/mcp/src/usecase/kb_store.py` and the `xql-examples` KB
declared in `manifest.yaml:knowledge.bundled[]`. This module provides the
*enrichment* layered on top of raw matches:

  - **stage_docs**: for every pipeline stage referenced in a match
    (`| filter`, `| comp`, `| alter`, ...), extract the relevant snippet
    from the bundled XQL reference (`xql_doc.md`). Helps the agent
    understand the syntax of the stages it just retrieved.
  - **dataset_fields**: for every dataset name referenced in a match
    (`dataset = panw_ngfw_traffic_raw`), look up its known field list
    from `dataset_fields.md`. Helps the agent reason about what columns
    it can `| filter` on.

Both are pure markdown parsing — no embeddings, no network. Caches at
module level so repeated queries don't re-read the files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Module-level caches. Re-population is keyed on resources_dir so a test
# that swaps roots gets a fresh read.
_xql_doc_cache: dict[Path, str] = {}
_dataset_fields_cache: dict[Path, dict[str, list[str]]] = {}


_STAGE_RE = re.compile(r"\|\s*([a-zA-Z_][\w]*)")
_DATASET_RE = re.compile(r"\bdataset\s*=\s*([A-Za-z0-9_]+)")
_DATAMODEL_RE = re.compile(r"\bdatamodel\s+dataset\s*=\s*([A-Za-z0-9_]+)")


def extract_stage_names(query: str) -> set[str]:
    return {m.group(1).lower() for m in _STAGE_RE.finditer(query)}


def extract_dataset(query: str) -> str | None:
    m = _DATASET_RE.search(query) or _DATAMODEL_RE.search(query)
    return m.group(1) if m else None


def _load_xql_doc(resources_dir: Path) -> str:
    cached = _xql_doc_cache.get(resources_dir)
    if cached is not None:
        return cached
    path = resources_dir / "xql_doc.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    _xql_doc_cache[resources_dir] = text
    return text


def _load_dataset_fields(resources_dir: Path) -> dict[str, list[str]]:
    cached = _dataset_fields_cache.get(resources_dir)
    if cached is not None:
        return cached
    mapping: dict[str, list[str]] = {}
    path = resources_dir / "dataset_fields.md"
    if path.is_file():
        current: str | None = None
        fields: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if current:
                    mapping[current] = fields
                current = line.removeprefix("## ").strip()
                fields = []
                continue
            if line.startswith("- "):
                fields.append(line.removeprefix("- ").strip())
        if current:
            mapping[current] = fields
    _dataset_fields_cache[resources_dir] = mapping
    return mapping


def _extract_doc_snippet(doc_text: str, stage_name: str, window: int = 360) -> str | None:
    if not doc_text:
        return None
    pattern = re.compile(
        rf"(.{{0,{window}}}\b{re.escape(stage_name)}\b.{{0,{window}}})",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(doc_text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def collect_stage_docs(resources_dir: Path, stage_names: list[str]) -> list[dict[str, str]]:
    if not stage_names:
        return []
    doc_text = _load_xql_doc(resources_dir)
    out: list[dict[str, str]] = []
    for name in stage_names:
        snippet = _extract_doc_snippet(doc_text, name)
        if snippet:
            out.append({"stage": name, "snippet": snippet})
    return out


def collect_dataset_fields(
    resources_dir: Path, datasets: list[str]
) -> list[dict[str, Any]]:
    if not datasets:
        return []
    mapping = _load_dataset_fields(resources_dir)
    out: list[dict[str, Any]] = []
    for ds in datasets:
        fields = mapping.get(ds)
        if fields:
            out.append({"dataset": ds, "fields": fields})
    return out
