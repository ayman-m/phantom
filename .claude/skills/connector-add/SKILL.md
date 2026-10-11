---
name: connector-add
description: >-
  Use when adding or modifying a connector under bundles/spark/connectors. Walks
  the 5-step authoring pattern + catalog/credential boundary check + import-style
  discipline so the new connector follows Phantom's conventions.
paths:
  - bundles/spark/connectors/**
  - phantom-connector-runtime/**
---

# Adding a connector

Activates for work in `bundles/spark/connectors/<id>/` or `phantom-connector-runtime/`. Follow these steps in order.

## 1. `connector.yaml`

Declares the connector's metadata, runtime style, schema, tool list, config fields. Validates against `bundles/spark/connectors/connector.schema.json` at boot AND at upload time. Required keys: `id`, `name`, `version`, `tools`, `runtimeMapping.style: container`, `image`.

The `image` field is the OCI reference to the operator's pre-published connector container — `ghcr.io/<org>/<repo>:vX.Y.Z` for bundle connectors, any registry phantom-updater can pull from for user uploads.

## 2. `src/connector.py` — the entry point

Inherits from the `phantom-connector-runtime` base (`../../../phantom-connector-runtime/`). Each tool is one method.

**Import-style discipline**: use `from src.X import Y` (with `src.` prefix), NOT `from usecase.X import Y`. The latter only resolves with a specific PYTHONPATH that production deployments don't always have. Mixed import styles cause a recurring family of bugs.

## 3. Per-tool implementation files

`src/<tool>.py`. Each public tool function gets its own module. Docstring with **Args section + concrete example payload** — the agent picks fields by reading the docstring, not just the signature.

## 4. Tests

`tests/` — connector-local pytest suite. Run with `python3 -m pytest -x` from the connector's directory.

## 5. Dockerfile

`FROM ghcr.io/ayman-m/phantom-connector-runtime-oss:latest`. The release pipeline builds + tags each connector image at release time.

## Catalog vs credential boundary check (MANDATORY)

Before merging, ask BOTH questions about every tool the connector exposes:

1. **Does this tool read or write a SecretStore value?** If yes → REST-only at `bundles/spark/mcp/src/api/<resource>.py`, NEVER `mcp.tool()`-registered. The agent never gets a handle to credentials.
2. **Does this tool mutate catalog metadata (install state, schemas, registry membership)?** If yes AND #1 is no → safe to `mcp.tool()`-register as agent-callable.

A tool can only be on the catalog side if #1 is NO AND #2 is YES. If both are YES, split the tool — credential half stays REST-only, catalog half becomes agent-callable. See root CLAUDE.md § Agent credential guardrail.

## Connector-system bug-family audit

After fixing any bug in a connector file, audit sibling connectors for the same pattern:

1. Identify the bug as a `grep` expression (e.g. `from usecase\.` for the import-style bug).
2. Run across `bundles/spark/connectors/*/src/` + `bundles/spark/mcp/src/` + `phantom-connector-runtime/runtime/`.
3. For each hit, fix in the same release OR document the gap inline with a code comment. The fix isn't done until the grep returns no hits or every remaining hit has a documented reason.

## After the build

- Update `bundles/spark/connectors/CLAUDE.md` if the connector introduces a new pattern.
- Add a journey entry in `mcp/agent/lib/journeys.ts` if the connector adds an operator-facing flow.
- Update `/help/architecture` (`#connector-containers`) if the connector's deployment topology is non-standard.

See also: [bundles/spark/connectors/CLAUDE.md](../../../bundles/spark/connectors/CLAUDE.md) for local conventions.
