# `phantom-ai-layer` (plugin)

The article's *"distribute what works"* pattern: bundle the parts of an AI Layer that aren't repo-specific into one installable package, so a new repo or a new engineer gets the team's baseline Claude Code setup immediately — no manual copying of hooks and skills.

## What's bundled

| Component | File | What it does |
|-----------|------|--------------|
| Skill | `skills/scoped-tests/` | Picks the correctly scoped test command instead of the full suite. Generic — names no specific service. |
| Hook (trigger) | `hooks/hooks.json` + `hooks/propose_claude_md.py` | Stop hook — detects which `CLAUDE.md`-governed areas changed and spawns the reflector in the background (self-improving). |
| Hook (reflector) | `hooks/reflect_claude_md.py` | Calls headless `claude -p` to reflect on the session diff and propose concrete `CLAUDE.md` edits. Falls back to a deterministic note if `claude` is unavailable. |
| Subagent | `agents/explorer.md` | Genuinely read-only explorer (`Read, Grep, Glob` — no write tools) — maps a subsystem and returns a report; the main agent edits. |
| MCP server | `mcp/codebase_search.py` | AST-based structured search — `where_is`, `find_references`, `outline`. Parses the code; never substring-matches. Python only. |

The bundled hooks and MCP server resolve paths from `${CLAUDE_PLUGIN_ROOT}` and `CLAUDE_PROJECT_DIR`, so they work in whatever repo the plugin is installed into — they are not tied to Phantom. The Stop hook spawns `reflect_claude_md.py` from its own directory, so both files travel together.

## Install

```bash
# add the marketplace (the parent tooling/ directory), then install
/plugin marketplace add ./tooling
/plugin install phantom-ai-layer@phantom-tooling
```

Once installed:
- The `codebase-search` MCP server becomes available as a tool in every Claude Code session
- The Stop hook fires on every session end, writing proposals to `.claude/claude-md-review.md`
- The `explorer` subagent can be invoked for read-only subsystem mapping
- The `scoped-tests` skill auto-loads when the agent is about to run tests

## Dependencies

The MCP server requires `mcp[cli]` (the FastMCP Python SDK):

```bash
pip install 'mcp[cli]<2'
```

If unavailable, the MCP server fails fast with a clear error; the rest of the layer (skill + hooks + subagent) continues to work — they have no Python deps beyond the standard library.

## What's NOT bundled (intentionally)

Repo-specific pieces stay in the Phantom repo's own `.claude/`:

- The `CLAUDE.md` hierarchy (root + `mcp/agent/`, `bundles/spark/mcp/`, `bundles/spark/connectors/`, `xlog/`, `installer/`, `updater/`)
- The `phantom-explorer` subagent (knows Phantom's 5-service stack + catalog/credential boundary + dev-cycle gap)
- The `connector-add` / `mcp-tool-add` / `release-tag-flow` / `help-page-update` / `agent-page-add` path-scoped skills
- The `SessionStart` orientation hook (knows about Phantom's `status:in-progress` GitHub label convention)

These describe Phantom specifically and don't translate to other repos.

## See also

- [`AI-LAYER.md`](../../AI-LAYER.md) — Phantom's article→artifact mapping
- [Anthropic article](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start) — plugin distribution pattern (Pattern 3)
- [Helpline `helpline-ai-layer` plugin](https://github.com/coleam00/helpline/tree/main/tooling/helpline-ai-layer) — reference implementation
