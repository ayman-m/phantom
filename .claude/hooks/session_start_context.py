"""SessionStart hook — dynamic per-module orientation for Phantom.

Prints a short orientation block at the start of every Claude Code session.
Claude Code injects this stdout into the session context, so Claude starts
already knowing which part of the codebase has active work — and the recent
direction of travel from git history — without spending a turn re-exploring.

Phantom-specific additions over the helpline reference:
  * In-flight GitHub issues with a `status:in-progress` label (optional: shown
    only if the repo uses that label and `gh` is authenticated).
  * Branch + divergence-from-main reminder (the dev cycle pushes to main; off-
    main work is unusual + worth flagging).

Tested standalone: `python3 .claude/hooks/session_start_context.py`
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    ".next", "out", "reports",
    "bundles/spark/connectors/cortex-content/baked",  # vendor data, not source
})


def _project_root() -> Path:
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(project) if project else Path(__file__).resolve().parents[2]


def _claude_md_areas(root: Path) -> set[str]:
    """Every directory (relative posix) that carries its own CLAUDE.md, except
    the repo root — the areas the CLAUDE.md hierarchy governs."""
    areas: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        if "CLAUDE.md" in filenames:
            rel = Path(dirpath).relative_to(root).as_posix()
            if rel != ".":
                areas.add(rel)
    return areas


def _area_of(changed: str, areas: set[str]) -> str | None:
    """The nearest CLAUDE.md-governed directory containing a changed file."""
    parts = changed.split("/")
    for depth in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:depth])
        if candidate in areas:
            return candidate
    return None


def _force_utf8() -> None:
    """Emit UTF-8 regardless of console code page — output goes into Claude's
    context and must not be mangled by cp1252 / latin-1."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _git(args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def _working_tree_changes() -> list[str]:
    paths: list[str] = []
    for line in _git(["status", "--porcelain"]).splitlines():
        if len(line) > 3:
            paths.append(line[3:].strip().replace("\\", "/"))
    return paths


def _active_areas(root: Path, paths: list[str]) -> list[str]:
    governed = _claude_md_areas(root)
    found: set[str] = set()
    for path in paths:
        area = _area_of(path, governed)
        if area is not None:
            found.add(area)
    return sorted(found)


def _recent_commits(limit: int = 5) -> list[str]:
    return [
        line.strip()
        for line in _git(["log", f"-{limit}", "--pretty=format:%h %s"]).splitlines()
        if line.strip()
    ]


def _current_branch() -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "(detached)"


def _ahead_behind_main() -> tuple[int, int] | None:
    """Return (ahead, behind) commits vs origin/main; None if unavailable."""
    raw = _git(["rev-list", "--left-right", "--count", "origin/main...HEAD"]).strip()
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2:
        return None
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return ahead, behind


def _in_progress_issues(limit: int = 5) -> list[str]:
    """Return GitHub issues labeled `status:in-progress`. Best-effort: returns [] if `gh` isn't
    available or unauthenticated."""
    if not shutil.which("gh"):
        return []
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--label", "status:in-progress",
             "--limit", str(limit), "--json", "number,title"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    try:
        rows = json.loads(result.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    return [f"#{row['number']} — {row['title']}" for row in rows]


def main() -> None:
    _force_utf8()

    # Drain the hook payload on stdin; this hook doesn't need it.
    try:
        sys.stdin.read()
    except (OSError, ValueError):
        pass

    lines = ["## Phantom — session orientation", ""]

    # Branch + divergence
    branch = _current_branch()
    ab = _ahead_behind_main()
    if branch == "main" and ab is None:
        lines.append("Branch: **main** (on the dev-cycle path — push freely).")
    elif branch == "main" and ab is not None:
        ahead, behind = ab
        if ahead == 0 and behind == 0:
            lines.append("Branch: **main**, up-to-date with origin.")
        else:
            lines.append(f"Branch: **main** — {ahead} ahead / {behind} behind origin.")
    else:
        lines.append(f"Branch: **{branch}** (off main — dev cycle assumes main).")
    lines.append("")

    # Active areas this session
    changes = _working_tree_changes()
    areas = _active_areas(_project_root(), changes)
    if areas:
        lines.append(f"Active area(s) this session: **{', '.join(areas)}**.")
        lines.append("Load the matching `CLAUDE.md` in each before editing.")
    else:
        lines.append("Working tree is clean — no area has pending work.")
    lines.append("")

    # In-flight issues
    issues = _in_progress_issues()
    if issues:
        lines.append("In-flight issues (`status:in-progress`):")
        lines.extend(f"- {row}" for row in issues)
        lines.append("")

    # Recent commits
    commits = _recent_commits()
    if commits:
        lines.append("Recent commits (newest first):")
        lines.extend(f"- {commit}" for commit in commits)
        lines.append("")

    lines.append(
        "Use `CODEBASE_MAP.md` to find where a feature lives. Use `AI-LAYER.md` "
        "for the harness overview. Root `CLAUDE.md` carries repo-wide contracts; "
        "each subdirectory has its own local conventions."
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
