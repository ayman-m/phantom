---
name: mcp-tool-add
description: >-
  Use when adding or modifying an MCP tool in the embedded Python server. Walks
  the registration pattern, the credential-guardrail check, the docstring
  discipline that the agent depends on, and the cross-file linkage that
  prevents silent capability gaps.
paths:
  - bundles/spark/mcp/src/usecase/builtin_components/**
  - bundles/spark/mcp/src/api/**
  - bundles/spark/mcp/src/main.py
---

# Adding an MCP tool

Activates for work in `bundles/spark/mcp/src/usecase/builtin_components/` or `bundles/spark/mcp/src/api/`. Follow these steps in order.

## 1. Credential-guardrail check (BEFORE writing code)

Ask BOTH questions:

1. **Does this tool read or write a SecretStore value?** (UI password, provider creds, per-instance secrets, API keys plaintext.) If YES → REST-only at `src/api/<resource>.py`, NEVER `mcp.tool()`-registered. The agent never gets a handle to credentials. See root CLAUDE.md § Agent credential guardrail.
2. **Does this tool mutate catalog metadata?** (Install state, schemas, registry membership.) If YES AND #1 is NO → safe to `mcp.tool()`-register as agent-callable.

A tool can only be on the catalog side if #1 is NO AND #2 is YES. If both are YES, split the tool.

## 2. Implement under `src/usecase/builtin_components/<module>.py`

Each module groups related tools. Examples: `data_faker`, `workers`, `scenarios`, `xsiam_tools`, `caldera_tools`, `simulation_skills`, `skills_crud`, `observables_catalog`, `field_info`, `job_scheduler`, `marketplace`, `secrets_store`, `self_mod_tools`.

```python
async def my_tool(arg1: str, arg2: int = 10) -> dict[str, Any]:
    """One-line summary that the agent reads when deciding to call this tool.

    Longer description. Explain when the agent should pick this tool over
    alternatives, with concrete trigger phrases ("set when the operator says
    'don't ask me each time'").

    Args:
      arg1: What it does, what shape, default behavior.
      arg2: When to set it. If destructive, flag here.

    Returns:
      {"ok": bool, "key": value, ...} — describe the envelope.

    Example payload:
      {"arg1": "fortigate", "arg2": 50}
    """
    ...
```

## 3. Config goes through pydantic-settings, NEVER `os.environ`

If the tool needs an env var, add a field to `src/config/config.py` with `validation_alias`. Raw `os.environ` calls are forbidden — they bypass type validation + the agent has no way to introspect the value's source.

## 4. Register in `src/main.py`

```python
mcp.tool()(my_module.my_tool)
```

One line per tool, in the registration block inside `async_main`.

## 5. Tests

Add to `tests/test_<module>.py`. Run with:

```bash
cd bundles/spark/mcp
PYTHONPATH=$PWD/src python3 -m pytest tests/test_<module>.py -x
```

The `PYTHONPATH=$PWD/src` is REQUIRED — half the test files use `from usecase.X import Y` which needs `src/` on the path.

## 6. UI-form sync discipline

If this tool corresponds to a UI form on a system-management page (`/jobs/new`, `/providers/new`, `/instances/new`, `/skills/new`, `/settings/`, `/profile/`, `/settings/hooks/*`), the docstring MUST be updated when the UI changes.

The agent picks fields by reading the docstring, not just the signature. If the UI exposes a field that the docstring doesn't mention in Args + an example payload, the agent will never set it. This is a SILENT CAPABILITY GAP — this rule prevents it.

Audit shape:
- Identify the matching UI form field.
- Confirm the field flows through to the backend store (otherwise it's a dead field, separate problem).
- Add to docstring Args: parameter name, type, default, what it does, concrete trigger phrases.
- For discriminated-union actions, update the example shapes.
- For destructive parameters, flag in the docstring.

## 7. After the build

- Update `bundles/spark/mcp/CLAUDE.md` if you introduced a new convention.
- If the tool surfaces a new operator capability, add a journey entry in `mcp/agent/lib/journeys.ts`.
- If the tool affects observability, extend the relevant `mcp/agent/app/observability/<sub>/page.tsx`.

See also: [bundles/spark/mcp/CLAUDE.md](../../../bundles/spark/mcp/CLAUDE.md) for local conventions.
