"""
Skills CRUD MCP Tools

Provides tools for managing simulation skills: Create, Read, Update, Delete
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from mcp import types as mcp_types
import json
import yaml


# YAML frontmatter delimiter — `---` on its own line, top of file.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Split a markdown file into (frontmatter_dict, body).

    If the file has no `---\\n...\\n---\\n` block at the top, returns
    ({}, content) — callers can fall back to legacy heading parsing.

    Returns the parsed YAML as a dict (empty dict on parse error) plus
    the body without the frontmatter block. This is the same shape
    operators are used to from Hugo / Jekyll / Astro / etc., so authoring
    a skill should feel familiar.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    fm_text, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(fm_text) or {}
        if not isinstance(parsed, dict):
            return {}, content
        return parsed, body
    except yaml.YAMLError:
        # Malformed YAML — fall back to no metadata rather than failing
        # to list the skill at all. Surfaces in the UI as a card with
        # default icon + filename-derived display name.
        return {}, content


def _extract_h1(body: str) -> Optional[str]:
    """Return the first H1 heading text, or None."""
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return None


# Re-use skills directory logic from simulation_skills.py
_current_file = Path(__file__).resolve()

def find_skills_dir(start_path: Path) -> Path:
    """Search upward from start_path to find mcp/server/skills directory."""
    current = start_path.parent

    for _ in range(10):
        candidate = current / "mcp" / "server" / "skills"
        if candidate.exists() and candidate.is_dir():
            return candidate

        if current.name == "server" and (current / "skills").exists():
            return current / "skills"

        if current.name == "builtin_components":
            server_dir = current.parent.parent.parent
            skills_candidate = server_dir / "skills"
            if skills_candidate.exists() and skills_candidate.is_dir():
                return skills_candidate

        if current.parent == current:
            break
        current = current.parent

    fallback = Path(os.getenv("SKILLS_DIR", "/app/skills")).resolve()
    if fallback.exists():
        return fallback

    return Path("/app/skills")

SKILLS_DIR = find_skills_dir(_current_file)


def get_all_skills() -> List[Dict[str, Any]]:
    """
    Get list of all skills with metadata.

    Returns:
        List of skill dictionaries with path, category, name, size
    """
    import logging
    logger = logging.getLogger(__name__)

    skills = []

    logger.info(f"[SKILLS_CRUD] SKILLS_DIR = {SKILLS_DIR}")
    logger.info(f"[SKILLS_CRUD] SKILLS_DIR.exists() = {SKILLS_DIR.exists()}")

    if not SKILLS_DIR.exists():
        logger.warning(f"[SKILLS_CRUD] Skills directory does not exist: {SKILLS_DIR}")
        return skills

    # List all items in SKILLS_DIR
    try:
        items = list(SKILLS_DIR.iterdir())
        logger.info(f"[SKILLS_CRUD] Found {len(items)} items in {SKILLS_DIR}")
        for item in items:
            logger.info(f"[SKILLS_CRUD]   - {item.name} (is_dir={item.is_dir()})")
    except Exception as e:
        logger.error(f"[SKILLS_CRUD] Error listing directory: {e}")
        return skills

    def _build_record(
        skill_file: Path,
        category: str,
        plugin_vendor: str | None = None,
    ) -> Dict[str, Any] | None:
        """Build the per-skill dict. Returns None on read error so the
        outer loop can skip without aborting the whole listing.

        `plugin_vendor` is set only for skills under `plugins/<vendor>/`
        — surfaced in the response so the UI can show vendor attribution
        on plugin skills, and used as a sub-namespace in the canonical
        name to avoid collisions between two plugins shipping a skill
        with the same filename.
        """
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[SKILLS_CRUD] Error reading {skill_file}: {e}")
            return None
        fm, body = parse_frontmatter(content)

        # Resolution order for the operator-facing display name:
        # frontmatter displayName → first H1 heading → filename stem.
        # The legacy fallbacks let un-migrated skills still render
        # reasonably.
        display_name = (
            fm.get("displayName")
            or fm.get("display_name")
            or _extract_h1(body)
            or skill_file.stem
        )

        # For plugin skills, qualify the canonical name with the
        # vendor so two plugins shipping `port_scan.md` don't
        # collide at the chat-agent's <available_skills> block.
        # Operators see the unprefixed displayName, but the agent
        # uses the qualified name as the primary key.
        canonical_name = fm.get("name") or skill_file.stem
        if plugin_vendor and not str(canonical_name).startswith(f"{plugin_vendor}."):
            canonical_name = f"{plugin_vendor}.{canonical_name}"

        # Category resolution:
        #   - For plugin-discovered skills (plugins/<vendor>/*.md), the
        #     filesystem path is authoritative. Frontmatter `category:
        #     foundation` on a plugin skill is treated as a HINT — the
        #     skill still lists under "plugins" so operators filtering
        #     by category have a reliable view of "plugin-contributed
        #     vs. built-in." The frontmatter category is preserved on
        #     the record as `declared_category` for any consumer that
        #     wants the original value.
        #   - For built-in skills, the path-derived category is the
        #     correct default but operators can override via frontmatter
        #     (e.g. moving a skill from foundation → workflows in-place).
        if plugin_vendor:
            resolved_category = "plugins"
            declared_category = fm.get("category") or category
        else:
            resolved_category = fm.get("category") or category
            declared_category = resolved_category

        record: Dict[str, Any] = {
            "file_path": str(skill_file.relative_to(SKILLS_DIR)),
            "absolute_path": str(skill_file),
            # Canonical identifier: filename without `.md` (vendor-
            # qualified for plugin skills) — same shape as MCP tool
            # names, stable across display-name edits, used as the
            # primary key in the chat agent's <available_skills> block.
            "name": canonical_name,
            "displayName": display_name,
            "category": resolved_category,
            "declared_category": declared_category,
            "description": fm.get("description") or "",
            "icon": fm.get("icon") or "",
            "source": fm.get("source") or ("plugin" if plugin_vendor else "platform"),
            "loadingMode": fm.get("loadingMode") or "on-demand",
            "locked": bool(fm.get("locked", False)),
            "attack": fm.get("attack") or [],
            # Full frontmatter passthrough for fields that
            # `load_simulation_skills` (simulation_skills.py) and
            # `filter_skills` need. Each skill carries its own metadata
            # in frontmatter, making the .md file the single source of
            # truth (a separate hardcoded dict drifts from disk).
            # Missing fields return falsy defaults — filter_skills
            # treats absence as "no constraint" so unfilled fields
            # don't drop the skill from filtered responses.
            "keywords": fm.get("keywords") or [],
            "complexity": fm.get("complexity") or "",
            "duration": fm.get("duration") or "",
            "attack_type": fm.get("attack_type") or "",
            "caldera_required": bool(fm.get("caldera_required", False)),
            "devices_required": fm.get("devices_required") or [],
            "prerequisites": fm.get("prerequisites") or [],
            "outputs": fm.get("outputs") or [],
            "tactics": fm.get("tactics") or [],
            "techniques": fm.get("techniques") or [],
            # Surface the skill-side execution-policy
            # fields (model / thinking / permissions). The job scheduler
            # already reads these via _parse_skill_frontmatter; this
            # exposes them through the listing API so the /skills UI
            # can show "this skill recommends model X" indicators
            # without re-parsing per skill. Missing fields render as
            # None so the UI knows "no recommendation."
            "model": fm.get("model") if isinstance(fm.get("model"), str) else None,
            "thinking": bool(fm.get("thinking", False)),
            "permissions": (
                fm.get("permissions")
                if isinstance(fm.get("permissions"), dict)
                else None
            ),
            # Legacy fields kept for back-compat with the /api/skills
            # route + any tooling reading the raw response.
            "filename": skill_file.name,
            "size_bytes": skill_file.stat().st_size,
            "modified": skill_file.stat().st_mtime,
            # Convenience flag for the UI: did this skill have
            # parseable frontmatter at all? Cards without frontmatter
            # get a "needs migration" badge.
            "has_frontmatter": bool(fm),
        }
        if plugin_vendor:
            # Surface the vendor for plugin-contributed
            # skills so the UI can attribute them. Bundle-built-in
            # skills (foundation/scenarios/validation/workflows) omit
            # this field entirely.
            record["plugin_vendor"] = plugin_vendor
        return record

    # ── Built-in categories: foundation / scenarios / validation /
    # workflows / anything else the bundle ships at the top level.
    # Each subdir's *.md files are indexed directly. The `plugins/`
    # dir gets special handling below — its layout is one extra level
    # deep (plugins/<vendor>/<skill>.md) and we walk that explicitly.
    EXCLUDED_DIRS = {"__pycache__", ".git", ".deleted", "plugins"}

    for category_dir in SKILLS_DIR.iterdir():
        if not (category_dir.is_dir() and category_dir.name not in EXCLUDED_DIRS):
            continue
        category = category_dir.name
        logger.info(f"[SKILLS_CRUD] Scanning category: {category}")

        md_files = list(category_dir.glob("*.md"))
        logger.info(f"[SKILLS_CRUD]   Found {len(md_files)} .md files in {category}")
        for skill_file in md_files:
            record = _build_record(skill_file, category)
            if record is None:
                continue
            skills.append(record)
            logger.info(f"[SKILLS_CRUD]     Added skill: {record['displayName']}")

    # ── Plugin skills.
    # Layout: plugins/<vendor>/<skill>.md. The bundle's plugin
    # contract puts each plugin's skill markdown into its vendor-
    # named subdir; the entrypoint script copies bundle source into
    # /app/skills/plugins/<vendor>/ at boot. The walker must
    # not treat `plugins` like any other category (it only globs
    # top-level *.md, of which there are none), or plugin skills would
    # never appear in /api/skills despite being on disk, so we
    # descend one extra level explicitly.
    plugins_dir = SKILLS_DIR / "plugins"
    if plugins_dir.exists() and plugins_dir.is_dir():
        for vendor_dir in plugins_dir.iterdir():
            if not vendor_dir.is_dir() or vendor_dir.name in EXCLUDED_DIRS:
                continue
            vendor = vendor_dir.name
            logger.info(f"[SKILLS_CRUD] Scanning plugin vendor: {vendor}")
            md_files = list(vendor_dir.glob("*.md"))
            logger.info(f"[SKILLS_CRUD]   Found {len(md_files)} .md files in plugins/{vendor}")
            for skill_file in md_files:
                record = _build_record(skill_file, "plugins", plugin_vendor=vendor)
                if record is None:
                    continue
                skills.append(record)
                logger.info(
                    f"[SKILLS_CRUD]     Added plugin skill: {record['displayName']} (vendor={vendor})"
                )

    logger.info(f"[SKILLS_CRUD] Total skills found: {len(skills)}")
    return sorted(skills, key=lambda x: (x["category"], x["filename"]))


def create_skill(category: str, filename: str, content: str) -> Dict[str, Any]:
    """
    Create a new skill file.

    Args:
        category: Skill category (foundation, scenarios, validation, workflows)
        filename: Filename (must end with .md)
        content: Markdown content of the skill

    Returns:
        Result dictionary with success status and message
    """
    if not filename.endswith(".md"):
        return {"success": False, "error": "Filename must end with .md"}

    if category not in ["foundation", "scenarios", "validation", "workflows"]:
        return {"success": False, "error": f"Invalid category: {category}. Must be one of: foundation, scenarios, validation, workflows"}

    category_dir = SKILLS_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)

    skill_path = category_dir / filename

    if skill_path.exists():
        return {"success": False, "error": f"Skill already exists: {skill_path.relative_to(SKILLS_DIR)}"}

    try:
        skill_path.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "message": f"Created skill: {skill_path.relative_to(SKILLS_DIR)}",
            "path": str(skill_path.relative_to(SKILLS_DIR))
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to create skill: {str(e)}"}


def read_skill(file_path: str) -> Dict[str, Any]:
    """
    Read a skill file content.

    Args:
        file_path: Relative path from skills directory (e.g., "scenarios/port_scan.md")

    Returns:
        Result dictionary with skill content
    """
    skill_path = SKILLS_DIR / file_path

    if not skill_path.exists():
        return {"success": False, "error": f"Skill not found: {file_path}"}

    if not skill_path.is_file():
        return {"success": False, "error": f"Not a file: {file_path}"}

    try:
        content = skill_path.read_text(encoding="utf-8")
        return {
            "success": True,
            "content": content,
            "path": file_path,
            "size_bytes": skill_path.stat().st_size
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to read skill: {str(e)}"}


def update_skill(file_path: str, content: str) -> Dict[str, Any]:
    """
    Update an existing skill file.

    Args:
        file_path: Relative path from skills directory (e.g., "scenarios/port_scan.md")
        content: New markdown content

    Returns:
        Result dictionary with success status
    """
    skill_path = SKILLS_DIR / file_path

    if not skill_path.exists():
        return {"success": False, "error": f"Skill not found: {file_path}"}

    try:
        # Backup original content
        original = skill_path.read_text(encoding="utf-8")
        backup_path = skill_path.with_suffix(".md.bak")
        backup_path.write_text(original, encoding="utf-8")

        # Write new content
        skill_path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "message": f"Updated skill: {file_path}",
            "backup": str(backup_path.relative_to(SKILLS_DIR))
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to update skill: {str(e)}"}


def delete_skill(file_path: str) -> Dict[str, Any]:
    """
    Delete a skill file.

    Args:
        file_path: Relative path from skills directory (e.g., "scenarios/port_scan.md")

    Returns:
        Result dictionary with success status
    """
    skill_path = SKILLS_DIR / file_path

    if not skill_path.exists():
        return {"success": False, "error": f"Skill not found: {file_path}"}

    try:
        # Create backup before deleting
        backup_dir = SKILLS_DIR / ".deleted"
        backup_dir.mkdir(exist_ok=True)

        backup_path = backup_dir / skill_path.name
        counter = 1
        while backup_path.exists():
            backup_path = backup_dir / f"{skill_path.stem}_{counter}.md"
            counter += 1

        skill_path.rename(backup_path)

        return {
            "success": True,
            "message": f"Deleted skill: {file_path}",
            "backup": str(backup_path.relative_to(SKILLS_DIR))
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to delete skill: {str(e)}"}


# MCP Tool Definitions

def get_tools() -> List[mcp_types.Tool]:
    """Return all skills CRUD MCP tools."""
    return [
        mcp_types.Tool(
            name="skills_list_all",
            description="List all available simulation skills with metadata. Returns all skills across foundation, scenarios, validation, and workflows categories.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        mcp_types.Tool(
            name="skills_read",
            description="Read the content of a specific skill file. Use this to view or edit an existing skill.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to skill file from skills directory (e.g., 'scenarios/port_scan.md')"
                    }
                },
                "required": ["file_path"]
            }
        ),
        mcp_types.Tool(
            name="skills_create",
            description="Create a new skill file. Use this to add new scenarios, foundation skills, validation skills, or workflows.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["foundation", "scenarios", "validation", "workflows"],
                        "description": "Skill category"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename for the skill (must end with .md)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown content of the skill"
                    }
                },
                "required": ["category", "filename", "content"]
            }
        ),
        mcp_types.Tool(
            name="skills_update",
            description="Update an existing skill file. Creates a backup (.md.bak) before updating.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to skill file (e.g., 'scenarios/port_scan.md')"
                    },
                    "content": {
                        "type": "string",
                        "description": "New markdown content"
                    }
                },
                "required": ["file_path", "content"]
            }
        ),
        mcp_types.Tool(
            name="skills_delete",
            description="Delete a skill file. Creates a backup in .deleted directory before deletion.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to skill file (e.g., 'scenarios/port_scan.md')"
                    }
                },
                "required": ["file_path"]
            }
        )
    ]


# FastMCP tool functions (for registration in main.py)

def skills_list_all() -> str:
    """
    List all available simulation skills with metadata.

    Returns all skills across foundation, scenarios, validation, and workflows categories
    with information about file path, category, name, size, and last modified time.
    """
    skills = get_all_skills()
    return json.dumps(skills, indent=2)


def skills_read(file_path: str) -> str:
    """
    Read the content of a specific skill file.

    Args:
        file_path: Relative path to skill file from skills directory (e.g., 'scenarios/port_scan.md')

    Returns:
        JSON with skill content and metadata
    """
    result = read_skill(file_path)
    return json.dumps(result, indent=2)


def skills_create(category: str, filename: str, content: str) -> str:
    """
    Create a new skill file.

    Args:
        category: Skill category (foundation, scenarios, validation, workflows)
        filename: Filename for the skill (must end with .md)
        content: Markdown content of the skill

    Returns:
        JSON with success status and created file path
    """
    result = create_skill(category, filename, content)
    return json.dumps(result, indent=2)


def skills_update(file_path: str, content: str) -> str:
    """
    Update an existing skill file.

    Creates a backup (.md.bak) before updating.

    Args:
        file_path: Relative path to skill file (e.g., 'scenarios/port_scan.md')
        content: New markdown content

    Returns:
        JSON with success status and backup file location
    """
    result = update_skill(file_path, content)
    return json.dumps(result, indent=2)


def skills_delete(file_path: str) -> str:
    """
    Delete a skill file.

    Creates a backup in .deleted directory before deletion.

    Args:
        file_path: Relative path to skill file (e.g., 'scenarios/port_scan.md')

    Returns:
        JSON with success status and backup file location
    """
    result = delete_skill(file_path)
    return json.dumps(result, indent=2)
