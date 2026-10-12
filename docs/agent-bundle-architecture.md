# Phantom Agent Bundle Architecture

Phantom is packaged as a portable agent product that can be imported into an agentic orchestration platform or launched standalone.

There are two compatible bundle surfaces:

- `bundles/spark/` is the Spark-compatible projection that follows the `spark-agents` schema v1.1 shape: `manifest.yaml`, `prompts/`, `skills/`, `kbs/`, and A2UI v0.8 surfaces.
- `bundles/phantom-agent.bundle.yaml` is the compose-native implementation bundle that knows how to run the current Phantom service stack: `phantom`, `phantom-mcp`, `phantom-agent`, and `caldera`.

The Spark bundle is the import contract for Spark-style orchestration. The compose bundle is the current standalone implementation path until the generic Spark runtime can host Phantom's MCP and service dependencies directly.

## Connector Resolution

Phantom follows the Spark bundle standard by declaring external services as `dependencies` and `instances` in `bundles/spark/manifest.yaml`.

- In standalone mode, XSIAM, Caldera, Xlog, and Phantom services are assumed to be running outside the agent. Operators provide connection settings such as `mcpUrl`, `calderaUrl`, `xsiamPapiUrl`, `webhookEndpoint`, `xlogEndpoint`, and `defaultLogDestination`, plus secret bindings for the declared secret paths.
- In Spark platform mode, Spark materializes the same connector declarations through connector-manager. The agent uses the same tool names and instance names, but the platform owns connector lifecycle, credentials, routing, and shared state.
- The `connectorResolution: auto` setting means "prefer Spark-managed connectors when attached to Spark; otherwise use standalone endpoint bindings."

This keeps the Phantom bundle portable without embedding XSIAM, Caldera, or log collector services inside the agent runtime.

## Diagram Mapping

| Spark diagram group | Phantom equivalent | Limitations |
|---|---|---|
| Identity and config | `bundles/spark/manifest.yaml`, compose service names, repo metadata, UI auth, MCP token | Cosign signing still uses placeholder metadata |
| Cognitive layer | Spark model requirements, persistent sessions, bundled prompt, Vertex/Gemini orchestration | No full `AgentEnvironment` adapter for Phantom services |
| Tool surface | FastMCP tools declared in Spark `tools.allow`, curated `bundles/tool-catalog.yaml`, generated `tool-snapshot.json` | No Spark connector-manager adapter |
| Memory | Spark memory declaration plus SQLite `/data/phantom.db`, MCP skills volume, Caldera volumes, optional state export/import | No Spark-native state materialization |
| Knowledge bases | Spark `kbs/phantom-soc`, MCP skills, XQL resources, scenarios | Scenario-to-KB generation is limited to the bundled scenarios |
| Run state | Persistent simulations, workers, validations, artifacts | Restore/rebind workflows for imported bundles |
| Integration surface | Spark connector declarations for Phantom MCP plus optional Caldera MCP, XSIAM MCP, and Xlog MCP instances; MCP/REST/GraphQL endpoints | Marketplace connector packages are not part of the bundle |
| UI bundle | Spark A2UI v0.8 chat/settings/activity surfaces (plus a `setup` surface that is not rendered: the first-run setup page was removed) plus current Phantom Next.js renderer | The Spark A2UI renderer is not implemented here; the Phantom Next.js renderer is used |
| Secrets | Spark `requiredSecrets`, `secret-bindings.example.yaml`, generated `.env.secret-refs`, optional file/HTTP provider binding | No Infisical/platform adapter |
| Observability | Spark observability metrics/events plus Compose healthchecks, smoke tests, and `observability.contract.yaml` | No OpenTelemetry instrumentation |

## Bundle Objective

The import artifact should make Phantom understandable to an orchestration platform without reading the repository:

1. Verify bundle integrity.
2. Discover required Docker images and optional included image archives.
3. Materialize the agent runtime.
4. Rebind secrets from the target platform secret provider.
5. Register MCP, REST, GraphQL, UI, and webhook interfaces.
6. Restore persistent memory/state when included.
7. Run standalone when no orchestration platform is present.
8. Render the agent UI from A2UI JSON using either the platform renderer or Phantom's standalone renderer.

## Bundle Shape

The Spark-compatible bundle root is `bundles/spark/`.

The compose-native canonical file is `bundles/phantom-agent.bundle.yaml`.

The YAML is intentionally secret-free. It can reference:

- Docker image names/tags and local artifact paths.
- Secret names such as `MCP_TOKEN` or `GOOGLE_APPLICATION_CREDENTIALS`.
- Volume names and restore modes.
- Interface definitions and health probes.
- Tool groups and package capabilities.
- A2UI manifest, component catalog, surfaces, event schema, and data model schema.

For air-gapped or no-registry imports, the export script packages Docker images as tar archives beside the YAML. The YAML remains the import contract and points at those image archive paths. Embedding full image bytes directly into YAML is possible but not recommended because it makes the file huge and hard to sign or diff.

## Bundle Capabilities

1. **Bundle content validation**
   - `tooling/validate/validate_all.py` validates the bundled data sources, connector tool declarations and plugin payload; `scripts/validate_spark_bundle.py` validates the Spark bundle.

2. **Tool catalog snapshot**
   - A curated tool catalog and allow/deny policy file define which MCP tools the agent may call.
   - Export writes the live MCP tool names, descriptions and Gemini-compatible sanitized schemas into `tool-snapshot.json`.
   - Export validates snapshot drift against the curated allow/deny policy.

3. **State export and import**
   - Export optionally copies SQLite, MCP skills and Caldera state from running containers when `INCLUDE_STATE=1`.
   - Import restores state artifacts into the target Docker volumes when `RESTORE_STATE=1`.
   - The UI exposes agent bundle readiness and platform health probes.

