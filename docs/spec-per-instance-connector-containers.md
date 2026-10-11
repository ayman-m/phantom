# Per-instance connector containers

Every Phantom connector instance runs in its own container. The agent's embedded MCP does not execute connector code; it routes each `tools/call` to the MCP server inside the right connector container. This document describes the topology, the design decisions behind it and the contract a connector container must meet.

## Why containers

Running connector code in the agent process (as importable Python modules) has four costs that grow with every connector:

- **Dependency footprint.** Every connector adds its dependencies to the agent image (a browser automation stack, cloud auth libraries, PDF extraction). The image grows monotonically.
- **Crash blast radius.** A buggy connector or runaway tool call takes down the agent: the chat UI, the embedded MCP and every other connector.
- **Cross-instance state.** Two instances of the same connector share one Python process, module globals and caches (the web connector keeps page registries keyed by session id).
- **No third-party story.** Adding a connector would mean writing Python in the Phantom repository and shipping it bundled.

One container per instance removes all four, at the price of an MCP round trip per call.

## Topology

```
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ phantom-agent container          │    │ phantom-connector-xlog-primary   │
│                                  │    │ (one container per instance)     │
│  Embedded MCP (port 8080)        │    │                                  │
│   ├─ Routing table:              │←──→│  FastMCP (port 9000)             │
│   │   xlog/* → xlog-primary:9000 │MCP │   ├─ tools/list returns xlog/*   │
│   │   web/*  → web-primary:9000  │    │   └─ tools/call executes xlog    │
│   │   ...                        │    │                                  │
│   └─ Per call: forward to the    │    │  Outbound to the xlog backend:   │
│      connector instance's MCP    │    │   POST http://xlog:8000/...      │
└──────────────────────────────────┘    └──────────────────────────────────┘
        │
        ↓
┌──────────────────────────────────┐
│ phantom-connector-web-primary    │
│ (FastMCP + playwright client)    │ ←—→ phantom-browser:9222 (CDP)
└──────────────────────────────────┘
```

- Connector code is an MCP server running in its own container.
- One container per instance, not per connector. Two web instances are two containers, each with its own browser context registry.
- Per-instance configuration and secrets come from the SecretStore (mounted read-only) plus an `INSTANCE_ID` environment variable.
- Per-call latency is an MCP round trip over the local Docker network (about 10-30 ms).
- Resource overhead is about 50-100 MB RAM per container, plus idle CPU.
- A connector bug restarts only that instance's container; the agent is unaffected.
- Agent and connectors talk MCP-over-HTTP.

## Design decisions

### Lifecycle: persistent per instance

One long-lived container per connector instance, alive as long as the instance exists in the instance store. This maps onto the operator's mental model (an instance is a running thing they manage). Rejected: a cold start per call (200-800 ms of Docker start-up dominates a chat turn that makes 5-10 tool calls), a warm pool (pool management for no extra warmth), and one shared container per connector (brings back cross-instance state bleed).

### Protocol: MCP-over-HTTP

Each connector container runs a FastMCP server on a known port, and the agent's embedded MCP acts as a proxy: any `tools/call` named `<connector>/<tool>` is looked up in the routing table and forwarded. The agent already speaks MCP, so the proxy is short; the connector contract becomes "a Phantom connector is an MCP server", which is language-agnostic and testable with any MCP client; streaming and capability negotiation (`tools/list`) come for free. Rejected: gRPC (protobuf tooling for no real gain), Unix sockets with custom framing (hard across container boundaries), plain REST (no streaming or negotiation).

### Hosting: Docker on the Compose network

Connector containers run on the same Docker daemon and the same Compose network as `phantom-agent`, and `phantom-updater` (which already has the Docker socket) manages their lifecycle. Phantom deploys as Docker Compose on a single host, so Kubernetes or a serverless platform would be out of model, and Compose cannot declare services dynamically. The accepted trade-off is a single-host scaling limit; per-container memory limits cap the blast radius.

### Images: one per connector

Each connector ships as `<registry>/phantom-connector-<id>:<version>`, built `FROM phantom-connector-runtime:<version>`. The runtime base image holds the shared plumbing: FastMCP, the SecretStore client, the per-instance config contextvar and the audit forwarder. Each connector image adds its own source and dependencies, so the agent image never carries them, and each image can be pulled independently by third parties. Rejected: one base image with source mounted at run time (breaks the immutable-artifact principle) and an image per instance (per-instance configuration is not per-instance code).

### Configuration delivery: SecretStore mount

