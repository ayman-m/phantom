"""Local-filesystem client for the cortex-content catalog.

Reads everything from the catalog directory shipped with the agent
image. Layout:

    bundles/spark/connectors/cortex-content/baked/
    ├── _manifest.json                   ← catalog metadata + counts
    ├── catalog.json                     ← pre-built rollup (Browse view)
    └── Packs/
        └── <pack_name>/
            ├── pack_metadata.json
            ├── Author_image.png         ← if present
            ├── Integrations/<int>/<int>_dark.svg  ← if present
            └── ModelingRules/<rule>/<rule>_schema.json

Three public methods (`list_dir` / `get_file` / `get_file_json`) mirror
what every consumer of this connector expects:

  - Missing path → raise GitHubNotFoundError (kept as the exception
    class name for legacy reasons; signals "not found" — the operator
    never sees the class name, just the message)
  - Malformed JSON → propagate JSONDecodeError up
  - Other I/O errors → propagate up
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ._github_client import GitHubNotFoundError

logger = logging.getLogger("Phantom MCP.cortex-content")


class BakedClient:
    """Filesystem-backed cortex-content client.

    Reads from `<baked_root>/<path>` for every call. The expected
    layout matches the structure documented at the top of this module.
    """

    def __init__(self, baked_root: Path | str) -> None:
        self._root = Path(baked_root).resolve()
        # Placeholder attributes — kept for compatibility with the logo URL
        # constructor (which rewrites to the local serving route regardless
        # of these values).
        self.owner = "local"
        self.repo = "cortex-content"
        self.branch = "local"

    # ── Public API (mirrors GitHubClient) ────────────────────────

    def list_dir(self, path: str) -> list[dict[str, Any]]:
        """List immediate children of `<baked_root>/<path>`.

        Returns the same `[{name, type}]` shape GitHub's contents API
        returns, with `type` ∈ {"dir", "file"}. Raises GitHubNotFoundError
        when the path doesn't exist OR isn't a directory."""
        target = self._safe_join(path)
        if not target.is_dir():
            raise GitHubNotFoundError(f"baked: directory not found: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir()):
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                }
            )
        return entries

    def get_file(self, path: str) -> str:
        """Return the file content as text. Raises GitHubNotFoundError
        if the path doesn't exist or isn't a file."""
        target = self._safe_join(path)
        if not target.is_file():
            raise GitHubNotFoundError(f"baked: file not found: {path}")
        try:
            return target.read_text()
        except UnicodeDecodeError:
            # Binary file (logo PNGs etc.) — surface a structured error.
            # Callers don't read logo bytes via this method;
            # logos are served via the agent-side /logo/<pack> route.
            raise GitHubNotFoundError(
                f"baked: file is binary, not readable as text: {path}"
            )

    def get_file_json(self, path: str) -> Any:
        """Return the file content parsed as JSON. Raises
        GitHubNotFoundError if the path doesn't exist; passes through
        json.JSONDecodeError if parsing fails."""
        target = self._safe_join(path)
        if not target.is_file():
            raise GitHubNotFoundError(f"baked: file not found: {path}")
        return json.loads(target.read_text())

    # ── Internals ────────────────────────────────────────────────

    def _safe_join(self, path: str) -> Path:
        """Resolve `<root>/<path>` defensively — refuse paths that
        escape the baked root via `..` segments."""
        if not path or path.startswith("/"):
            raise GitHubNotFoundError(f"baked: path must be relative: {path!r}")
        candidate = (self._root / path).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise GitHubNotFoundError(
                f"baked: path escapes root: {path!r}"
            ) from None
        return candidate


def baked_root_path() -> Path:
    """Canonical location of the baked catalog directory.

    Checks two layout candidates so the connector works in both the
    repo (dev / tests / pre-commit) and the agent container (production).
    """
    candidates = [
        # Container: /app/bundle/connectors/cortex-content/src/_baked_client.py
        # baked dir sibling-of-src: /app/bundle/connectors/cortex-content/baked/
        Path(__file__).resolve().parent.parent / "baked",
        # Source tree: bundles/spark/connectors/cortex-content/baked/
        Path(__file__).resolve().parent.parent / "baked",
    ]
    for c in candidates:
        if c.is_dir() and (c / "_manifest.json").is_file():
            return c
    return candidates[0]  # default — caller checks .is_dir() before using


def is_baked_available() -> bool:
    """True if a baked catalog is present + appears complete (has the
    _manifest.json sentinel). Used by `_get_client()` in connector.py
    to decide whether to wire up BakedClient or fall back to GitHubClient."""
    root = baked_root_path()
    return root.is_dir() and (root / "_manifest.json").is_file()
