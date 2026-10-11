/**
 * Log destinations flow diagram.
 *
 * Visual companion for the /help/architecture#log-destinations section.
 *
 * What it shows:
 *   - The 4 layers a /log-destinations request flows through:
 *       Browser → Next.js proxy → embedded MCP → SQLite + SecretStore
 *   - The 3 MCP-side concerns:
 *       destination_types_loader (boot-time spec.yaml scan + validation),
 *       log_destinations_store (CRUD + WEBHOOK_ENDPOINT migration),
 *       destination_handler_registry (file-path import + probe/send dispatch)
 *   - The 4 storage / external surfaces the system touches:
 *       Type manifests (bundles/spark/destinations/<id>/),
 *       log_destinations.db SQLite store,
 *       SecretStore overlay (credential boundary),
 *       External destinations (XSIAM HTTPS / syslog UDP-TCP-TLS / Splunk HEC / webhook)
 *   - The MCP tools row (read-only — list, get) that returns "***" for
 *     every secret slot. Operator-write paths bypass MCP tools entirely
 *     and go through the REST endpoints.
 *   - The credential-boundary callout: secrets land in SecretStore,
 *     not in log_destinations.db (which only carries secret_refs JSON).
 *
 * Layout:
 *   - 4 horizontal lanes (Browser / Next.js / MCP / Storage+External)
 *   - MCP lane has 3 columns side-by-side; store is the hero box center
 *   - Storage lane has 4 boxes: type manifests, SQLite, SecretStore,
 *     external destinations
 *   - Send path (orange edge) flows from handler_registry down to
 *     external destinations, distinct from the CRUD path (operator blue)
 *
 * The diagram is intentionally destination-neutral on the external side:
 * XSIAM appears as one of four bundled types alongside syslog, webhook,
 * and Splunk HEC. Adding a new type is "ship one spec.yaml + one
 * handler.py" — same drop-in pattern as the connector marketplace.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES = DIAGRAM_THEME_CSS + `
.dgm-root .ld-types-shape {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-state-info);
  stroke-width: 2;
}
.dgm-root .ld-secret-shape {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-state-warn);
  stroke-width: 2;
}
.dgm-root .ld-external-shape {
  fill: var(--dgm-external-fill);
  stroke: var(--dgm-edge-external);
  stroke-width: 1.8;
}
.dgm-root .ld-handler-shape {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-state-success);
  stroke-width: 2;
}

.dgm-root .ld-types-text { fill: var(--dgm-state-info); }
.dgm-root .ld-secret-text { fill: var(--dgm-state-warn); }
.dgm-root .ld-external-text { fill: var(--dgm-edge-external); }
.dgm-root .ld-handler-text { fill: var(--dgm-state-success); }

.dgm-root .ld-row-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  fill: var(--dgm-text-muted);
}
.dgm-root .ld-boundary-pill {
  fill: var(--dgm-badge-bg);
  stroke: var(--dgm-state-warn);
  stroke-width: 1.4;
  stroke-dasharray: 4 3;
}
.dgm-root .ld-boundary-text {
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.1em;
  fill: var(--dgm-state-warn);
}
`;

export function LogDestinationsFlow() {
  return (
    <div className="dgm-root">
      <style>{STYLES}</style>
      <svg
        viewBox="0 0 1200 900"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Log destinations request flow — browser through Next.js proxy, embedded MCP store and handler registry, SQLite store + SecretStore overlay, and per-type handler dispatch to external destinations"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        {/* Title */}
        <text x="600" y="42" textAnchor="middle" className="title" fontSize="22">
          Log destinations request flow
        </text>
        <text x="600" y="68" textAnchor="middle" className="detail" fontSize="13">
          Browser → Next.js proxy → MCP (store + handler registry) → SQLite + SecretStore · Probe + Send dispatch through per-type handler
        </text>

        {/* Lane dividers + labels */}
        <line className="lane-line" x1="60" y1="120" x2="1140" y2="120" />
        <text x="74" y="113" className="lane-label">BROWSER</text>
        <line className="lane-line" x1="60" y1="260" x2="1140" y2="260" />
        <text x="74" y="253" className="lane-label">PHANTOM-AGENT · Next.js</text>
        <line className="lane-line" x1="60" y1="430" x2="1140" y2="430" />
        <text x="74" y="423" className="lane-label">PHANTOM-AGENT · embedded MCP (Python FastMCP)</text>
        <line className="lane-line" x1="60" y1="700" x2="1140" y2="700" />
        <text x="74" y="693" className="lane-label">CONTAINER FILESYSTEM + EXTERNAL</text>

        {/* ── Browser layer ───────────────────────────────────────── */}
        <rect x="380" y="140" width="440" height="92" rx="14" className="node-shape" />
        <text x="600" y="172" textAnchor="middle" className="node-title">/log-destinations page</text>
        <text x="600" y="194" textAnchor="middle" className="node-subtitle">React 19 · form-engine renders schema-driven CRUD</text>
        <text x="600" y="214" textAnchor="middle" className="node-detail-small">
          Create · Edit · Probe (Test) · Delete · Set default
        </text>

        {/* HTTPS edge browser → next.js */}
        <path className="edge operator" d="M 600 232 L 600 280" />
        <rect x="610" y="244" width="180" height="22" rx="5" className="edge-label-box" />
        <text x="700" y="259" textAnchor="middle" className="edge-label-text-small">HTTPS · cookie session</text>

        {/* ── Next.js layer (proxy routes) ────────────────────────── */}
        <rect x="160" y="280" width="880" height="120" rx="14" className="node-shape" />
        <text x="600" y="310" textAnchor="middle" className="node-title-small">/api/agent/log-destinations/* — Next.js route handlers (lib/mcp-proxy.ts)</text>

        <text x="200" y="338" className="ld-row-label">READ</text>
        <text x="200" y="358" className="node-detail-small mono">GET  /</text>
        <text x="200" y="376" className="node-detail-small mono">GET  /{`{id}`}</text>

        <text x="430" y="338" className="ld-row-label">CRUD</text>
        <text x="430" y="358" className="node-detail-small mono">POST   / (create)</text>
        <text x="430" y="376" className="node-detail-small mono">PATCH  /{`{id}`} (edit)</text>
        <text x="430" y="394" className="node-detail-small mono">DELETE /{`{id}`}</text>

        <text x="720" y="338" className="ld-row-label">PROBE + DEFAULT</text>
        <text x="720" y="358" className="node-detail-small mono">POST /{`{id}`}/probe</text>
        <text x="720" y="376" className="node-detail-small mono">POST /{`{id}`}/set-default</text>
        <text x="720" y="394" className="node-detail-small muted">— is_default exclusive flip</text>

        {/* Bearer-auth edge */}
        <path className="edge muted" d="M 600 400 L 600 450" />
        <rect x="608" y="412" width="220" height="22" rx="5" className="edge-label-box" />
        <text x="718" y="427" textAnchor="middle" className="edge-label-text-small">
          Bearer MCP_TOKEN · HTTPS:8080
        </text>

        {/* ── MCP layer ───────────────────────────────────────────── */}
        {/* types_loader (left) */}
        <rect x="80" y="450" width="280" height="170" rx="14" className="node-shape" />
        <text x="220" y="482" textAnchor="middle" className="node-title-small">destination_types_loader</text>
        <text x="220" y="504" textAnchor="middle" className="node-subtitle" style={{fontSize: 11}}>usecase/destination_types_loader.py</text>
        <text x="100" y="532" className="ld-row-label">AT BOOT</text>
        <text x="100" y="552" className="node-detail-small">scans bundles/spark/destinations/</text>
        <text x="100" y="570" className="node-detail-small">validates each spec.yaml against</text>
        <text x="100" y="586" className="node-detail-small mono">destination.schema.json</text>
        <text x="100" y="604" className="node-detail-small muted">missing/invalid spec → boot fail</text>

        {/* log_destinations_store (center, hero) */}
        <rect x="380" y="450" width="440" height="170" rx="14" className="node-shape hero" />
        <rect className="hero-halo" x="360" y="438" width="480" height="200" rx="22" opacity="0.4" />
        <text x="600" y="482" textAnchor="middle" className="node-title">log_destinations_store</text>
        <text x="600" y="504" textAnchor="middle" className="node-subtitle" style={{fontSize: 11}}>usecase/log_destinations_store.py</text>

        <text x="400" y="532" className="ld-row-label">CRUD + STATE</text>
        <text x="400" y="552" className="node-detail-small">create / update / delete</text>
        <text x="400" y="570" className="node-detail-small">set-default (exclusive)</text>
        <text x="400" y="588" className="node-detail-small mono">+ probe-history bookkeeping</text>

        <text x="620" y="532" className="ld-row-label">BOOT MIGRATION</text>
        <text x="620" y="552" className="node-detail-small">WEBHOOK_ENDPOINT env →</text>
        <text x="620" y="570" className="node-detail-small mono">xsiam_http &quot;XSIAM Default&quot;</text>
        <text x="620" y="588" className="node-detail-small muted">idempotent · runs once</text>

        {/* handler_registry (right) */}
        <rect x="840" y="450" width="280" height="170" rx="14" className="ld-handler-shape" />
        <text x="980" y="482" textAnchor="middle" className="ld-handler-text" style={{fontSize: 18, fontWeight: 800}}>
          handler_registry
        </text>
        <text x="980" y="504" textAnchor="middle" className="node-subtitle" style={{fontSize: 11}}>destination_handler_registry.py</text>

        <text x="860" y="532" className="ld-row-label">DISPATCH</text>
        <text x="860" y="552" className="node-detail-small mono">probe(merged_config)</text>
        <text x="860" y="570" className="node-detail-small mono">send(merged_config, records)</text>
        <text x="860" y="588" className="node-detail-small muted">file-path import per type</text>
        <text x="860" y="604" className="node-detail-small muted">missing handler → boot fail</text>

        {/* Credential boundary pill */}
        <rect x="900" y="430" width="220" height="22" rx="11" className="ld-boundary-pill" />
        <text x="1010" y="445" textAnchor="middle" className="ld-boundary-text">CREDENTIAL BOUNDARY</text>

        {/* MCP-internal edges between the 3 boxes */}
        <path className="edge compose" d="M 360 535 L 380 535" />
        <path className="edge compose" d="M 820 535 L 840 535" />

        {/* MCP tools row (below MCP boxes) */}
        <rect x="160" y="640" width="880" height="44" rx="10" className="node-shape" />
        <text x="600" y="660" textAnchor="middle" className="ld-row-label">MCP TOOLS (agent-callable, read-only)</text>
        <text x="600" y="676" textAnchor="middle" className="node-detail-small">
          <tspan className="mono">log_destinations_list(type_id?)</tspan>{" "}·{" "}
          <tspan className="mono">log_destinations_get(id_or_name)</tspan>{" "}— both return{" "}
          <tspan className="mono ld-secret-text">&quot;***&quot;</tspan>{" "}sentinels for every secret slot
        </text>

        {/* Store → MCP tools (the tools read from store) */}
        <path className="edge muted" d="M 600 620 L 600 640" />

        {/* ── Storage / external layer ────────────────────────────── */}
        {/* Type manifests (blue) */}
        <rect x="80" y="720" width="240" height="160" rx="14" className="ld-types-shape" />
        <text x="200" y="750" textAnchor="middle" className="ld-types-text" style={{fontSize: 16, fontWeight: 800}}>
          Type manifests
        </text>
        <text x="200" y="770" textAnchor="middle" className="node-subtitle" style={{fontSize: 10.5}}>
          bundles/spark/destinations/
        </text>
        <text x="100" y="796" className="node-detail-small mono">syslog/</text>
        <text x="100" y="814" className="node-detail-small mono">webhook/</text>
        <text x="100" y="832" className="node-detail-small mono">xsiam_http/</text>
        <text x="100" y="850" className="node-detail-small mono">splunk_hec/</text>
        <text x="200" y="870" textAnchor="middle" className="node-detail-small muted">spec.yaml + handler.py</text>

        {/* log_destinations.db (sink) */}
        <rect x="340" y="720" width="240" height="160" rx="14" className="node-shape" />
        <text x="460" y="750" textAnchor="middle" className="node-title-small">log_destinations.db</text>
        <text x="460" y="770" textAnchor="middle" className="node-subtitle" style={{fontSize: 10.5}}>
          /app/data/
        </text>
        <text x="360" y="796" className="node-detail-small">id · name · type_id</text>
        <text x="360" y="814" className="node-detail-small mono">config_json</text>
        <text x="360" y="832" className="node-detail-small mono">secret_refs_json</text>
        <text x="360" y="850" className="node-detail-small">enabled · is_default</text>
        <text x="360" y="868" className="node-detail-small muted">last_probe_ok · failures</text>

        {/* SecretStore (warn yellow) */}
        <rect x="600" y="720" width="240" height="160" rx="14" className="ld-secret-shape" />
        <text x="720" y="750" textAnchor="middle" className="ld-secret-text" style={{fontSize: 16, fontWeight: 800}}>
          SecretStore overlay
        </text>
        <text x="720" y="770" textAnchor="middle" className="node-subtitle" style={{fontSize: 10.5}}>
          /app/data/secrets/
        </text>
        <text x="620" y="796" className="node-detail-small mono">/agents/phantom/</text>
        <text x="620" y="814" className="node-detail-small mono">  log_destinations/</text>
        <text x="620" y="832" className="node-detail-small mono">    {`<id>/<slot>`}</text>
        <text x="620" y="850" className="node-detail-small">AES-GCM at rest</text>
        <text x="620" y="868" className="node-detail-small muted">cascade-delete with row</text>

        {/* External destinations (orange) */}
        <rect x="860" y="720" width="260" height="160" rx="14" className="ld-external-shape" />
        <text x="990" y="750" textAnchor="middle" className="ld-external-text" style={{fontSize: 16, fontWeight: 800}}>
          External destinations
        </text>
        <text x="990" y="770" textAnchor="middle" className="node-subtitle" style={{fontSize: 10.5}}>
          (outside the trust boundary)
        </text>
        <text x="880" y="796" className="node-detail-small">XSIAM HTTPS collector</text>
        <text x="880" y="814" className="node-detail-small">syslog UDP / TCP / TLS</text>
        <text x="880" y="832" className="node-detail-small">Splunk HEC HTTPS</text>
        <text x="880" y="850" className="node-detail-small">webhook (4 auth modes)</text>
        <text x="990" y="870" textAnchor="middle" className="node-detail-small muted">handler.send() · handler.probe()</text>

        {/* types_loader → Type manifests (boot-time scan, dashed) */}
        <path className="edge muted" d="M 220 620 L 220 720" />
        {/* Store → log_destinations.db (config + non-secret writes) */}
        <path className="edge compose" d="M 540 684 L 460 720" />
        {/* Store → SecretStore (secret_refs writes) */}
        <path className="edge compose" d="M 660 684 L 720 720" />
        {/* Handler_registry → External (probe + send path) */}
        <path className="edge external" d="M 980 684 L 980 720" />
        <rect x="990" y="695" width="120" height="20" rx="5" className="edge-label-box" />
        <text x="1050" y="709" textAnchor="middle" className="edge-label-text-small">send / probe</text>
      </svg>
    </div>
  );
}
