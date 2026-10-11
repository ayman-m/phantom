/**
 * Shared diagram theme — single source of truth for every architecture
 * + user-guide diagram component.
 *
 * Why: every diagram needs the same colour palette and theme-toggle
 * behaviour. Duplicating the 27 CSS variables + 25 common classes per
 * diagram leads to drift the moment one of them is tweaked. Each
 * diagram component imports `DIAGRAM_THEME_CSS` and concatenates it
 * with its own structural CSS:
 *
 *   const STYLES = DIAGRAM_THEME_CSS + `
 *     .dgm-root .my-layout { ... }
 *   `;
 *
 * Rules for adding to this file:
 *   1. Only add classes that ≥ 2 diagrams will use. One-offs stay in
 *      the diagram's own file.
 *   2. Always add the value to BOTH the dark block (default) AND the
 *      [data-theme="light"] override. Skipping the light value leaks
 *      the dark value into light mode — visible immediately on toggle.
 *   3. Variable names use the `--dgm-` prefix. Class names use the
 *      `.dgm-` prefix when they could collide with anything else on
 *      the page; common-name classes (`.title`, `.subtitle`,
 *      `.lane-label`) are scoped under `.dgm-root` instead.
 */

export const DIAGRAM_THEME_CSS = `
.dgm-root {
  /* ── Dark (default) ─────────────────────────────────────── */
  --dgm-bg-0: #050914;
  --dgm-bg-1: #071426;
  --dgm-bg-2: #0b1020;
  --dgm-panel: rgba(255, 255, 255, 0.035);
  --dgm-node-fill: rgba(12, 22, 38, 0.94);
  --dgm-node-fill-strong: rgba(13, 28, 50, 0.98);
  --dgm-external-fill: rgba(22, 24, 34, 0.96);
  --dgm-sink-fill: rgba(11, 20, 31, 0.96);
  --dgm-stroke-muted: rgba(164, 183, 207, 0.25);
  --dgm-stroke-strong: rgba(219, 232, 255, 0.40);
  --dgm-lane: rgba(170, 190, 220, 0.22);
  --dgm-text-main: #edf5ff;
  --dgm-text-soft: #b9c8da;
  --dgm-text-muted: #7f91a8;
  --dgm-badge-bg: rgba(255, 255, 255, 0.075);
  --dgm-badge-stroke: rgba(255, 255, 255, 0.14);
  --dgm-label-bg: rgba(5, 9, 20, 0.88);
  --dgm-label-border: rgba(255, 255, 255, 0.14);
  --dgm-hero-glow: rgba(44, 130, 255, 0.18);
  --dgm-edge-operator: #4aa3ff;
  --dgm-edge-iap: #a9b4c2;
  --dgm-edge-shared: #f7b731;
  --dgm-edge-compose: #45d483;
  --dgm-edge-external: #ff9f43;
  --dgm-state-success: #45d483;
  --dgm-state-warn: #f7b731;
  --dgm-state-error: #ff7a8a;
  --dgm-state-info: #4aa3ff;
  --dgm-code: #d9e7ff;
  --dgm-grid-dot: rgba(255, 255, 255, 0.045);
}

[data-theme="light"] .dgm-root {
  /* ── Light overrides ────────────────────────────────────── */
  --dgm-bg-0: #f8fafc;
  --dgm-bg-1: #f1f5f9;
  --dgm-bg-2: #e2e8f0;
  --dgm-panel: rgba(15, 23, 42, 0.04);
  --dgm-node-fill: #ffffff;
  --dgm-node-fill-strong: #ffffff;
  --dgm-external-fill: #ffffff;
  --dgm-sink-fill: #ffffff;
  --dgm-stroke-muted: rgba(15, 23, 42, 0.18);
  --dgm-stroke-strong: rgba(15, 23, 42, 0.50);
  --dgm-lane: rgba(15, 23, 42, 0.16);
  --dgm-text-main: #0f172a;
  --dgm-text-soft: #334155;
  --dgm-text-muted: #64748b;
  --dgm-badge-bg: rgba(15, 23, 42, 0.05);
  --dgm-badge-stroke: rgba(15, 23, 42, 0.16);
  --dgm-label-bg: rgba(255, 255, 255, 0.96);
  --dgm-label-border: rgba(15, 23, 42, 0.14);
  --dgm-hero-glow: rgba(31, 123, 255, 0.10);
  --dgm-edge-operator: #1f7bff;
  --dgm-edge-iap: #64748b;
  --dgm-edge-shared: #d97706;
  --dgm-edge-compose: #059669;
  --dgm-edge-external: #ea580c;
  --dgm-state-success: #059669;
  --dgm-state-warn: #d97706;
  --dgm-state-error: #b91c1c;
  --dgm-state-info: #1f7bff;
  --dgm-code: #1e293b;
  --dgm-grid-dot: rgba(15, 23, 42, 0.06);
}

.dgm-root svg {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 18px;
  background: var(--dgm-bg-0);
}

/* ── Typography ─────────────────────────────────────────── */
.dgm-root .title {
  font-weight: 750;
  letter-spacing: -0.02em;
  fill: var(--dgm-text-main);
}
.dgm-root .subtitle,
.dgm-root .mono {
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  fill: var(--dgm-code);
}
.dgm-root .detail { fill: var(--dgm-text-soft); }
.dgm-root .muted { fill: var(--dgm-text-muted); }

.dgm-root .lane-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.14em;
  fill: var(--dgm-text-muted);
}
.dgm-root .lane-line {
  stroke: var(--dgm-lane);
  stroke-width: 1;
  stroke-dasharray: 7 10;
}

/* ── Node containers ────────────────────────────────────── */
.dgm-root .node-shape {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root .hero .node-shape {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-stroke-strong);
  stroke-width: 2.3;
}
.dgm-root .workstation .node-shape {
  stroke: var(--dgm-edge-iap);
  stroke-width: 1.7;
  stroke-dasharray: 8 7;
}
.dgm-root .external .node-shape {
  fill: var(--dgm-external-fill);
  stroke: var(--dgm-edge-external);
  stroke-width: 1.7;
}
.dgm-root .sink .node-shape {
  fill: var(--dgm-sink-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root .hero-halo { fill: var(--dgm-hero-glow); }
.dgm-root .badge {
  fill: var(--dgm-badge-bg);
  stroke: var(--dgm-badge-stroke);
  stroke-width: 1;
}
.dgm-root .icon {
  fill: none;
  stroke: var(--dgm-text-main);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dgm-root .icon-fill {
  fill: var(--dgm-text-main);
  stroke: none;
}

/* ── Node text ──────────────────────────────────────────── */
.dgm-root .node-title {
  font-size: 18px;
  font-weight: 760;
  fill: var(--dgm-text-main);
  letter-spacing: -0.01em;
}
.dgm-root .node-title-small {
  font-size: 15px;
  font-weight: 760;
  fill: var(--dgm-text-main);
  letter-spacing: -0.01em;
}
.dgm-root .node-subtitle {
  font-size: 12.5px;
  fill: var(--dgm-code);
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}
.dgm-root .node-detail { font-size: 12.5px; fill: var(--dgm-text-soft); }
.dgm-root .node-detail-small { font-size: 11.8px; fill: var(--dgm-text-soft); }

/* ── Edges ──────────────────────────────────────────────── */
.dgm-root .edge {
  fill: none;
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dgm-root .edge.operator { stroke: var(--dgm-edge-operator); marker-end: url(#dgm-arrow-operator); }
.dgm-root .edge.iap      { stroke: var(--dgm-edge-iap); stroke-width: 2; stroke-dasharray: 8 7; marker-end: url(#dgm-arrow-iap); }
.dgm-root .edge.shared   { stroke: var(--dgm-edge-shared); stroke-width: 4; marker-end: url(#dgm-arrow-shared); }
.dgm-root .edge.compose  { stroke: var(--dgm-edge-compose); marker-end: url(#dgm-arrow-compose); }
.dgm-root .edge.external { stroke: var(--dgm-edge-external); marker-end: url(#dgm-arrow-external); }
.dgm-root .edge.muted    { stroke: var(--dgm-text-muted); stroke-width: 1.6; marker-end: url(#dgm-arrow-muted); }

/* ── Edge labels ────────────────────────────────────────── */
.dgm-root .edge-label-box {
  fill: var(--dgm-label-bg);
  stroke: var(--dgm-label-border);
  stroke-width: 1;
}
.dgm-root .edge-label-text {
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  fill: var(--dgm-text-main);
}
.dgm-root .edge-label-text-small {
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 11.5px;
  fill: var(--dgm-text-main);
}

/* ── Legend ─────────────────────────────────────────────── */
.dgm-root .legend-title { font-size: 13px; font-weight: 780; fill: var(--dgm-text-main); }
.dgm-root .legend-text { font-size: 12px; fill: var(--dgm-text-soft); }
.dgm-root .legend-line { stroke-width: 3; stroke-linecap: round; }
.dgm-root .legend-line.dashed { stroke-dasharray: 7 6; }

/* ── State chip palette (for state-machine + status atlas diagrams) ── */
.dgm-root .state-success-fill { fill: var(--dgm-state-success); }
.dgm-root .state-warn-fill    { fill: var(--dgm-state-warn); }
.dgm-root .state-error-fill   { fill: var(--dgm-state-error); }
.dgm-root .state-info-fill    { fill: var(--dgm-state-info); }
.dgm-root .state-success-stroke { stroke: var(--dgm-state-success); }
.dgm-root .state-warn-stroke    { stroke: var(--dgm-state-warn); }
.dgm-root .state-error-stroke   { stroke: var(--dgm-state-error); }
.dgm-root .state-info-stroke    { stroke: var(--dgm-state-info); }
`;

