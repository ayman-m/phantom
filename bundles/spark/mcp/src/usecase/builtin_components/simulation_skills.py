"""
Simulation Skills MCP Tool

Provides access to purple team simulation skill prompts for LLM agents.
Skills are structured guides for orchestrating attack scenarios using Phantom, CALDERA, and XSIAM.
"""

import os
from itertools import combinations
from pathlib import Path
from typing import Union, Dict, List, Optional, Any, Tuple
from mcp import types as mcp_types


# Path to skills directory
# This file is at: mcp/server/src/usecase/builtin_components/simulation_skills.py
# Skills are at: mcp/server/skills/
#
# Local path: /Users/.../phantom/phantom/mcp/server/src/usecase/builtin_components/simulation_skills.py
# Docker path: /app/src/usecase/builtin_components/simulation_skills.py
#
# Skills are now co-located with the MCP server for single source of truth

_current_file = Path(__file__).resolve()

# Search upward for a directory that contains "mcp/server/skills"
def find_skills_dir(start_path: Path) -> Path:
    """Search upward from start_path to find mcp/server/skills directory."""
    current = start_path.parent

    # Limit search to prevent infinite loops
    for _ in range(10):
        # Check if mcp/server/skills exists from current directory
        candidate = current / "mcp" / "server" / "skills"
        if candidate.exists() and candidate.is_dir():
            return candidate

        # Also check if we're already inside mcp/server directory structure
        # In that case, navigate to server/skills
        if current.name == "server" and (current / "skills").exists():
            return current / "skills"

        # Check if we're in src/usecase/builtin_components and go up to server/skills
        if current.name == "builtin_components":
            server_dir = current.parent.parent.parent  # up from builtin_components -> usecase -> src -> server
            skills_candidate = server_dir / "skills"
            if skills_candidate.exists() and skills_candidate.is_dir():
                return skills_candidate

        # Move up one level
        if current.parent == current:  # Reached filesystem root
            break
        current = current.parent

    # Fallback: assume Docker structure where skills are at /app/skills (server/skills mounted)
    # or use environment variable if set
    fallback = Path(os.getenv("SKILLS_DIR", "/app/skills")).resolve()
    if fallback.exists():
        return fallback

    # Final fallback: return expected path even if it doesn't exist yet
    # (allows for testing/development scenarios)
    return Path("/app/skills")

SKILLS_DIR = find_skills_dir(_current_file)


def get_skill_metadata() -> Dict[str, Dict[str, Any]]:
    """
    Returns metadata for all available skills, sourced ENTIRELY from
    disk via `skills_crud.get_all_skills()`. The .md frontmatter is
    the single source of truth for every per-skill field.

    There is no hardcoded enrichment dict: any hardcoded dict drifts
    from disk and creates maintenance debt. The enrichment fields
    (keywords, complexity, etc.) are frontmatter passthroughs in
    skills_crud._build_record. The .md file's YAML frontmatter
    is the entire contract; the chat agent's available_skills block,
    the load_simulation_skills filter logic, and the UI all read from
    the same parsed-frontmatter dict.

    Resulting record shape per skill:
      name, file_path, category, description, keywords[], complexity,
      duration, attack_type, caldera_required, devices_required[],
      prerequisites[], outputs[], tactics[], techniques[]

    Missing frontmatter fields return falsy defaults — filter_skills()
    treats absence as "no constraint" so unfilled fields don't drop
    the skill from filtered responses.
    """
    try:
        from usecase.builtin_components.skills_crud import get_all_skills
    except ImportError:
        # Defensive — test harness without the full module path.
        # Returns empty set; consumers handle gracefully.
        return {}

    disk_rows = get_all_skills()
    out: Dict[str, Dict[str, Any]] = {}
    for row in disk_rows:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            continue
        # frontmatter-declared `attack` is the ATT&CK tactics list;
        # if `tactics` was also declared, prefer it; otherwise fall
        # back to `attack`. Same value; two field-name conventions in
        # use across the bundle's skill files.
        tactics = row.get("tactics") or row.get("attack") or []
        out[name] = {
            "category": row.get("category") or row.get("declared_category") or "",
            "file_path": row.get("file_path") or "",
            "name": row.get("displayName") or name,
            "description": row.get("description") or "",
            "keywords": row.get("keywords") or [],
            "complexity": row.get("complexity") or "",
            "duration": row.get("duration") or "",
            "attack_type": row.get("attack_type") or "",
            "caldera_required": bool(row.get("caldera_required", False)),
            "devices_required": row.get("devices_required") or [],
            "prerequisites": row.get("prerequisites") or [],
            "outputs": row.get("outputs") or [],
            "tactics": tactics,
            "techniques": row.get("techniques") or [],
        }
    return out