A container starts with the `PHANTOM_SECRET_KEK` key, the SecretStore volume mounted read-only, and `INSTANCE_ID`. At boot the connector reads its instance configuration and secrets with the same library the agent uses, so rotating a secret is the same operation as before and nothing is exposed through `docker inspect`. Rejected: environment variables only (secrets visible to anyone who can inspect the container) and secrets in the MCP handshake (extra protocol surface).

### Lifecycle management: phantom-updater

`phantom-updater` exposes the connector lifecycle:

- `POST /api/v1/connectors/<id>/instances/<name>/start` pulls the image, runs the container on the Compose network and returns its address.
- `POST .../stop` stops and removes the container.
- `GET .../status` reports health, restart count and resource usage.
- `POST .../restart` forces a restart of a wedged container.

After a start, the updater notifies the agent with `PUT /api/v1/instances/<id>/container_url`, which updates the routing entry and reloads the tool registry. The updater honours `PHANTOM_TLS_VERIFY` for that callback, as the agent does for its own loopback calls.

Container names are `phantom-connector-<id>-<instance-name>` (for example `phantom-connector-xlog-primary`) and the agent reaches them at `http://phantom-connector-<id>-<instance-name>:9000/mcp`.

### Failure modes

- **Crash.** Docker `restart: unless-stopped`. The proxy reconnects on the next call (one retry, then the error surfaces to chat) and the audit log records the crash.
- **Hang.** A per-call timeout in the agent proxy (60 s by default, configurable). After the timeout the agent surfaces the error and the updater can kill and restart the container.
- **Out of memory.** A per-container Docker memory limit (256 MB by default, configurable per connector with `runtime.memory` in `connector.yaml`). The container restarts and the agent retries.
- **Long-running tools.** Any tool that can exceed the per-call timeout must be async-capable: return a job id immediately and let the agent poll (for example `xlog/create_data_worker` with `duration_seconds: 0`).
- **Image pull failure** (first start on an offline deploy). The updater retries with backoff and surfaces an actionable message in the operator UI.

### Observability

Container stdout and stderr go to the normal Docker log stream (`docker logs phantom-connector-xlog-primary`). Connector audit events are posted to the agent's audit endpoint over HTTP, so there is one audit pipeline and one durable store. CPU, memory and network are available through `docker stats`.

## The runtime contract

A connector container must:

1. Start a FastMCP server on port 9000 (overridable with an environment variable).
2. Register its tools at boot under the bare names from `connector.yaml`'s `spec.tools[]` (the container provides namespace isolation, so no `functionPrefix` is needed).
3. Read its per-instance configuration from the SecretStore at boot.
4. Implement `tools/list` and `tools/call` per the MCP specification (FastMCP derives both from the registered tools).
5. Serve a `/health` HTTP endpoint that returns 200 when ready. Docker healthchecks and the updater's readiness checks use it.
6. Optionally forward audit events with `POST <agent-audit-url>` for tools that want durable audit rows.
7. Handle SIGTERM cleanly: drain in-flight calls, then exit.

That is the entire contract; everything else is connector-specific.

## Implementation notes

- **Flat tool arguments.** FastMCP derives each tool's JSON Schema from the function signature and rejects `**kwargs` callables. The agent-side proxy therefore synthesizes, for every container-style tool, a function whose signature mirrors the `args` declared in `connector.yaml` (one parameter per argument, optional arguments default to `None`, `None` values are dropped before forwarding). The `args` type map covers `string`, `integer`, `number`, `boolean`, `object` and `array`. Connector tool functions must use flat keyword parameters matching `connector.yaml`; `tooling/validate/validate_all.py` checks this.
- **Instance schema is shared.** The runtime reads instance rows from the same SQLite file as the agent's `InstanceStore` (`config_json` and `secrets_json` columns), so both sides must change together.
- **Routing reload.** The agent caches instance objects when it registers tools. A `container_url` change therefore triggers a tool-registry reload so the proxy closures see the new address (about 0.9 s, acceptable for an infrequent event).

## What stays the same

- **`connector.yaml` schema.** `configSchema`, `secretSlots`, `spec.tools[]` and `runtimeMapping` are unchanged; `runtimeMapping.style` is `"container"`.
- **Per-instance configuration and secrets.** Same keys and same SecretStore; only the reader differs (the connector container instead of the agent).
- **Approval gate.** Still enforced agent-side, where the chat session originates. Connector containers just execute what the proxied call asks.
- **Audit log.** One durable store in the agent; connector containers post to its endpoint.
- **Marketplace flow.** Install pulls the connector image into the local Docker cache; creating an instance provisions its container.
- **Bundle layout.** `bundles/spark/connectors/<id>/` holds `connector.yaml`, the source and a `Dockerfile` for the per-image build. `bundles/spark/connectors/_runtime/` is a reference skeleton.
