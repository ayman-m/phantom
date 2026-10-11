"""Reflector — the *reasoning* half of the self-improving Stop hook.

`propose_claude_md.py` (the hook) does the cheap, deterministic part: notice
that something changed. This file does the expensive part the article actually
describes:

    "A stop hook can reflect on what happened during a session and propose
     CLAUDE.md updates while the context is fresh."

It gathers the session's working-tree diff plus the current CLAUDE.md of every
area that changed, asks Claude (headless `claude -p`) to judge whether those
conventions still hold, and writes the proposal to `.claude/claude-md-review.md`.

Because it makes an LLM call (slow), the hook spawns this in the background.
It can also be run directly for a synchronous reflection — useful for tests
and `validate_all.py`:

    python3 .claude/hooks/reflect_claude_md.py

Two safety properties:
  * Recursion guard — the headless `claude` it spawns would fire its own Stop
    hook, which would spawn another reflection, forever. The `claude` child is
    launched with PHANTOM_AILAYER_REFLECT_LOCK=1; both this file and the hook
    no-op when that variable is set.
  * Graceful fallback — if the `claude` CLI is missing or the call fails, it
    writes a deterministic "re-check these files" note instead, so the AI Layer
    still flags drift without the model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    ".next", "out", "reports",
    "bundles/spark/connectors/cortex-content/baked",
})
_REVIEW_FILE = ".claude/claude-md-review.md"
_LOCK_ENV = "PHANTOM_AILAYER_REFLECT_LOCK"
_MAX_DIFF_CHARS = 12_000
_CLAUDE_TIMEOUT = 180


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


def _git(args: list[str], root: Path, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def _changed_paths(root: Path) -> list[str]:
    return [
        line[3:].strip().replace("\\", "/")
        for line in _git(["status", "--porcelain"], root).splitlines()
        if len(line) > 3
    ]


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


def _touched_areas(root: Path) -> dict[str, int]:
    """Map each touched CLAUDE.md-governed area to a count of files changed."""
    governed = _claude_md_areas(root)
    counts: dict[str, int] = {}
    for path in _changed_paths(root):
        area = _area_of(path, governed)
        if area is not None:
            counts[area] = counts.get(area, 0) + 1
    return counts


def _build_prompt(root: Path, areas: dict[str, int], diff: str) -> str:
    blocks: list[str] = []
    for area in sorted(areas):
        claude_md = root / area / "CLAUDE.md"
        content = (
            claude_md.read_text(encoding="utf-8")
            if claude_md.is_file()
            else "(this area has no CLAUDE.md yet)"
        )
        blocks.append(f"### {area}/CLAUDE.md\n\n{content}")
    current = "\n\n".join(blocks)

    return f"""You are auditing whether a codebase's CLAUDE.md files still match \
reality after a coding session. CLAUDE.md is the instruction file an AI coding \
agent loads for that part of the repo.

Below is the git diff of the session's uncommitted changes, then the current \
CLAUDE.md for every area that changed.

For EACH area, output exactly one of:
- `No change needed` — the CLAUDE.md still holds; or
- a concrete proposed edit: the specific line(s) to add, change, or remove, \
plus one sentence on why.

Only propose an update when the diff introduces a genuine new convention, \
gotcha, command, or constraint that the CLAUDE.md does not yet capture. Do not \
propose stylistic rewrites. Be terse. Respond in plain text; do not use tools.

## Git diff (uncommitted work this session)

```diff
{diff}
```

## Current CLAUDE.md file(s)

{current}
"""


def _run_claude(prompt: str, root: Path) -> str | None:
    claude = shutil.which("claude")
    if not claude:
        return None

    env = dict(os.environ)
    env[_LOCK_ENV] = "1"  # recursion guard for the nested claude's own Stop hook

    try:
        result = subprocess.run(
            [claude, "-p", "--output-format", "text"],
            cwd=root,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CLAUDE_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _deterministic_note(root: Path, areas: dict[str, int], stamp: str) -> str:
    lines = [
        f"# CLAUDE.md review — {stamp}",
        "",
        "_`claude` CLI unavailable — deterministic fallback. The areas below "
        "changed this session; re-check their CLAUDE.md by hand._",
        "",
    ]
    for area, count in sorted(areas.items()):
        claude_md = root / area / "CLAUDE.md"
        if claude_md.is_file():
            lines.append(
                f"- **{area}** ({count} file(s)) — re-read `{area}/CLAUDE.md`: "
                f"do its conventions still hold?"
            )
        else:
            lines.append(
                f"- **{area}** ({count} file(s)) — no `{area}/CLAUDE.md` exists; "
                f"consider adding one."
            )
    return "\n".join(lines) + "\n"


def reflect() -> int:
    _force_utf8()

    if os.environ.get(_LOCK_ENV):
        return 0

    root = _project_root()
    areas = _touched_areas(root)
    if not areas:
        return 0

    diff = _git(["diff", "HEAD", "--", *sorted(areas)], root)
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n... (diff truncated for the reflection)"

    stamp = datetime.now().isoformat(timespec="seconds")
    reflection = (
        _run_claude(_build_prompt(root, areas, diff), root) if diff.strip() else None
    )

    if reflection:
        body = (
            f"# CLAUDE.md review — {stamp}\n\n"
            f"_Reflection by `claude -p` over {len(areas)} touched area(s): "
            f"{', '.join(sorted(areas))}._\n\n"
            f"{reflection}\n"
        )
    else:
        body = _deterministic_note(root, areas, stamp)

    review = root / _REVIEW_FILE
    try:
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(body, encoding="utf-8")
    except OSError as exc:
        print(f"[reflector] could not write {_REVIEW_FILE}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(reflect())
