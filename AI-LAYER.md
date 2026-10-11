# Phantom AI Layer

The coding-agent harness for this repo: the files, hooks, skills, subagent and MCP server that make Claude Code (and other coding agents) effective in a codebase of this size. It follows the approach in Anthropic's article *"How Claude Code works in large codebases: best practices and where to start"* ([read it here](https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start)). The article's thesis: **the harness around the model determines how Claude Code performs more than the model alone.**

> "AI Layer" is our name for that harness, borrowed from [coleam00/helpline](https://github.com/coleam00/helpline). The article describes the components; it does not use the phrase.

This file maps each component to the artifact that implements it.

---

## Components

| Component | Purpose | Artifact |
|---|---|---|
| **CLAUDE.md files** | Loaded first; a lean root, with subdirectory files loaded additively as the agent walks the tree | Root [`CLAUDE.md`](CLAUDE.md) plus six subdirectory files: [`mcp/agent/`](mcp/agent/CLAUDE.md), [`bundles/spark/mcp/`](bundles/spark/mcp/CLAUDE.md), [`bundles/spark/connectors/`](bundles/spark/connectors/CLAUDE.md), [`xlog/`](xlog/CLAUDE.md), [`installer/`](installer/CLAUDE.md), [`updater/`](updater/CLAUDE.md) |
| **Codebase map** | Find where a feature lives before exploring | [`CODEBASE_MAP.md`](CODEBASE_MAP.md) |
| **Ignore rules** | Keep generated files, baked vendor data, caches and lockfiles out of the agent's context | `.claudeignore` (including `bundles/spark/connectors/cortex-content/baked/`, the vendor catalog files that ship in the agent image but are not source) |
| **Hooks** | A start hook loads context dynamically; a stop hook reflects on the session and proposes `CLAUDE.md` updates | [`.claude/hooks/session_start_context.py`](.claude/hooks/session_start_context.py) (branch, touched areas, recent commits), [`.claude/hooks/propose_claude_md.py`](.claude/hooks/propose_claude_md.py) and [`.claude/hooks/reflect_claude_md.py`](.claude/hooks/reflect_claude_md.py) (the Stop hook: recursion guard, diff-fingerprint dedup, deterministic fallback; the reflector drafts edits into `.claude/claude-md-review.md`) |
| **Skills** | On-demand expertise with progressive disclosure, scoped to paths | [`.claude/skills/`](.claude/skills/): `connector-add`, `mcp-tool-add`, `release-tag-flow`, `help-page-update`, `agent-page-add`, `data-source-xdm-validation`. [`.agents/skills/`](.agents/skills/) mirrors the same tree for agents that read that location. Each skill carries `paths:` frontmatter, which the validator asserts |
| **Subagent** | Split exploration from editing: a read-only mapper in its own context window | [`.claude/agents/phantom-explorer.md`](.claude/agents/phantom-explorer.md), tools `Read, Grep, Glob` only. The validator asserts it has no write tools |
| **MCP server** | Structured code search as a callable tool | [`.mcp.json`](.mcp.json) and [`tooling/mcp/codebase_search.py`](tooling/mcp/codebase_search.py): AST-based `where_is`, `find_references` and `outline` over every Python source tree. The validator performs a real stdio handshake |
| **LSP** | Symbol-level precision instead of text-pattern false positives | [`pyproject.toml`](pyproject.toml) configures `[tool.pyright]` for every Python source tree; install with `pip install pyright "mcp[cli]<2"`. TypeScript is covered by the Next.js toolchain |
| **Plugin** | Bundle the repo-agnostic parts into an installable package distributed through a marketplace | [`tooling/phantom-ai-layer/`](tooling/phantom-ai-layer/) and [`tooling/.claude-plugin/marketplace.json`](tooling/.claude-plugin/marketplace.json). It carries the explorer subagent, the propose/reflect hooks, the codebase-search MCP and a generic `scoped-tests` skill. Phantom-specific skills stay in `.claude/skills/` |
| **Scoped test commands** | Run only the tests for the code you touched | Each subdirectory `CLAUDE.md` documents its local pytest, tsc and lint commands; the root keeps the full pre-deploy gate. The plugin ships the portable `scoped-tests` skill at `tooling/phantom-ai-layer/skills/scoped-tests/` |
| **Validator** | Confirms the harness is wired correctly and catches drift | [`tooling/validate/validate_all.py`](tooling/validate/validate_all.py) |

---

## Maintenance

- **Keep CLAUDE.md lean.** The root holds repo-wide agent-behavior contracts and critical gotchas; architecture detail lives in the subdirectory files and `CODEBASE_MAP.md`. The root stays substantive because the pre-deploy gate, credential guardrail, data-source validation doctrine, documentation discipline and canonical-state discipline are load-bearing repo-wide.
- **Review cadence.** Review `CLAUDE.md`, skills and hooks every 3 to 6 months, and after any major model release: delete guidance the current model no longer needs, keep the contracts that are still load-bearing.
- **Stop hook.** It proposes `CLAUDE.md` edits while the session context is fresh; a maintainer reviews the draft.
- **Validator.** Run it after any AI Layer change, locally or from CI, to catch drift.
- **Ownership.** The project maintainers own `tooling/`, `.claude/` and the `CLAUDE.md` hierarchy. The plugin is the distribution mechanism: a new repo or contributor installs it once and gets the baseline layer.

---

## Runtime versus coding-agent layer

Phantom is itself an agentic platform, so several of these concepts exist twice: once in the product's runtime and once in the contributor tooling.

| Concept | Phantom runtime (the product) | Coding-agent layer (this AI Layer) |
|---|---|---|
| Skills | `bundles/spark/skills/`, used by the chat agent | `.claude/skills/`, used by Claude Code when editing the repo |
| Hooks | The hooks framework (settings/hooks page), fired on chat events | `.claude/hooks/`, fired on Claude Code session events |
| Subagents | The `/agents` page, runtime agent definitions | `.claude/agents/phantom-explorer.md`, a read-only mapper for coding sessions |
| MCP server | The embedded MCP at `bundles/spark/mcp/`, which drives the chat agent | `tooling/mcp/codebase_search.py`, symbol search for coding sessions |
| Plugin marketplace | The connector marketplace at `/connectors` and `marketplace.db` | `tooling/.claude-plugin/marketplace.json`, coding-agent plugins |

The AI Layer does not replace Phantom's runtime documentation (`/help/architecture`, `/help/user`, `journeys.ts`). Those are operator-facing; the AI Layer is contributor-facing.

---

## Validation

```bash
python tooling/validate/validate_all.py
```

The validator checks that:
- the `CLAUDE.md` hierarchy exists (root plus subdirectory files)
- `.claudeignore` excludes the baked catalog
- `.claude/settings.json` is valid JSON with the expected schema
- `.claude/agents/phantom-explorer.md` has no write tools
- all hooks compile
- all skills have `paths:` frontmatter
- `.mcp.json` references a valid script and `tooling/mcp/codebase_search.py` initializes and answers a stdio handshake
- the plugin marketplace is well formed and the plugin payload matches the repo copies by SHA
- pyright is configured

Wire the validator into your own CI if you want it to fail a build on drift.
