"""Tools named by shipped YAML must exist in the real tool catalog.

The example-vendor plugin's agent definitions and the phantom-soc-v1 bench case
named tools that no connector or built-in registers (xsiam_execute_xql_query,
memory_list, caldera_list_operations, phantom_list_scenarios, ...). A subagent
whose allow-list names nothing real silently loses the tools it needs, and a
bench case that expects a missing tool can never score.

The catalog is rebuilt from the bundle itself: every connector.yaml tool in its
namespaced (`<id>.<tool>`) and legacy (`<functionPrefix><tool>`) form, the
built-in tool registry, and the tools main.py registers directly
(`mcp.tool()(name)`, for example the data_sources_* family).
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest
import yaml

from usecase.connector_loader import _BUILTIN_LEGACY_TOOLS, _legacy_alias

SPARK = Path(__file__).resolve().parents[2]
MAIN_PY = SPARK / "mcp" / "src" / "main.py"
CONNECTORS = SPARK / "connectors"
AGENT = SPARK.parents[1] / "mcp" / "agent"
PLUGIN_AGENTS = sorted((SPARK / "plugins").glob("*/agents/*.yaml"))
BENCH_CASES = sorted((SPARK / "mcp" / "src" / "usecase" / "bench_cases").glob("*.yaml"))


def _catalog() -> set[str]:
    names = {name for name, _fn in _BUILTIN_LEGACY_TOOLS}
    names |= set(re.findall(r"mcp\.tool\(\)\((\w+)\)", MAIN_PY.read_text(encoding="utf-8")))
    for manifest in sorted(CONNECTORS.glob("*/connector.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        cid = data.get("id")
        prefix = (data.get("runtimeMapping") or {}).get("functionPrefix", "")
        for tool in (data.get("spec") or {}).get("tools") or []:
            tool_name = tool.get("name")
            if not (cid and tool_name):
                continue
            names.add(f"{cid}.{tool_name}")
            legacy = _legacy_alias(prefix, tool_name)
            if legacy:
                names.add(legacy)
    return names


CATALOG = _catalog()


def _known(pattern: str) -> bool:
    if any(ch in pattern for ch in "*?["):
        return any(fnmatch.fnmatch(n, pattern) for n in CATALOG)
    return pattern in CATALOG


def test_catalog_was_built():
    assert "xlog.create_data_worker" in CATALOG
    assert "phantom_create_data_worker" in CATALOG
    assert "health_status" in CATALOG
    assert "caldera_get_all_agents" in CATALOG
    assert "xsiam_run_xql_query" in CATALOG
    assert "data_sources_installed_as_vendors" in CATALOG


def test_there_are_plugin_agents_and_bench_cases():
    assert PLUGIN_AGENTS and BENCH_CASES


@pytest.mark.parametrize("path", PLUGIN_AGENTS, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_plugin_agent_tools_exist(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("tools_allowed", "tools_denied"):
        unknown = [t for t in data.get(key) or [] if not _known(t)]
        assert not unknown, f"{path.name} {key} names tools that do not exist: {unknown}"


@pytest.mark.parametrize("path", BENCH_CASES, ids=lambda p: p.stem)
def test_bench_case_expected_tools_exist(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for case in (data.get("manifest") or {}).get("cases") or []:
        unknown = [t for t in case.get("expected_tool_calls") or [] if not _known(t)]
        assert not unknown, f"{path.name} case {case.get('id')} expects tools that do not exist: {unknown}"


# ── the agent UI's own references to tools ───────────────────────────────


def _ts(rel: str) -> str:
    if not AGENT.is_dir():
        pytest.skip("mcp/agent is not part of this checkout")
    return (AGENT / rel).read_text(encoding="utf-8")


def _tool_metadata_names() -> tuple[list[str], dict[str, str]]:
    """Keys of TOOL_METADATA_TABLE and the NAMESPACED_TO_TABLE_KEY pairs."""
    text = _ts("lib/tool-metadata.ts")
    table = text[text.index("export const TOOL_METADATA_TABLE") : text.index("export const NAMESPACED_TO_TABLE_KEY")]
    aliases = text[text.index("export const NAMESPACED_TO_TABLE_KEY") : text.index("export function resolveToolMetadata")]
    keys = re.findall(r"^  (\w+): \{", table, re.M)
    pairs = dict(re.findall(r'^  "([^"]+)": "([^"]+)",', aliases, re.M))
    return keys, pairs


def test_tool_metadata_table_names_only_real_tools():
    keys, pairs = _tool_metadata_names()
    assert len(keys) > 20 and pairs  # the parser found the table
    unknown = [k for k in keys if k not in CATALOG]
    assert not unknown, f"lib/tool-metadata.ts keys that are not tools: {unknown}"
    bad = {ns: key for ns, key in pairs.items() if ns not in CATALOG or key not in keys}
    assert not bad, f"NAMESPACED_TO_TABLE_KEY entries that do not line up with a tool and a table key: {bad}"


# Tool names the UI shows as examples, in comments and placeholders. A name that
# no connector provides sends the operator to write a matcher that never fires.
_UI_FILES_NAMING_TOOLS = [
    "app/api/chat/route.ts",
    "lib/hooks.ts",
    "lib/slack-approval-hook.ts",
    "lib/approvals-config.ts",
    "app/settings/hooks/page.tsx",
    "app/jobs/new/page.tsx",
]
_TOOL_TOKEN = re.compile(
    r"(?<![\w.*-])((?:caldera|xsiam|xlog)[_.][a-z][a-z0-9_]*|phantom_[a-z][a-z0-9_]*)(?![\w*])"
)
# Words of the product or of prose that happen to share a connector prefix.
_NOT_TOOLS = {"phantom_mcp", "phantom_agent"}


@pytest.mark.parametrize("rel", _UI_FILES_NAMING_TOOLS)
def test_ui_examples_name_real_tools(rel):
    unknown = sorted(
        # A token ending in "_" is a prefix being tested (startsWith('phantom_web_')), not a tool.
        {
            t
            for t in _TOOL_TOKEN.findall(_ts(rel))
            if t not in CATALOG and t not in _NOT_TOOLS and not t.endswith("_")
        }
    )
    assert not unknown, f"{rel} names tools that do not exist: {unknown}"


def test_slack_approval_default_glob_matches_real_tools():
    text = _ts("lib/slack-approval-hook.ts")
    glob = re.search(r'DEFAULT_TOOL_GLOB =\s*"([^"]+)"', text).group(1)
    for pattern in glob.split(","):
        assert _known(pattern), f"default toolGlob pattern {pattern!r} matches no tool"


# ── names the chat route itself carries ──────────────────────────────────


def _expand(alternation: str) -> list[str]:
    """Expand `a|b_(c|d)|e` (one nesting level) into the concrete names."""
    parts, depth, cur = [], 0, ""
    for ch in alternation:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    names: list[str] = []
    for part in parts:
        m = re.fullmatch(r"(\w*)\(([^()]*)\)", part)
        names += [m.group(1) + alt for alt in m.group(2).split("|")] if m else [part]
    return names


def test_chat_route_turn_cache_lists_name_real_tools():
    text = _ts("app/api/chat/route.ts")
    cacheable = re.search(r"TURN_CACHEABLE_TOOLS = new Set<string>\(\[(.*?)\]\)", text, re.S).group(1)
    reads = re.findall(r"'([\w.]+)'", cacheable)
    writes = _expand(re.search(r"return /\^\((.*)\)\$/\.test", text).group(1))
    assert len(reads) > 5 and len(writes) > 5  # the parsers found both lists
    unknown = [n for n in reads + writes if n not in CATALOG]
    assert not unknown, f"app/api/chat/route.ts names tools that do not exist: {unknown}"


def test_chat_route_plan_mode_example_names_real_tools():
    text = _ts("app/api/chat/route.ts")
    plan = text[text.index("const PLAN_MODE_INSTRUCTIONS") :]
    plan = plan[: plan.index("`;")]
    named = set(re.findall(r"\b((?:xlog|caldera|xsiam)\.[a-z_]+|data_sources_[a-z_]+)\b", plan))
    assert named
    unknown = sorted(n for n in named if n not in CATALOG)
    assert not unknown, f"the plan-mode prompt tells the model to use tools that do not exist: {unknown}"
