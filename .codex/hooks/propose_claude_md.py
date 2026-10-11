"""Stop hook — the *trigger* half of the self-improving AI Layer.

The article: "a stop hook can reflect on what happened during a session and
propose CLAUDE.md updates while the context is fresh." That reflection is an
LLM call — too slow to block the end of every turn on. So the work is split:

  * This file (the hook) does the cheap, deterministic part — notice which
    CLAUDE.md-governed areas changed, and decide whether a reflection is worth
    it. "Area" = any directory with its own CLAUDE.md, so the hook follows the
    article's CLAUDE.md hierarchy and is not tied to any specific layout.
  * `reflect_claude_md.py` (the reflector) does the LLM call that actually
    reflects and proposes concrete CLAUDE.md edits.

When something changed, this hook spawns the reflector in the **background**
and returns immediately; the reflector writes `.claude/claude-md-review.md` a
little after the turn ends.

Three guards keep it well-behaved:
  * Recursion guard — the reflector spawns a headless `claude` whose own Stop
    hook lands right back here; PHANTOM_AILAYER_REFLECT_LOCK makes that no-op.
  * Dedup — the Stop hook fires every turn, but the diff usually has not
    changed turn to turn; a fingerprint of `git diff HEAD` skips re-reflecting
    on a diff already handled.
  * Fallback — if `claude` is missing the reflector still runs and writes a
    deterministic note, so drift is flagged either way.

Tested standalone: `python3 .claude/hooks/propose_claude_md.py`
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    ".next", "out", "reports",
    "bundles/spark/connectors/cortex-content/baked",
})
_LOCK_ENV = "PHANTOM_AILAYER_REFLECT_LOCK"
_STATE_FILE = ".claude/.claude-md-review-state"
_REFLECTOR = "reflect_claude_md.py"

# Windows: detach the background reflector so it outlives this hook process.
_DETACHED_PROCESS = 0x00000008


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _project_root() -> Path:
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(project) if project else Path(__file__).resolve().parents[2]


def _git(args: list[str], root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def _claude_md_areas(root: Path) -> set[str]:
    areas: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        if "CLAUDE.md" in filenames:
            rel = Path(dirpath).relative_to(root).as_posix()
            if rel != ".":
                areas.add(rel)
    return areas


def _area_of(changed: str, areas: set[str]) -> str | None:
    parts = changed.split("/")
    for depth in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:depth])
        if candidate in areas:
            return candidate
    return None


def _touched_areas(root: Path) -> set[str]:
    governed = _claude_md_areas(root)
    touched: set[str] = set()
    for line in _git(["status", "--porcelain"], root).splitlines():
        if len(line) <= 3:
            continue
        path = line[3:].strip().replace("\\", "/")
        area = _area_of(path, governed)
        if area is not None:
            touched.add(area)
    return touched


def _diff_fingerprint(root: Path, areas: set[str]) -> str:
    raw = _git(["diff", "HEAD", "--", *sorted(areas)], root)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _spawn_reflector(reflector: Path, root: Path) -> bool:
    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS
    else:
        start_new_session = True
    try:
        subprocess.Popen(
            [sys.executable, str(reflector)],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[phantom-ai-layer hook] could not start reflector: {exc}", file=sys.stderr)
        return False
    return True


def main() -> int:
    _force_utf8()

    try:
        sys.stdin.read()
    except (OSError, ValueError):
        pass

    # Guard 1 — recursion. A reflection spawns a headless `claude` whose own
    # Stop hook runs this file again. If the lock is set, do nothing.
    if os.environ.get(_LOCK_ENV):
        return 0

    root = _project_root()
    areas = _touched_areas(root)
    if not areas:
        return 0

    # Guard 2 — dedup. The Stop hook fires every turn; only reflect when the
    # diff itself is new since the last reflection.
    fingerprint = _diff_fingerprint(root, areas)
    state = root / _STATE_FILE
    try:
        if state.read_text(encoding="utf-8").strip() == fingerprint:
            return 0
    except OSError:
        pass

    reflector = Path(__file__).with_name(_REFLECTOR)
    if not reflector.is_file():
        print(f"[phantom-ai-layer hook] {_REFLECTOR} missing — skipped", file=sys.stderr)
        return 0

    if not _spawn_reflector(reflector, root):
        return 0

    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass

    print(
        f"[phantom-ai-layer hook] {len(areas)} area(s) changed "
        f"({', '.join(sorted(areas))}) — reflecting in the background "
        f"→ .claude/claude-md-review.md",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