def read_skill_file(file_path: str) -> Optional[str]:
    """
    Read a skill markdown file and return its contents.

    Args:
        file_path: Relative path from skills directory (e.g., "foundation/generate_shared_iocs.md")

    Returns:
        File contents as string, or None if file not found
    """
    full_path = SKILLS_DIR / file_path

    if not full_path.exists():
        return None

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def _norm(text: str) -> str:
    """Lowercase and treat `_`/`-` as spaces so `web shell`, `web-shell` and
    a skill file named `web_app_to_webshell_...` can be compared."""
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _keyword_score(metadata: Dict[str, Any], keywords: List[str]) -> int:
    """How strongly a skill matches any of `keywords`; 0 means no match.

    Matches name > displayName/description > frontmatter keywords > body text.
    A phrase also matches with its spaces removed ("web shell" finds
    "webshell"). Higher scores sort first.
    """
    skill_id = str(metadata.get("skill_id") or "")
    fields = [
        (_norm(skill_id), 8),
        (_norm(str(metadata.get("name") or "")), 6),
        (_norm(str(metadata.get("description") or "")), 4),
        (_norm(" ".join(str(k) for k in (metadata.get("keywords") or []))), 4),
    ]
    body: Optional[str] = None
    best = 0
    for raw in keywords:
        phrase = _norm(raw)
        if not phrase:
            continue
        squashed = phrase.replace(" ", "")
        for text, weight in fields:
            if phrase in text or squashed in text.replace(" ", ""):
                best = max(best, weight)
        if best == 0:
            if body is None:
                path = metadata.get("file_path")
                body = _norm(read_skill_file(path) or "") if path else ""
            if phrase in body or squashed in body.replace(" ", ""):
                best = 1
    return best


