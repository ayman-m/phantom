"""
Simulation Skills MCP Tool

Provides access to purple team simulation skill prompts for LLM agents.
Skills are structured guides for orchestrating attack scenarios using Phantom, CALDERA, and XSIAM.
"""

import os
from pathlib import Path
from typing import Union, Dict, List, Optional, Any
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


def filter_skills(
    category: Optional[str] = None,
    attack_type: Optional[str] = None,
    complexity: Optional[str] = None,
    caldera_available: Optional[bool] = None,
    keywords: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Filter skills based on criteria.

    Args:
        category: Filter by category (foundation, scenarios, validation, workflows)
        attack_type: Filter by attack type (ransomware, apt, credential_theft, etc.)
        complexity: Filter by complexity (low, medium, high)
        caldera_available: Filter by whether CALDERA is available
        keywords: If non-empty, only return skills
            whose `keywords` (inline metadata OR frontmatter) intersect
            the supplied list (case-insensitive substring match). The
            chat-route uses this to filter "load_simulation_skills"
            responses by what the operator's recent prompts actually
            mentioned — keeps system-prompt-relevant skills front and
            irrelevant ones out.

    Returns:
        List of matching skill metadata
    """
    all_skills = get_skill_metadata()
    filtered = []

    for skill_id, metadata in all_skills.items():
        # Apply filters
        if category and metadata.get("category") != category:
            continue

        if attack_type and metadata.get("attack_type") != attack_type:
            continue

        if complexity and metadata.get("complexity") != complexity:
            continue

        if caldera_available is False and metadata.get("caldera_required") is True:
            continue

        if keywords:
            # Match against inline keywords +
            # any frontmatter keywords the file declared. Empty
            # skill keywords means "no opinion" → don't filter
            # this skill out (keeps untagged skills available).
            skill_keywords = (metadata.get("keywords") or [])
            file_path_rel = metadata.get("file_path")
            if file_path_rel:
                fm = _read_frontmatter_keywords(file_path_rel)
                if fm:
                    skill_keywords = list(skill_keywords) + list(fm)
            if skill_keywords:
                # Lowercase + substring match: "fortigate" in
                # "fortigate-auth-spray" → True. Looser than exact
                # match because operator phrasing varies.
                kw_lc = [k.lower() for k in keywords]
                sk_lc = [k.lower() for k in skill_keywords]
                if not any(
                    any(kw in sk or sk in kw for sk in sk_lc)
                    for kw in kw_lc
                ):
                    continue

        # Add skill_id to metadata
        skill_data = {"skill_id": skill_id, **metadata}
        filtered.append(skill_data)

    return filtered


def _read_frontmatter_keywords(file_path_rel: str) -> List[str]:
    """Read YAML frontmatter from a skill MD
    file and return its `keywords` list (or empty). Best-effort:
    malformed frontmatter / missing files return []. Cached
    lifetime is per-process (skills don't change without a restart).
    """
    cached = _FRONTMATTER_KEYWORDS_CACHE.get(file_path_rel)
    if cached is not None:
        return cached
    try:
        skills_dir = find_skills_dir(Path(__file__).parent)
        full_path = skills_dir / file_path_rel
        if not full_path.exists():
            _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = []
            return []
        text = full_path.read_text(encoding="utf-8")
    except Exception:
        _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = []
        return []
    # Look for a leading `---\n...\n---\n` block.
    if not text.startswith("---"):
        _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = []
        return []
    end_idx = text.find("\n---", 3)
    if end_idx < 0:
        _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = []
        return []
    fm_text = text[3:end_idx].strip()
    try:
        import yaml as _yaml

        data = _yaml.safe_load(fm_text) or {}
    except Exception:
        _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = []
        return []
    raw = data.get("keywords") if isinstance(data, dict) else None
    # Also accept a `when.keywords` nested form (matches the SnowAgent
    # `when: { keywords: [...] }` shape).
    if not raw and isinstance(data, dict):
        when = data.get("when")
        if isinstance(when, dict):
            raw = when.get("keywords")
    if isinstance(raw, list):
        result = [str(k) for k in raw if isinstance(k, (str, int))]
    elif isinstance(raw, str):
        # Comma-separated fallback.
        result = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        result = []
    _FRONTMATTER_KEYWORDS_CACHE[file_path_rel] = result
    return result


_FRONTMATTER_KEYWORDS_CACHE: Dict[str, List[str]] = {}


def _as_keyword_list(value: Any) -> Optional[List[str]]:
    """A model sends {} or a single string where a list is meant; accept both rather than fail the call."""
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value] or None
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
    Load simulation skill prompts for purple team exercises.

    This tool provides access to structured skill guides that teach LLM agents how to:
    - Generate consistent IoCs across synthetic and real attack telemetry
    - Create realistic network topologies with multiple log sources
    - Execute complete attack scenarios (ransomware, APT, etc.)
    - Validate detection coverage and IoC correlation
    - Conduct end-to-end purple team exercises

    Skills can be filtered by category, attack type, complexity, and CALDERA availability.

    Args:
        category: Filter by category
            - "foundation": Core building blocks (IoC generation, topology design)
            - "scenarios": Complete attack chains (ransomware, APT)
            - "validation": Verification and testing (IoC correlation)
            - "workflows": End-to-end processes (purple team exercise)
            - None: Return summary of all skills

        attack_type: Filter scenario skills by attack type
            - "ransomware": Ransomware attack chains
            - "apt": Advanced Persistent Threat scenarios
            - "credential_theft": Credential-focused attacks
            - None: Return all attack types

        complexity: Filter by skill complexity
            - "low": Simple, quick to execute
            - "medium": Moderate complexity, standard scenarios
            - "high": Complex, multi-day exercises
            - None: Return all complexity levels

        include_content: Whether to include full skill markdown content
            - True: Return full skill content (for execution)
            - False: Return only metadata (for browsing)

        caldera_available: Filter by CALDERA requirement
            - True: Return all skills (CALDERA optional and required)
            - False: Return only skills that don't require CALDERA
            - None: Return all skills regardless of CALDERA

    Returns:
        Dictionary containing:
        - skills: List of skill objects with metadata and optionally content
        - summary: Overview of returned skills
        - total_count: Number of skills returned

    Examples:
        # Get foundation skills with full content
        load_simulation_skills(category="foundation", include_content=True)

        # Get ransomware scenario
        load_simulation_skills(category="scenarios", attack_type="ransomware")

        # Browse all available skills (metadata only)
        load_simulation_skills(include_content=False)

        # Get skills that don't require CALDERA
        load_simulation_skills(caldera_available=False)

        # Get high complexity scenarios
        load_simulation_skills(category="scenarios", complexity="high")
    """
    # Filter skills based on criteria
    matched_skills = filter_skills(
        category=category,
        attack_type=attack_type,
        complexity=complexity,
        caldera_available=caldera_available,
        keywords=_as_keyword_list(keywords),
    )

    # Prepare response
    skills = []

    for skill_metadata in matched_skills:
        skill_data = skill_metadata.copy()

        # Load content if requested
        if include_content:
            content = read_skill_file(skill_metadata["file_path"])
            if content:
                skill_data["content"] = content
            else:
                skill_data["content"] = f"Error: Could not read skill file at {skill_metadata['file_path']}"

        skills.append(skill_data)

    # Generate summary
    categories = {}
    for skill in skills:
        cat = skill.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    summary = {
        "total_skills": len(skills),
        "by_category": categories,
        "filters_applied": {
            "category": category,
            "attack_type": attack_type,
            "complexity": complexity,
            "caldera_available": caldera_available
        }
    }

    # Build usage guidance based on what was returned
    usage_guidance = []

    if category == "foundation":
        usage_guidance.append("Foundation skills are building blocks. Execute them in order:")
        usage_guidance.append("1. generate_shared_iocs - Create consistent IoCs")
        usage_guidance.append("2. create_device_topology - Design network environment")
        usage_guidance.append("Then proceed to a scenario skill.")

    elif category == "scenarios":
        usage_guidance.append("Scenario skills provide complete attack chains.")
        usage_guidance.append("Prerequisites:")
        usage_guidance.append("1. Run foundation skills first (IoCs and topology)")
        usage_guidance.append("2. Follow step-by-step instructions in the scenario")
        usage_guidance.append("3. Use validation skills after execution")

    elif category == "validation":
        usage_guidance.append("Validation skills verify scenario execution.")
        usage_guidance.append("Run these AFTER completing a scenario to:")
        usage_guidance.append("- Check IoC correlation across data sources")
        usage_guidance.append("- Identify detection gaps")
        usage_guidance.append("- Generate validation reports")

    elif category == "workflows":
        usage_guidance.append("Workflow skills orchestrate complete exercises.")
        usage_guidance.append("These combine multiple skills into end-to-end processes.")
        usage_guidance.append("Follow the phase-by-phase instructions for complete exercises.")

    else:
        # No category filter - provide general guidance
        usage_guidance.append("Typical execution order:")
        usage_guidance.append("1. Foundation skills (generate IoCs, create topology)")
        usage_guidance.append("2. Scenario skills (execute attack chain)")
        usage_guidance.append("3. Validation skills (verify correlation and coverage)")
        usage_guidance.append("4. Workflow skills (for complete exercises with reporting)")

    return {
        "success": True,
        "skills": skills,
        "summary": summary,
        "usage_guidance": usage_guidance,
        "skills_directory": str(SKILLS_DIR)
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
    content += '    "attack_type": "ransomware"\n'
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