4. **Secrets rebinding**
   - A rebinding map translates Phantom env vars into target orchestration secret references.
   - Import materializes `.env.secret-refs` with provider references, never raw values.
   - An optional file/HTTP provider adapter registers references with a target provider when `BIND_SECRET_PROVIDER=1`.

5. **Image packaging**
   - Export saves `phantom:local`, `phantom-mcp:local`, `phantom-agent:local` and `caldera:local` as local image archives when requested.
   - SHA-256 checksums are recorded in the bundle output.

6. **Orchestrator interface**
   - Lifecycle commands cover install, start, stop, restart, status, health, logs and export.
   - Next.js runtime endpoints expose the manifest, health, guided workflows and report proxying under `/api/agent/*`.
   - The A2UI manifest, catalog and JSONL surfaces ship in the bundle as files. The current agent app serves no `/api/a2ui/*` endpoints.

7. **A2UI portable UI contract**
   - The bundle includes `a2ui/manifest.json`, `a2ui/catalogs/phantom-ui.v0.1.json`, surface JSONL files, a data model schema and an event schema.
   - Bundle metadata declares A2UI as the importable UI contract and keeps `phantom-agent` as the standalone renderer.
   - The A2UI `setup` surface and its `phantom.setup.save` event describe the first-run setup page, which was removed; nothing renders or handles them.

8. **First login (no setup page)**
   - There is no first-run setup page. The installer (or your `.env`) supplies `PHANTOM_DEFAULT_ADMIN_PASSWORD`; the agent seeds the `admin` account from it on a fresh volume and the UI asks you to change it at `/profile`.
   - Model provider credentials (Google service-account JSON or Gemini API key) are added at `/providers`, and each connector's URL and secrets at `/connectors`. They are stored in the ProviderStore, InstanceStore and SecretStore under `/app/data`, not in files under `.phantom-agent/`.
   - Downstream XSIAM, Xlog and Caldera service secrets stay with their connector instances.

9. **Spark-compatible bundle projection**
   - `bundles/spark/manifest.yaml` follows Spark schema v1.1.
   - The Spark bundle includes `prompts/`, `skills/`, `kbs/` and A2UI v0.8 UI surfaces.
   - Validation and export helpers are `scripts/validate_spark_bundle.py` and `scripts/export_spark_agent_bundle.sh`.

10. **Signature and provenance**
    - Export produces `bundle-manifest.json`, `checksums.sha256` and an optional `bundle-signature.json` using HMAC-SHA256.

## Known Limitations

- No schema validator for `phantom.agentic/v1alpha1` bundle manifests yet.
- No policy editor for allow/deny changes on the platform side.
- Importing state over existing target volumes has no confirmation flow in the UI or orchestrator.
- No first-class secret adapters for the target orchestration platform or Infisical (the file/HTTP provider adapter is the supported path).
- Phantom service adapters for the generic Spark runtime (so it can execute the declared tools directly) and the mapping of Phantom A2UI catalog components to the target platform's renderer are not implemented; the standalone `phantom-agent` renderer is the supported path.
- Signing is HMAC-SHA256; cosign-style attestation or platform-native signing is not implemented.
- No callback/webhook declarations or direct MCP invocation endpoints with policy enforcement.

## Bundle Lifecycle

### Bundle contract

- `bundles/phantom-agent.bundle.yaml` describes the stack.
- A remote-side export script packages the manifest, the Compose file and the local Docker images.
- Secret-bearing volumes, such as Caldera `conf`, are kept out of state exports.

### Runtime import

- An import/materialize script prepares target hosts: it loads image archives, generates an env template, and optionally restores volumes.
- Target secret bindings are applied from a template; provider-reference materialization and optional file/HTTP provider registration are supported.

### Agent orchestrator API

- REST endpoints expose lifecycle and package metadata: runtime manifest, health, workflow and report endpoints.
- A readiness panel in the UI shows bundle state; the export itself is triggered from the lifecycle script.

### Signed product bundle

- Export generates checksums and optional HMAC signatures for the bundle metadata.
- Import verifies the checksum and, when present, the signature before loading.

## Connector Runtime Model

Every connector instance runs as its own container (`phantom-connector-<id>:<version>`, inheriting from `phantom-connector-runtime`). The agent's MCP acts as a routing proxy: it forwards `tools/call` over MCP-over-HTTP to the connector container's own MCP server (FastMCP on port 9000 by default). See `docs/spec-per-instance-connector-containers.md` for the architectural rationale and design decisions.

Lifecycle is managed by phantom-updater's endpoints: `POST /api/v1/connectors/<id>/instances/<name>/{start,stop,restart}` and `GET .../status`. Each `start` pulls the image (with retry/backoff for offline deploys), launches the container on the Compose network with `phantom_mcp_data` mounted read-only at `/app/data`, and notifies the agent via `PUT /api/v1/instances/<id>/container_url` to update the routing entry the loader reads at the next tool call.

Properties:

- Latency: ~10-30 ms per call (HTTP roundtrip plus MCP handshake on the local Docker network).
- Resource overhead: ~50-100 MB RAM per container, idle CPU.
- Crash scope: a connector bug restarts only that container via `restart: unless-stopped`; the agent is unaffected.
- Dependency footprint: each connector's dependencies live in its own image, so the agent image stays lean.
- Isolation: each container has its own FastMCP server, its own contextvar state and its own filesystem.
- Third-party connectors: anyone can ship a Phantom connector as a standalone MCP-server container; no monorepo change is required.

### Writing a new connector

See `bundles/spark/connectors/_runtime/README.md` for the runtime contract and a working reference skeleton with `Dockerfile`, `connector.yaml` and one demo tool.