/**
 * Shared marker (arrowhead) <defs> fragment. Every diagram that uses
 * arrows should render <DiagramMarkers /> inside its own <defs>. The
 * marker IDs are scoped with `dgm-` so they're stable across all
 * diagrams; the shared CSS in DIAGRAM_THEME_CSS already references
 * them via marker-end: url(#dgm-arrow-*).
 *
 * If a page renders multiple diagrams, the IDs are still unique-by-
 * convention because every diagram uses the same canonical marker
 * set — having two `<defs>` blocks with the same `<marker>` ID is a
 * SVG no-op (browser uses the first definition), which is the
 * intended behaviour here.
 */
export function DiagramMarkers() {
  return (
    <>
      <marker
        id="dgm-arrow-operator"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="8"
        markerHeight="8"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-edge-operator)" />
      </marker>
      <marker
        id="dgm-arrow-iap"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="8"
        markerHeight="8"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-edge-iap)" />
      </marker>
      <marker
        id="dgm-arrow-shared"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="9"
        markerHeight="9"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-edge-shared)" />
      </marker>
      <marker
        id="dgm-arrow-compose"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="8"
        markerHeight="8"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-edge-compose)" />
      </marker>
      <marker
        id="dgm-arrow-external"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="8"
        markerHeight="8"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-edge-external)" />
      </marker>
      <marker
        id="dgm-arrow-muted"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto"
      >
        <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--dgm-text-muted)" />
      </marker>
    </>
  );
}
