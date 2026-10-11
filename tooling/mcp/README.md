# `tooling/mcp/` — Phantom's repo-scoped MCP servers

MCP servers wired into the repo for Claude Code coding sessions. These are the AI Layer's MCP-side artifacts — distinct from Phantom's own runtime MCP (`bundles/spark/mcp/`), which serves the chat agent inside the customer container.

## `codebase_search.py`

AST-based structured search over Phantom's Python source. Exposes 3 tools via FastMCP stdio:

- `where_is(name)` — every Python definition of `name`
- `find_references(name)` — every Python use of `name`
- `outline(module)` — the structured API of a Python module

Coverage: `bundles/spark/mcp/`, `bundles/spark/connectors/*/src/`, `xlog/`, `updater/`, `scripts/`, `tooling/`, `phantom-connector-runtime/`. NOT covered: TypeScript (Next.js, `mcp/agent/**`) — use VS Code's "go to definition" or `Grep --type=ts` for TS symbols. Tree-sitter-typescript integration is tracked as a follow-up.

### Dependencies

Requires `mcp[cli]` 1.x (the FastMCP Python SDK; 2.x moved the import path this server uses). Install once:

```bash
pip install 'mcp[cli]<2'
```

If unavailable, the script fails fast with a clear error; the AI Layer treats codebase-search as best-effort tooling.

### Wired via `.mcp.json` (repo root)

```json
{
  "mcpServers": {
    "phantom-codebase-search": {
      "command": "python3",
      "args": ["tooling/mcp/codebase_search.py"]
    }
  }
}
```

Claude Code auto-loads this MCP server when started in the repo root.

### Run directly (for testing)

```bash
python3 tooling/mcp/codebase_search.py
```

The server runs over stdio — connect with any MCP-compatible client to test the tools.

## See also

- [`AI-LAYER.md`](../../AI-LAYER.md) — Phantom's article→artifact mapping
- [Anthropic article](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start) — MCP servers as structured-search tooling
- [Helpline `tooling/mcp/codebase_search.py`](https://github.com/coleam00/helpline/blob/main/tooling/mcp/codebase_search.py) — reference implementation
