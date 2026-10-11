# Phantom Spark Agent Bundle (v1.2)

This directory is the Spark-compatible bundle for Phantom, conforming
to **agent-bundle schema v1.2** as defined in
[`ayman-m/spark-agents`](https://github.com/ayman-m/spark-agents/blob/main/docs/spec.md).

```
bundles/spark/
├── manifest.yaml                      schema 1.2 — declares connectors,
│                                      embedded MCP, setup-bound instances
├── prompts/system.md                  system prompt template
├── skills/                            markdown skill cards
├── kbs/xql-examples/                  bundled XQL example knowledge base
├── data-sources/                      bundled data-source catalog
├── destinations/                      log destination definitions
├── providers/vertex/                  model provider definition
├── plugins/                           plugin examples
├── mcp/                               embedded MCP server
│   ├── server.yaml
│   └── README.md
└── connectors/                        tool-providing connectors
    ├── caldera/                       adversary emulation — abilities,
    │                                  adversaries, operations, agents, facts
    ├── xsiam/                         XQL queries, cases, datasets,
    │                                  lookups, assets, issues
    ├── xlog/                          workers, scenarios, observables,
    │                                  validation, coverage
    ├── cortex-xdr/                    Cortex XDR public API
    ├── cortex-docs/                   public Cortex documentation search
    ├── cortex-content/                baked Cortex content-pack catalog
    ├── web/                           headless-browser fetch / interact
    ├── http-sender/                   synthetic events to an HTTP collector
    └── wec-sender/                    synthetic Windows events over WEC
```

## Connector model (v1.2)

The bundle follows the spec's split between two connector kinds:

- **Messaging connectors** (`manifest.yaml:messagingConnectors`) —
  Slack/Discord/Gmail-style services that route inbound chat to the
  agent. **Phantom uses none.** The agent is driven via its own UI, not
  inbound chat.

- **Tool-providing connectors** (`manifest.yaml:toolConnectors[]` +
  `connectors/<id>/connector.yaml`) — services the agent CALLS to do
  its work. Each connector lives entirely in this bundle (source under
  `connectors/<id>/src/`); the embedded MCP at `mcp/` aggregates their
  tool catalogs into one MCP endpoint the agent talks to.

## Per-connector summary

| Connector | Required at setup | Backing service |
|---|---|---|
| `xlog` | **Yes** (log generation is the agent's core capability) | The `xlog` compose service (GraphQL API) |
| `caldera` | No (agent degrades: no adversary emulation) | MITRE Caldera server (the `caldera` compose service) |
| `xsiam` | No (agent degrades: no detection validation) | Cortex XSIAM tenant via the public API (the operator's own, no in-cluster service) |
| `cortex-xdr` | No | Cortex XDR tenant via the public API (the operator's own) |
| `cortex-docs` | No | Public Cortex documentation site |
| `cortex-content` | No | Baked catalog shipped in the image |
| `web` | No | The `phantom-browser` sidecar (headless Chromium over CDP) |
| `http-sender` | No | The operator's own XSIAM HTTP Log Collector or Cribl endpoint |
| `wec-sender` | No | The operator's own Broker VM Windows Event Collector |

## Setup-bound instances

**No tool-connector instances are hardcoded in the manifest**.
Instead, `setup.bindsInstances[]` declares one template per
connector, and the runtime materializes one `connector_instances` row
per template when the operator submits the setup form. The form fields
each template references (e.g. `${setup.calderaBaseUrl}`,
`${setup.xsiamPapiUrl}`, `${setup.xlogApiToken}`) are rendered by the
standalone runtime from each connector.yaml's `configSchema` +
`secretSlots` — see spec v1.2 §7.5 mode resolution for the standalone
vs Spark-platform fork.

## Mode resolution (where the MCP runs)

Per spec §7.5, the same bundle behaves identically in both modes
**except** for who hosts the MCP and where instances are stored:

| | **Standalone** | **Spark-platform** |
|---|---|---|
| Embedded MCP | Spawned from `bundles/spark/mcp/` | NOT spawned — `connector-manager` MCP supersedes it |
| Tool connectors | Loaded into embedded MCP from `bundles/spark/connectors/<id>/` | For each entry: `gateway.PublishConnector` → admin approval → registered with `connector-manager` |
| Tool-connector instances | `data_root/instances.db` (from setup form) | Postgres `connector_instances` (from same form, server-side) |
| Setup UI | The Phantom agent's setup page | Spark workspace UI |
| Tool namespace seen by the agent | `caldera/*`, `xsiam/*`, `xlog/*` | Same |

The bundle owns its MCP runtime: the `phantom-mcp` Docker service
builds from `./bundles/spark/mcp/`, and connector-specific shared
infrastructure lives in each connector's `src/` (as `_factory.py`,
`_papi_client.py`, `_xql_enrichment.py`, `_graphql_client.py`). The
bundle is the deployment unit.

The compose-native bundle manifest at
[`bundles/phantom-agent.bundle.yaml`](../phantom-agent.bundle.yaml)
documents the compose deployment model and references these paths.

## References

- [Spark agent-bundle spec v1.2](https://github.com/ayman-m/spark-agents/blob/main/docs/spec.md)
- [Mode resolution (spec §7.5)](https://github.com/ayman-m/spark-agents/blob/main/docs/spec.md#75-mode-resolution)
- [Tool-connector schema (spec §7.4)](https://github.com/ayman-m/spark-agents/blob/main/docs/spec.md#74-tool-connector-schema-connectorsidconnectoryaml)
- Reference example bundle: [`examples/incident-triage/`](https://github.com/ayman-m/spark-agents/tree/main/examples/incident-triage)
- Upstream Spark connector schema source of truth:
  [`connector-manager/internal/mcp/pg_instance_store.go`](https://github.com/ayman-m/spark/blob/main/services/connector-manager/internal/mcp/pg_instance_store.go)