def _apply_filters(
    all_skills: Dict[str, Dict[str, Any]],
    category: Optional[str],
    attack_type: Optional[str],
    complexity: Optional[str],
    caldera_available: Optional[bool],
    keywords: Optional[List[str]],
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for skill_id, metadata in all_skills.items():
        if category and metadata.get("category") != category:
            continue
        # A skill that declares no attack_type / complexity has no opinion
        # about it: absence is "no constraint", only a declared different
        # value excludes the skill.
        declared = metadata.get("attack_type")
        if attack_type and declared and str(declared).lower() != attack_type.lower():
            continue
        declared = metadata.get("complexity")
        if complexity and declared and str(declared).lower() != complexity.lower():
            continue
        if caldera_available is False and metadata.get("caldera_required") is True:
            continue
        entry = {"skill_id": skill_id, **metadata}
        if keywords:
            score = _keyword_score(entry, keywords)
            if score == 0:
                continue
            entry["_score"] = score
        matched.append(entry)
    if keywords:
        matched.sort(key=lambda e: -e["_score"])
        for e in matched:
            del e["_score"]
    return matched


# Filters that may be dropped when nothing matches, in preference order (the
# first of two equally small drop sets wins). caldera_available is a hard
# requirement (a skill that needs CALDERA cannot run without it) and keywords
# are never relaxed: dropping them would turn "nothing matches your words" into
# "here is the whole catalog". category goes last: a category the catalog does
# not have is the only reason to widen past it.
_RELAXABLE = ("complexity", "attack_type", "category")

# A relaxed result is a set of suggestions, not an answer: at most this many
# skills, metadata only, so a miss can never dump the catalog's bodies.
RELAXED_RESULT_LIMIT = 10


def filter_skills_with_notes(
    category: Optional[str] = None,
    attack_type: Optional[str] = None,
    complexity: Optional[str] = None,
    caldera_available: Optional[bool] = None,
    keywords: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter skills; relax category/attack_type/complexity instead of returning nothing.

    Returns (skills, filters_relaxed). When the filters as given match nothing,
    the SMALLEST set of category/attack_type/complexity filters whose removal
    produces matches is dropped (one filter at a time first, then pairs, then
    all three) and reported as {"filter", "value", "reason"}; filters that were
    not the cause are never reported. `keywords` and `caldera_available` are
    never relaxed, so keywords that match nothing return ([], []). The list is
    empty in `filters_relaxed` when the filters matched as given.
    """
    all_skills = get_skill_metadata()
    given: Dict[str, Any] = {
        "category": category or None,
        "attack_type": attack_type or None,
        "complexity": complexity or None,
    }

    def run(dropped: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        use = {k: (None if k in dropped else v) for k, v in given.items()}
        return _apply_filters(
            all_skills,
            use["category"],
            use["attack_type"],
            use["complexity"],
            caldera_available,
            keywords or None,
        )

    matched = run()
    if matched:
        return matched, []
    active = [n for n in _RELAXABLE if given[n] is not None]
    for size in range(1, len(active) + 1):
        for dropped in combinations(active, size):
            matched = run(dropped)
            if not matched:
                continue
            notes = []
            for name in dropped:
                others = [d for d in dropped if d != name]
                together = f" (together with {', '.join(others)})" if others else ""
                notes.append(
                    {
                        "filter": name,
                        "value": given[name],
                        "reason": (
                            f"no skill matched {name}={given[name]!r} with the other "
                            f"filters; ignoring it{together} gave {len(matched)} match(es)"
                        ),
                    }
                )
            return matched, notes
    return [], []


def filter_skills(
    category: Optional[str] = None,
    attack_type: Optional[str] = None,
    complexity: Optional[str] = None,
    caldera_available: Optional[bool] = None,
    keywords: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Filter skills (see filter_skills_with_notes); drops the relaxation notes."""
    return filter_skills_with_notes(
        category, attack_type, complexity, caldera_available, keywords
    )[0]


def _as_keyword_list(value: Any) -> Optional[List[str]]:
    """A model sends {} or a single string where a list is meant; accept both rather than fail the call.

    A string may hold several comma-separated phrases ("web shell, exfil").
    """
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return parts or None
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()] or None
    return None


async def load_simulation_skills(
    category: Optional[str] = None,
    attack_type: Optional[str] = None,
    complexity: Optional[str] = None,
    include_content: bool = True,
    include_field_reference: bool = False,
    caldera_available: Optional[bool] = None,
    keywords: Optional[Union[List[str], str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Load simulation skill runbooks (scenarios, workflows, foundation).

    Call this FIRST for any simulation request, to see whether a shipped skill
    already covers it. Every filter is optional. The simplest, most reliable
    call is `keywords` alone ("web shell", "dns tunneling", "port scan"), or no
    filter at all with include_content=False to browse the whole catalog.

    Filtering is forgiving about metadata. Most shipped skills declare no
    `attack_type` or `complexity`, and a skill that declares none is never
    excluded by that filter. If the filters still match nothing, the smallest
    set of category / attack_type / complexity filters whose removal produces
    matches is dropped and listed in `filters_relaxed`. A relaxed result is a
    short list of suggestions: at most 10 skills, metadata only (no `content`
    even when include_content=True). Read `hint`, pick a skill by name and
    description, then call `skills_read` with its path (for example
    "scenarios/dns_tunneling_c2.md") or repeat the call with fewer filters.
    `keywords` are never dropped: if no skill matches them the result is an
    EMPTY list with a `hint` (retry with one or two broader words, or browse
    with include_content=False and no filters). You can also skip this tool and
    call `skills_read` with a path from the AVAILABLE SKILLS block.

    Args:
        category: "foundation" (building blocks), "scenarios" (multi-stage attack
            chains), "validation" (verification), "workflows" (end-to-end runs and
            the alert-trigger recipes). Omit for every category.
        attack_type: Optional hint ("apt", "ransomware", "credential_theft", ...).
            Only skills that declare a different attack_type are excluded.
        complexity: Optional hint ("low", "medium", "high"). Only skills that
            declare a different complexity are excluded.
        include_content: True returns each skill's full markdown body (use when
            about to execute); False returns metadata only (use when browsing).
            Ignored (metadata only) when filters were relaxed.
        caldera_available: False excludes skills that require CALDERA. This is a
            hard requirement and is never relaxed.
        keywords: Free text, one phrase or several comma-separated, matched
            case-insensitively against each skill's name, display name,
            description, frontmatter keywords and full body text. Matching any one
            phrase is enough. "web shell" also finds "webshell". Results are
            ordered best match first (name matches before body-only matches).

    Returns:
        success, skills (metadata, plus `content` when requested), summary
        (total_skills returned, total_matched, by_category, filters_applied),
        filters_relaxed (list of {filter, value, reason}; empty when the filters
        matched as given), hint (null unless the result was relaxed or empty)
        and usage_guidance.

    Examples:
        # Find the web shell scenario
        load_simulation_skills(keywords="web shell")

        # The same, with extra hints that do not have to match exactly
        load_simulation_skills(category="scenarios", attack_type="apt", complexity="medium", keywords="web shell")

        # Browse every skill, metadata only
        load_simulation_skills(include_content=False)

        # Skills that run without CALDERA
        load_simulation_skills(caldera_available=False, include_content=False)
    """
    keyword_list = _as_keyword_list(keywords)
    matched_skills, filters_relaxed = filter_skills_with_notes(
        category=category,
        attack_type=attack_type,
        complexity=complexity,
        caldera_available=caldera_available,
        keywords=keyword_list,
    )

    total_matched = len(matched_skills)
    if filters_relaxed:
        # Nearest-match suggestions only: names and descriptions, never bodies.
        matched_skills = matched_skills[:RELAXED_RESULT_LIMIT]
        include_content = False

    skills = []
    for skill_metadata in matched_skills:
        skill_data = skill_metadata.copy()
        if include_content:
            content = read_skill_file(skill_metadata["file_path"])
            if content:
                skill_data["content"] = content
            else:
                skill_data["content"] = f"Error: Could not read skill file at {skill_metadata['file_path']}"
        skills.append(skill_data)

    categories: Dict[str, int] = {}
    for skill in skills:
        cat = skill.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    summary = {
        "total_skills": len(skills),
        "total_matched": total_matched,
        "by_category": categories,
        "filters_applied": {
            "category": category,
            "attack_type": attack_type,
            "complexity": complexity,
            "caldera_available": caldera_available,
            "keywords": keyword_list,
        },
    }

    usage_guidance: List[str] = []
    hint: Optional[str] = None
    if filters_relaxed:
        dropped = ", ".join(f"{r['filter']}={r['value']!r}" for r in filters_relaxed)
        hint = (
            f"Filters relaxed ({dropped}): nothing matched them, so these are the nearest skills "
            f"(metadata only, {len(skills)} of {total_matched}). Choose by name and description, "
            "then call skills_read with its path (for example \"scenarios/dns_tunneling_c2.md\") "
            "or repeat this call with fewer filters and include_content=true."
        )
    elif not skills and keyword_list:
        hint = (
            f"No skill matches the keywords {keyword_list!r}. Retry with one or two broader "
            "words, browse with include_content=false and no filters, or call skills_read "
            "with a path from the AVAILABLE SKILLS block (for example "
            "\"scenarios/dns_tunneling_c2.md\")."
        )
    elif not skills:
        hint = (
            "No skill matches these filters. Browse with include_content=false and no "
            "filters, or call skills_read with a path from the AVAILABLE SKILLS block."
        )
    if hint:
        usage_guidance.append(hint)
    if category == "foundation":
        usage_guidance.append("Foundation skills are building blocks that scenarios and workflows build on.")
    elif category == "scenarios":
        usage_guidance.append("Scenario skills are complete multi-stage attack chains.")
        usage_guidance.append("Follow the step-by-step instructions in the skill, stage by stage.")
        usage_guidance.append("If a stage needs a data-source class that is not installed, follow the skill's missing-class step for that stage.")
    elif category == "validation":
        usage_guidance.append("Validation skills verify an earlier run; use them after the run.")
    elif category == "workflows":
        usage_guidance.append("Workflow skills are end-to-end recipes, including the alert-trigger recipes.")
        usage_guidance.append("Follow the phase-by-phase instructions in the skill.")
    else:
        usage_guidance.append("Pick the skill that matches the request, then follow its instructions exactly.")
        usage_guidance.append("Use foundation skills (baseline_normal_activity, bootstrap_dataset_fields) for background traffic and dataset preparation.")

    return {
        "success": True,
        "skills": skills,
        "summary": summary,
        "filters_relaxed": filters_relaxed,
        "hint": hint,
        "usage_guidance": usage_guidance,
        "skills_directory": str(SKILLS_DIR),
    }


# MCP tool resource for listing available skills
def get_skills_list_resource() -> mcp_types.Resource:
    """
    Creates an MCP resource listing all available simulation skills.

    This resource provides a quick reference of available skills without loading full content.
    """
    metadata = get_skill_metadata()

    # Build markdown content
    content = "# Available Purple Team Simulation Skills\n\n"

    # Group by category
    categories = {}
    for skill_id, data in metadata.items():
        cat = data.get("category", "unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((skill_id, data))

    # Foundation skills
    if "foundation" in categories:
        content += "## Foundation Skills\n\n"
        content += "Core building blocks for scenario creation.\n\n"
        for skill_id, data in categories["foundation"]:
            content += f"### {data['name']}\n"
            content += f"**ID:** `{skill_id}`\n\n"
            content += f"{data['description']}\n\n"
            content += f"- **Complexity:** {data.get('complexity', 'N/A')}\n"
            content += f"- **Prerequisites:** {', '.join(data.get('prerequisites', []))}\n"
            content += f"- **Outputs:** {', '.join(data.get('outputs', []))}\n\n"

    # Scenario skills
    if "scenarios" in categories:
        content += "## Scenario Skills\n\n"
        content += "Complete attack chains following MITRE ATT&CK.\n\n"
        for skill_id, data in categories["scenarios"]:
            content += f"### {data['name']}\n"
            content += f"**ID:** `{skill_id}`\n\n"
            content += f"{data['description']}\n\n"
            content += f"- **Attack Type:** {data.get('attack_type', 'N/A')}\n"
            content += f"- **Complexity:** {data.get('complexity', 'N/A')}\n"
            content += f"- **Duration:** {data.get('duration', 'N/A')}\n"
            content += f"- **CALDERA Required:** {'Yes' if data.get('caldera_required') else 'No'}\n"
            content += f"- **Tactics:** {', '.join(data.get('tactics', []))}\n"
            content += f"- **Prerequisites:** {', '.join(data.get('prerequisites', []))}\n\n"

    # Validation skills
    if "validation" in categories:
        content += "## Validation Skills\n\n"
        content += "Verify execution and validate detection coverage.\n\n"
        for skill_id, data in categories["validation"]:
            content += f"### {data['name']}\n"
            content += f"**ID:** `{skill_id}`\n\n"
            content += f"{data['description']}\n\n"
            content += f"- **Complexity:** {data.get('complexity', 'N/A')}\n"
            content += f"- **Prerequisites:** {', '.join(data.get('prerequisites', []))}\n"
            content += f"- **Outputs:** {', '.join(data.get('outputs', []))}\n\n"

    # Workflow skills
    if "workflows" in categories:
        content += "## Workflow Skills\n\n"
        content += "End-to-end processes combining multiple skills.\n\n"
        for skill_id, data in categories["workflows"]:
            content += f"### {data['name']}\n"
            content += f"**ID:** `{skill_id}`\n\n"
            content += f"{data['description']}\n\n"
            content += f"- **Complexity:** {data.get('complexity', 'N/A')}\n"
            content += f"- **Duration:** {data.get('duration', 'N/A')}\n"
            content += f"- **Prerequisites:** {', '.join(data.get('prerequisites', []))}\n"
            content += f"- **Outputs:** {', '.join(data.get('outputs', []))}\n\n"

    content += "\n---\n\n"
    content += "## Usage\n\n"
    content += "Load skills using the `load_simulation_skills` tool:\n\n"
    content += "```json\n"
    content += '{\n'
    content += '  "tool": "load_simulation_skills",\n'
    content += '  "params": {\n'
    content += '    "category": "scenarios",\n'
    content += '    "keywords": "dns tunneling"\n'
    content += '  }\n'
    content += '}\n'
    content += "```\n"

    return mcp_types.Resource(
        uri="skills://simulation/list",
        name="Purple Team Simulation Skills",
        description="List of all available simulation skills for purple team exercises",
        mimeType="text/markdown",
        text=content
    )
