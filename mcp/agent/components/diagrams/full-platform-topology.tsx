"use client";

/**
 * Phantom Full-Platform Topology — embedded SVG diagram.
 *
 * Source SVG converted to JSX. Theme colour tokens live in the shared
 * _diagram-theme module; the toggle in the agent sidebar writes
 * data-theme="light" on <html> and the diagram reflows automatically.
 *
 * No animations. No JavaScript at runtime. Pure SVG + CSS.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES = DIAGRAM_THEME_CSS;

export function FullPlatformTopology() {
  return (
    <div className="dgm-root">
      <style>{STYLES}</style>
      <svg viewBox="0 0 1280 920" role="img" aria-labelledby="fpt-diagram-title fpt-diagram-desc">
      <title id="fpt-diagram-title">Phantom platform full-platform topology</title>
      <desc id="fpt-diagram-desc">
        Dark-themed topology diagram showing Phantom clients, agent, MCP server, connector backends, sinks,
        and all authenticated edges across the platform.
      </desc>

      <defs>
        <DiagramMarkers />
        <linearGradient id="fpt-bg-gradient" x1="0" y1="0" x2="1280" y2="920" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="var(--dgm-bg-0)" />
          <stop offset="48%" stopColor="var(--dgm-bg-1)" />
          <stop offset="100%" stopColor="var(--dgm-bg-2)" />
        </linearGradient>

        <pattern id="fpt-dot-grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="var(--dgm-grid-dot)" />
        </pattern>

        <symbol id="fpt-icon-browser" viewBox="0 0 24 24">
          <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
          <path d="M3.5 9h17" />
          <path d="M7 7.1h.01M10 7.1h.01" />
        </symbol>

        <symbol id="fpt-icon-code" viewBox="0 0 24 24">
          <path d="M8 8l-4 4 4 4" />
          <path d="M16 8l4 4-4 4" />
          <path d="M13.5 5.5l-3 13" />
        </symbol>

        <symbol id="fpt-icon-laptop" viewBox="0 0 24 24">
          <rect x="5" y="5" width="14" height="10" rx="2" />
          <path d="M3.5 18h17" />
          <path d="M9 18h6" />
        </symbol>

        <symbol id="fpt-icon-sparkles" viewBox="0 0 24 24">
          <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z" />
          <path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14z" />
          <path d="M5 15l.7 1.8L7.5 17.5l-1.8.7L5 20l-.7-1.8-1.8-.7 1.8-.7L5 15z" />
        </symbol>

        <symbol id="fpt-icon-hub" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <circle cx="5" cy="7" r="2" />
          <circle cx="19" cy="7" r="2" />
          <circle cx="5" cy="17" r="2" />
          <circle cx="19" cy="17" r="2" />
          <path d="M7 8l3 2.2M17 8l-3 2.2M7 16l3-2.2M17 16l-3-2.2" />
        </symbol>

        <symbol id="fpt-icon-bolt" viewBox="0 0 24 24">
          <path d="M13 2L5 13h6l-1 9 9-12h-6l0-8z" />
        </symbol>

        <symbol id="fpt-icon-swords" viewBox="0 0 24 24">
          <path d="M5 4l6.5 6.5" />
          <path d="M19 4l-6.5 6.5" />
          <path d="M10 12l-5 5" />
          <path d="M14 12l5 5" />
          <path d="M4 20l4-4" />
          <path d="M20 20l-4-4" />
          <path d="M8.5 8.5l2-2M15.5 8.5l-2-2" />
        </symbol>

        <symbol id="fpt-icon-magnifier" viewBox="0 0 24 24">
          <circle cx="10.5" cy="10.5" r="5.5" />
          <path d="M15 15l5 5" />
          <path d="M8 10.5h5" />
        </symbol>

        <symbol id="fpt-icon-inbox" viewBox="0 0 24 24">
          <path d="M4 12l2.5-7h11L20 12" />
          <path d="M4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" />
          <path d="M8 12l2 3h4l2-3" />
        </symbol>
      </defs>

      
      <rect x="0" y="0" width="1280" height="920" fill="url(#fpt-bg-gradient)" />
      <rect x="0" y="0" width="1280" height="920" fill="url(#fpt-dot-grid)" />

      
      <text x="170" y="38" className="title" fontSize="24">Phantom Platform Topology</text>
      <text x="170" y="60" className="detail" fontSize="13">Continuous SOC simulation stack · Docker Compose services · external model, PAPI, and webhook integrations</text>

      
      <line className="lane-line" x1="155" y1="205" x2="1235" y2="205" />
      <line className="lane-line" x1="155" y1="390" x2="1235" y2="390" />
      <line className="lane-line" x1="155" y1="580" x2="1235" y2="580" />
      <line className="lane-line" x1="155" y1="755" x2="1235" y2="755" />

      
      <text className="lane-label" x="42" y="125">CLIENTS</text>
      <text className="lane-label" x="42" y="300">PHANTOM AGENT</text>
      <text className="lane-label" x="42" y="488">MCP SERVER</text>
      <text className="lane-label" x="42" y="670">CONNECTOR BACKENDS</text>
      <text className="lane-label" x="42" y="823">SINKS</text>

      
      <path className="edge operator" d="M312 166 C312 188 465 204 465 235" />
      <path className="edge operator" d="M625 166 L625 235" />
      <path className="edge iap" d="M970 166 C970 196 790 205 790 235" />

      <path className="edge external" d="M855 290 L936 290" />
      <path className="edge shared" d="M625 345 L625 430" />

      <path className="edge compose" d="M500 538 C500 560 370 586 370 620" />
      <path className="edge compose" d="M775 538 C775 560 720 588 720 620" />
      <path className="edge external" d="M1010 489 C1072 512 1081 559 1081 600" />

      <path className="edge external" d="M370 715 L370 784" />

      
      <g transform="translate(338 214)">
        <rect className="edge-label-box" x="0" y="-15" width="108" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">HTTPS · Basic</text>
      </g>

      <g transform="translate(638 214)">
        <rect className="edge-label-box" x="0" y="-15" width="118" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">Bearer (api key)</text>
      </g>

      <g transform="translate(806 214)">
        <rect className="edge-label-box" x="0" y="-15" width="132" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">SSH tunnel → :3000</text>
      </g>

      
      <g transform="translate(858 273)">
        <rect className="edge-label-box" x="0" y="-15" width="156" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">OAuth2 · service account</text>
      </g>

      <g transform="translate(638 405)">
        <rect className="edge-label-box" x="0" y="-16" width="242" height="27" rx="8" />
        <text className="edge-label-text" x="10" y="3">Authorization: Bearer $MCP_TOKEN</text>
      </g>

      
      <g transform="translate(336 599)">
        <rect className="edge-label-box" x="0" y="-15" width="142" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">https://xlog:8000</text>
      </g>

      <g transform="translate(670 599)">
        <rect className="edge-label-box" x="0" y="-15" width="148" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">http://caldera:8888</text>
      </g>

      <g transform="translate(1046 584)">
        <rect className="edge-label-box" x="0" y="-15" width="86" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">HTTPS PAPI</text>
      </g>

      
      <g transform="translate(392 771)">
        <rect className="edge-label-box" x="0" y="-15" width="202" height="25" rx="8" />
        <text className="edge-label-text" x="10" y="2">Authorization: $WEBHOOK_KEY</text>
      </g>

      
      <g className="node" transform="translate(175 72)">
        <rect className="node-shape" x="0" y="0" width="275" height="94" rx="18" />
        <circle className="badge" cx="34" cy="34" r="18" />
        <use href="#fpt-icon-browser" className="icon" x="22" y="22" width="24" height="24" />
        <text className="node-title-small" x="64" y="31">Operator browser</text>
        <text className="node-subtitle" x="64" y="54">UI auth · HTTP Basic</text>
        <text className="node-detail" x="64" y="75">operator UI surface</text>
      </g>

      <g className="node" transform="translate(500 72)">
        <rect className="node-shape" x="0" y="0" width="250" height="94" rx="18" />
        <circle className="badge" cx="34" cy="34" r="18" />
        <use href="#fpt-icon-code" className="icon" x="22" y="22" width="24" height="24" />
        <text className="node-title-small" x="64" y="31">API clients</text>
        <text className="node-subtitle" x="64" y="54">Bearer (api key)</text>
        <text className="node-detail" x="64" y="75">curl / scripts / CI</text>
      </g>

      <g className="node workstation" transform="translate(820 72)">
        <rect className="node-shape" x="0" y="0" width="300" height="94" rx="18" />
        <circle className="badge" cx="34" cy="34" r="18" />
        <use href="#fpt-icon-laptop" className="icon" x="22" y="22" width="24" height="24" />
        <text className="node-title-small" x="64" y="31">Operator workstation</text>
        <text className="node-subtitle" x="64" y="54">SSH tunnel → VM:22</text>
        <text className="node-detail" x="64" y="75">remote-only entry path</text>
      </g>

      
      <g className="node hero" transform="translate(385 235)">
        <rect className="hero-halo" x="12" y="12" width="446" height="102" rx="24" />
        <rect className="node-shape" x="0" y="0" width="470" height="110" rx="22" />
        <circle className="badge" cx="38" cy="38" r="20" />
        <use href="#fpt-icon-browser" className="icon" x="25" y="25" width="26" height="26" />
        <text className="node-title" x="74" y="36">phantom-agent</text>
        <text className="node-subtitle" x="74" y="62">Next.js 15 · React 19 · :3000</text>
        <text className="node-detail" x="74" y="83">operator UI · chat handler</text>
        <text className="node-detail" x="74" y="101">server-side passthrough to MCP</text>
      </g>

      <g className="node external">
        <ellipse className="node-shape" cx="1084" cy="290" rx="148" ry="58" />
        <circle className="badge" cx="986" cy="270" r="18" />
        <use href="#fpt-icon-sparkles" className="icon" x="974" y="258" width="24" height="24" />
        <text className="node-title-small" x="1018" y="270">Vertex AI / Gemini</text>
        <text className="node-subtitle" x="1018" y="292">Google Cloud · external</text>
        <text className="node-detail-small" x="1018" y="314">chat model · embeddings · cache</text>
      </g>

      
      <g className="node hero" transform="translate(290 430)">
        <rect className="hero-halo" x="14" y="12" width="692" height="102" rx="24" />
        <rect className="node-shape" x="0" y="0" width="720" height="108" rx="22" />
        <circle className="badge" cx="38" cy="38" r="20" />
        <use href="#fpt-icon-hub" className="icon" x="25" y="25" width="26" height="26" />
        <text className="node-title" x="74" y="36">phantom-mcp</text>
        <text className="node-subtitle" x="74" y="62">FastMCP · :8080 · streamable-http</text>
        <text className="node-detail" x="74" y="83">~80 tools · 6 SQLite stores</text>
        <text className="node-detail" x="74" y="101">runtime built-ins: memory · sessions · knowledge · skills · tasks · hooks</text>
      </g>

      
      <g className="node" transform="translate(220 620)">
        <rect className="node-shape" x="0" y="0" width="300" height="95" rx="18" />
        <circle className="badge" cx="34" cy="34" r="18" />
        <use href="#fpt-icon-bolt" className="icon" x="22" y="22" width="24" height="24" />
        <text className="node-title-small" x="64" y="31">xlog (phantom)</text>
        <text className="node-subtitle" x="64" y="54">FastAPI + GraphQL · :8000</text>
        <text className="node-detail" x="64" y="75">synthetic logs · scenarios · workers</text>
      </g>

      <g className="node" transform="translate(570 620)">
        <rect className="node-shape" x="0" y="0" width="300" height="95" rx="18" />
        <circle className="badge" cx="34" cy="34" r="18" />
        <use href="#fpt-icon-swords" className="icon" x="22" y="22" width="24" height="24" />
        <text className="node-title-small" x="64" y="31">caldera</text>
        <text className="node-subtitle" x="64" y="54">5.3.0 · :8888 / :8443</text>
        <text className="node-detail" x="64" y="75">MITRE ATT&amp;CK adversary emulation</text>
      </g>

      <g className="node external">
        <ellipse className="node-shape" cx="1084" cy="660" rx="148" ry="60" />
        <circle className="badge" cx="986" cy="638" r="18" />
        <use href="#fpt-icon-magnifier" className="icon" x="974" y="626" width="24" height="24" />
        <text className="node-title-small" x="1018" y="638">XSIAM PAPI</text>
        <text className="node-subtitle" x="1018" y="660">Cortex Cloud · external</text>
        <text className="node-detail-small" x="1018" y="682">XQL execution · detection content</text>
      </g>

      
      <g className="node sink" transform="translate(160 784)">
        <rect className="node-shape" x="0" y="0" width="420" height="66" rx="17" />
        <circle className="badge" cx="34" cy="33" r="17" />
        <use href="#fpt-icon-inbox" className="icon" x="22" y="21" width="24" height="24" />
        <text className="node-title-small" x="64" y="29">XSIAM HTTP collector / arbitrary webhook</text>
        <text className="node-subtitle" x="64" y="51">telemetry sink — receives synthesised logs</text>
      </g>

      
      <g transform="translate(170 868)">
        <rect x="0" y="-18" width="940" height="44" rx="16" fill="var(--dgm-panel)" stroke="var(--dgm-stroke-muted)" />
        <text className="legend-title" x="18" y="8">Legend</text>

        <line className="legend-line" x1="92" y1="4" x2="122" y2="4" stroke="var(--dgm-edge-operator)" />
        <text className="legend-text" x="132" y="8">operator HTTP</text>

        <line className="legend-line dashed" x1="258" y1="4" x2="288" y2="4" stroke="var(--dgm-edge-iap)" />
        <text className="legend-text" x="298" y="8">SSH tunnel</text>

        <line className="legend-line" x1="410" y1="4" x2="446" y2="4" stroke="var(--dgm-edge-shared)" strokeWidth="4" />
        <text className="legend-text" x="456" y="8">shared secret</text>

        <line className="legend-line" x1="604" y1="4" x2="634" y2="4" stroke="var(--dgm-edge-compose)" />
        <text className="legend-text" x="644" y="8">compose-internal</text>

        <line className="legend-line" x1="800" y1="4" x2="830" y2="4" stroke="var(--dgm-edge-external)" />
        <text className="legend-text" x="840" y="8">external SaaS</text>
      </g>
    </svg>
    </div>
  );
}
