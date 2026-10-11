# XQL Examples Knowledge Base

This directory is the bundled `xql-examples` knowledge base — one of the platform's bundled KBs declared in `bundles/spark/manifest.yaml:knowledge.bundled[]`. The runtime's `SqliteKnowledgeBase` (spec §6.10 standalone impl, see `bundles/spark/mcp/src/usecase/kb_store.py`) ingests every markdown file under `entries/`, embeds each entry's content + title via `text-embedding-004`, and serves semantic search via the runtime's built-in `knowledge_search` tool. The `xsiam` connector exposes a thin back-compat wrapper at `find_xql_examples_rag(intent, top_k)` that delegates here.

## Adding a new entry

Each entry is a single markdown file under `entries/` with YAML frontmatter validated against `schema.json`. Required fields: `id`, `title`, `category`. Optional fields: `dataset`, `tags`.

Filename convention: `<NNN>-<kebab-case-slug>.md`. `NNN` is a zero-padded sequence number — pick the next available; the schema validation is keyed on the `id` field, not the filename, so collisions in numbering are caught at boot.

```yaml
---
id: XQL-NNN-<short-slug>
title: <Human-readable title — describes the analyst intent, since the embedder includes this in the searchable content>
category: alert-mapping | detection | investigation | general
dataset: <xsiam dataset name, e.g. "xdr_data" or "panw_ngfw_traffic_raw">
tags:
  - <pipeline stages used: filter, comp, alter, dedup, sort, ...>
  - <free-form: xdr_data, network, causality, etc.>
---

# <Title>

**Dataset**: `<dataset name>`

\`\`\`sql
<the full XQL query — multi-line ok>
\`\`\`

## When to use

<one-paragraph description of the operator-facing use case>

## Variations

<numbered or bulleted list of common parameter changes — different time windows, alternative datasets, additional filters>

## Source (optional)

<one line: a vendor doc citation, or how the query was validated>
```

## Validation discipline

Entries fall into three confidence buckets:

1. **Validated** — the query was run against a real XDR/XSIAM tenant and returned correct results. A `## Source` section may say so, without naming a tenant or a person. The `## When to use` text can then state the use case with confidence.

2. **Vendor-documented** — the query is a documented pattern from Palo Alto Networks' official Cortex XQL / XDR Public API documentation (for example found through the `cortex-docs` connector). The `## Source` cites the vendor doc and notes "Validate against your tenant before relying." These cover well-established patterns.

3. **Pattern derived** — XQL patterns inferred from the connector tool descriptions, related queries in the corpus, or general SIEM hunting know-how. The `## Source` says "Pattern derived from..." and is explicit that the query should be validated before relying on it. Use this bucket sparingly.

Entries carry no author, requester, tenant or customer names, in the frontmatter, the body or the comments inside the query. Keep comments that explain the logic of the query; leave out comments that say who wrote it or for whom.

Don't add tenant-specific field names without redaction. If a query references a custom dataset only your tenant has, mark it as `(tenant-specific)` in the title.

## After adding entries

The `xql-examples` index is regenerated on agent boot when the runtime's KB store detects any entry file with a newer mtime than the indexed copy. No manual reindex command is required — restart the agent container (or wait for the next boot) and the new entries become searchable. The audit row recording the reindex appears in `/observability/events` with `audit_type=knowledge_indexed`.

To verify locally:

```bash
# After saving new entries, restart the agent container:
docker compose restart phantom-agent

# Then check that knowledge_search returns the new entry:
curl -s -X POST http://localhost:8080/api/v1/knowledge_search \
  -H "Authorization: Bearer $MCP_TOKEN" \
  -d '{"kb_name": "xql-examples", "query": "<a phrase from your new title>"}' \
  | jq '.data.results[] | {id, title}'
```

## Cross-references

- Schema: [`schema.json`](schema.json)
- Bundled KB declaration: `bundles/spark/manifest.yaml:knowledge.bundled[].xql-examples`
- Runtime: `bundles/spark/mcp/src/usecase/kb_store.py` (`SqliteKnowledgeBase`)
- Connector wrapper: `bundles/spark/connectors/xsiam/src/connector.py` (`xsiam_find_xql_examples_rag`)
- Related skills: `bundles/spark/mcp/skills/foundation/cortex_kb_search.md` (the agent's discipline for using the Cortex KB; pairs naturally with this XQL KB)
- Source legacy markdown (auto-derivation seed): `bundles/spark/mcp/resources/xql_examples.md`
