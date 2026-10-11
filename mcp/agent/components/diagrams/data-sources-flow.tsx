/**
 * Data Sources flow diagram.
 *
 * Visual companion for the /help/architecture#data-sources section.
 *
 * What it shows:
 *   - The 4 layers a /data-sources request flows through:
 *       Browser → Next.js API proxy → embedded MCP → YAML loader
 *   - The 2 YAML roots the loader scans: bundle (read-only) + user
 *     (writable via the CRUD endpoints)
 *   - The 4 CRUD operations supported on user uploads:
 *       POST /user (create) · PUT /user/{id} (edit) ·
 *       POST /user/preview · DELETE /user/{id}
 *     each gated by the accept_token (SHA-256 of canonical YAML) so the
 *     operator must have just previewed the exact bytes they're committing
 *   - The 4 fields the response enrichment layer adds beyond the YAML's
 *     own attributes: vendor_logo_url, use_cases, origin, vendor_key
 *
 * Layout:
 *   - 3 horizontal lanes (Browser / Agent — Next.js / Agent — MCP)
 *   - Right column: 2 storage root boxes stacked vertically
 *   - Center: enrichment box between MCP and the response back to UI
 *
 * Version annotations are intentionally absent — this is customer-facing
 * documentation describing the system as it is, not as it evolved.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES = DIAGRAM_THEME_CSS + `
.dgm-root .ds-bundle-shape {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-state-info);
  stroke-width: 2;
}
.dgm-root .ds-user-shape {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-state-warn);
  stroke-width: 2;
}
.dgm-root .ds-enrich-shape {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-state-success);
  stroke-width: 2;
}
.dgm-root .ds-bundle-text { fill: var(--dgm-state-info); }
.dgm-root .ds-user-text { fill: var(--dgm-state-warn); }
.dgm-root .ds-enrich-text { fill: var(--dgm-state-success); }

.dgm-root .ds-row-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  fill: var(--dgm-text-muted);
}
.dgm-root .ds-version-badge {
  font-size: 10px;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  fill: var(--dgm-text-muted);
}
`;

export function DataSourcesFlow() {
  return (
    <div className="dgm-root">
      <style>{STYLES}</style>
      <svg
        viewBox="0 0 1200 800"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Data Sources request flow — browser through Next.js to the embedded MCP and YAML loader, with bundle vs user storage roots and response enrichment"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        {/* Title */}
        <text x="600" y="42" textAnchor="middle" className="title" fontSize="22">
          Data Sources request flow
        </text>
        <text x="600" y="68" textAnchor="middle" className="detail" fontSize="13">
          Browser → Next.js proxy → embedded MCP → YAML loader (bundle + user roots) → enrichment → UI
        </text>

        {/* Lane dividers + labels */}
        <line className="lane-line" x1="60" y1="120" x2="1140" y2="120" />
        <text x="74" y="113" className="lane-label">BROWSER</text>
        <line className="lane-line" x1="60" y1="260" x2="1140" y2="260" />
        <text x="74" y="253" className="lane-label">PHANTOM-AGENT · Next.js</text>
        <line className="lane-line" x1="60" y1="430" x2="1140" y2="430" />
        <text x="74" y="423" className="lane-label">PHANTOM-AGENT · embedded MCP (Python FastMCP)</text>
        <line className="lane-line" x1="60" y1="640" x2="1140" y2="640" />
        <text x="74" y="633" className="lane-label">CONTAINER FILESYSTEM</text>

        {/* ── Browser layer ───────────────────────────────────────── */}
        <rect x="380" y="140" width="440" height="92" rx="14" className="node-shape" />
        <text x="600" y="172" textAnchor="middle" className="node-title">/data-sources page</text>
        <text x="600" y="194" textAnchor="middle" className="node-subtitle">React 19 · two tabs: Browse + Installed</text>
        <text x="600" y="214" textAnchor="middle" className="node-detail-small">
          Browse / Installed / Drawer · upload + edit user uploads · use-case filter dropdown
        </text>

        {/* HTTPS edge browser → next.js */}
        <path className="edge operator" d="M 600 232 L 600 280" />
        <rect x="610" y="244" width="180" height="22" rx="5" className="edge-label-box" />
        <text x="700" y="259" textAnchor="middle" className="edge-label-text-small">HTTPS · cookie session</text>

        {/* ── Next.js layer (proxy routes) ────────────────────────── */}
        <rect x="160" y="280" width="880" height="120" rx="14" className="node-shape" />
        <text x="600" y="310" textAnchor="middle" className="node-title-small">/api/agent/data-sources/* — Next.js route handlers (lib/mcp-proxy.ts)</text>

        <text x="200" y="338" className="ds-row-label">READ</text>
        <text x="200" y="358" className="node-detail-small mono">/catalog</text>
        <text x="200" y="376" className="node-detail-small mono">/{`{pack}/{rule}/{ds}/schema`}</text>

        <text x="430" y="338" className="ds-row-label">USER CRUD</text>
        <text x="430" y="358" className="node-detail-small mono">POST  /user/preview</text>
        <text x="430" y="376" className="node-detail-small mono">POST  /user           (create)</text>
        <text x="430" y="394" className="node-detail-small mono">
          PUT   /user/{`{id}`}      <tspan className="ds-enrich-text">(edit)</tspan>
        </text>

        <text x="780" y="338" className="ds-row-label">DELETE</text>
        <text x="780" y="358" className="node-detail-small mono">DELETE /user/{`{id}`}</text>
        <text x="780" y="376" className="node-detail-small mono">           cascade uninstall</text>

        {/* Bearer-auth edge */}
        <path className="edge muted" d="M 600 400 L 600 450" />
        <rect x="608" y="412" width="220" height="22" rx="5" className="edge-label-box" />
        <text x="718" y="427" textAnchor="middle" className="edge-label-text-small">
          Bearer MCP_TOKEN · HTTPS:8080
        </text>

        {/* ── MCP layer ───────────────────────────────────────────── */}
        <rect x="120" y="450" width="540" height="170" rx="14" className="node-shape hero" />
        <rect className="hero-halo" x="100" y="438" width="580" height="200" rx="22" opacity="0.4" />
        <text x="390" y="482" textAnchor="middle" className="node-title">DataSourcesYamlLoader</text>
        <text x="390" y="504" textAnchor="middle" className="node-subtitle">bundles/spark/mcp/src/usecase/</text>

        <text x="150" y="532" className="ds-row-label">CACHE</text>
        <text x="150" y="550" className="node-detail-small">mtime-keyed per root</text>
        <text x="150" y="566" className="node-detail-small mono">in-memory accelerator</text>
        <text x="150" y="582" className="node-detail-small muted">invalidates on writes</text>

        <text x="400" y="532" className="ds-row-label">INDEX</text>
        <text x="400" y="550" className="node-detail-small">O(1) id lookup</text>
        <text x="400" y="566" className="node-detail-small mono">_id_index dict</text>
        <text x="400" y="582" className="node-detail-small">invalidated on write</text>

        <text x="150" y="602" className="ds-row-label">WRITE GATE</text>
        <text x="245" y="602" className="node-detail-small">
          accept_token = SHA-256(canonical YAML) · server re-hashes + verifies before write
        </text>

        {/* Enrichment box (right of loader, same lane) */}
        <rect x="700" y="450" width="340" height="170" rx="14" className="ds-enrich-shape" />
        <text x="870" y="482" textAnchor="middle" className="ds-enrich-text" style={{fontSize: 19, fontWeight: 800}}>
          Response enrichment
        </text>
        <text x="870" y="504" textAnchor="middle" className="node-subtitle">
          api/data_sources.py · per-row
        </text>

        <text x="720" y="532" className="ds-row-label">FIELDS ADDED</text>
        <text x="730" y="552" className="node-detail-small mono">+ vendor_logo_url</text>
        <text x="950" y="552" className="node-detail-small muted">one logo per vendor</text>
        <text x="730" y="570" className="node-detail-small mono">+ use_cases[]</text>
        <text x="950" y="570" className="node-detail-small muted">card badges + filter</text>
        <text x="730" y="588" className="node-detail-small mono">+ origin</text>
        <text x="950" y="588" className="node-detail-small muted">bundle | user</text>
        <text x="730" y="606" className="node-detail-small mono">+ vendor_key</text>
        <text x="950" y="606" className="node-detail-small muted">browse grouping</text>

        {/* Loader → enrichment arrow */}
        <path className="edge compose" d="M 660 535 L 700 535" />

        {/* ── Storage layer ───────────────────────────────────────── */}
        {/* Bundle root */}
        <rect x="120" y="660" width="540" height="110" rx="14" className="ds-bundle-shape" />
        <text x="390" y="690" textAnchor="middle" className="ds-bundle-text" style={{fontSize: 18, fontWeight: 800}}>
          BUNDLE root (read-only)
        </text>
        <text x="390" y="712" textAnchor="middle" className="node-subtitle">
          /app/bundle/data-sources/{`<id>/data_source.yaml`}
        </text>
        <text x="140" y="738" className="node-detail-small">
          342 YAMLs · 137 vendors · 44 use_cases · embedded logos
        </text>
        <text x="140" y="756" className="node-detail-small muted">
          shipped in image; refreshed on every release
        </text>

        {/* User root */}
        <rect x="700" y="660" width="340" height="110" rx="14" className="ds-user-shape" />
        <text x="870" y="690" textAnchor="middle" className="ds-user-text" style={{fontSize: 18, fontWeight: 800}}>
          USER root (writable)
        </text>
        <text x="870" y="712" textAnchor="middle" className="node-subtitle">
          /app/data/user_data_sources/
        </text>
        <text x="720" y="738" className="node-detail-small">
          operator uploads · backup/restore travels these
        </text>
        <text x="720" y="756" className="node-detail-small muted">
          collision rule: bundle wins on id; user must use new id
        </text>

        {/* Loader → roots */}
        <path className="edge compose" d="M 280 620 L 280 660" />
        <path className="edge compose" d="M 870 620 L 870 660" />

        {/* Enrichment → response back up to next.js */}
        <path className="edge operator" d="M 1040 530 L 1090 530 L 1090 340 L 1040 340" />
        <rect x="1052" y="425" width="86" height="22" rx="5" className="edge-label-box" />
        <text x="1095" y="440" textAnchor="middle" className="edge-label-text-small">JSON</text>

        {/* Response → browser */}
        <path className="edge operator" d="M 1090 280 L 1090 180 L 820 180 L 820 232" />

        {/* Legend strip */}
        <rect x="60" y="784" width="1080" height="0" />
      </svg>
    </div>
  );
}
