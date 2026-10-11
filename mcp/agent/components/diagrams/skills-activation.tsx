/**
 * Skills subsystem diagram — source → seed → catalog → activation.
 *
 * Visualizes the four moving parts of how a skill becomes callable:
 *
 *   1. Bundle source — every skill is a markdown file with YAML
 *      frontmatter at bundles/spark/mcp/skills/<category>/<name>.md.
 *      Categories: foundation/ (5), scenarios/ (12), workflows/ (3).
 *      Total: 20 skills.
 *
 *   2. Boot-time volume seed — entrypoint.sh's per-release marker
 *      auto-merges /app/mcp/skills-default/ → /app/skills/ on every
 *      version transition. Operators get new skills
 *      automatically on upgrade; their custom edits stay too (merge,
 *      not replace).
 *
 *   3. MCP catalog registration — the Python MCP server reads every
 *      *.md file in /app/skills/, parses frontmatter, registers each
 *      as a tool of name "Skill: <slug>". Catalog exposed via the
 *      agent's tool catalog (/api/skills + the agent's tools array).
 *
 *   4. Activation pathways — three ways a skill gets invoked at chat
 *      time:
 *      (a) Explicit slash command — operator types "/build_xql_query"
 *      (b) Agent auto-selection — agent reads frontmatter description,
 *          picks the skill matching the operator's intent
 *      (c) Job action.skill — scheduled job invokes a named skill
 *
 *   Once activated: the skill's MD body is loaded into the chat
 *   context, the agent reads + follows the instructions, calling
 *   tools as directed.
 *
 * Layout: source on the left, 4 horizontal layers flowing right.
 */

import { DIAGRAM_THEME_CSS, DiagramMarkers } from "./_diagram-theme";

const STYLES =
  DIAGRAM_THEME_CSS +
  `
.dgm-root.skills .source-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.4;
}
.dgm-root.skills .source-card.foundation { stroke: var(--dgm-state-success); }
.dgm-root.skills .source-card.scenarios  { stroke: var(--dgm-edge-operator); }
.dgm-root.skills .source-card.workflows  { stroke: var(--dgm-edge-shared); }
.dgm-root.skills .seed-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-state-info);
  stroke-width: 2.4;
}
.dgm-root.skills .catalog-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-shared);
  stroke-width: 2.4;
}
.dgm-root.skills .catalog-glow {
  fill: var(--dgm-edge-shared);
  opacity: 0.10;
}
.dgm-root.skills .activate-card {
  fill: var(--dgm-node-fill);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1.6;
}
.dgm-root.skills .activate-card.slash  { stroke: var(--dgm-edge-operator); }
.dgm-root.skills .activate-card.auto   { stroke: var(--dgm-state-info); }
.dgm-root.skills .activate-card.job    { stroke: var(--dgm-edge-shared); }
.dgm-root.skills .chat-card {
  fill: var(--dgm-node-fill-strong);
  stroke: var(--dgm-edge-compose);
  stroke-width: 2;
}
.dgm-root.skills .layer-tag {
  fill: var(--dgm-text-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
.dgm-root.skills .skill-frontmatter {
  fill: var(--dgm-badge-bg);
  stroke: var(--dgm-stroke-muted);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
`;

export function SkillsActivation() {
  return (
    <div className="dgm-root skills">
      <style>{STYLES}</style>
      <svg
        viewBox="0 0 1200 760"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Skills subsystem: bundle source → boot-time volume seed → MCP catalog registration → three activation pathways into the chat context"
      >
        <defs>
          <DiagramMarkers />
        </defs>

        <text x="600" y="36" textAnchor="middle" className="title" fontSize="22">
          Skills subsystem — source → seed → catalog → activation
        </text>
        <text x="600" y="60" textAnchor="middle" className="detail" fontSize="13">
          20 skills (5 foundation · 12 scenarios · 3 workflows) seeded once at boot · activated 3 ways at chat time
        </text>

        {/* ── LAYER 1: Bundle source (left, stacked 3 categories) ──── */}
        <text x="80" y="100" className="layer-tag">1. BUNDLE SOURCE</text>
        <text x="80" y="116" className="muted" fontSize="10">
          bundles/spark/mcp/skills/&lt;category&gt;/&lt;name&gt;.md
        </text>

        <rect x="80" y="135" width="240" height="62" rx="8" className="source-card foundation" />
        <text x="200" y="156" textAnchor="middle" className="node-title-small">foundation/</text>
        <text x="200" y="174" textAnchor="middle" className="muted" fontSize="10">
          primitive helpers: IOC gen, topology
        </text>
        <text x="200" y="188" textAnchor="middle" className="muted" fontSize="10">
          5 skills
        </text>

        <rect x="80" y="210" width="240" height="62" rx="8" className="source-card scenarios" />
        <text x="200" y="231" textAnchor="middle" className="node-title-small">scenarios/</text>
        <text x="200" y="249" textAnchor="middle" className="muted" fontSize="10">
          named ATT&amp;CK scenarios (knock_knock,
        </text>
        <text x="200" y="263" textAnchor="middle" className="muted" fontSize="10">
          ink_and_foil, …) · 12 skills
        </text>

        <rect x="80" y="285" width="240" height="62" rx="8" className="source-card workflows" />
        <text x="200" y="306" textAnchor="middle" className="node-title-small">workflows/</text>
        <text x="200" y="324" textAnchor="middle" className="muted" fontSize="10">
          multi-step orchestration including
        </text>
        <text x="200" y="338" textAnchor="middle" className="muted" fontSize="10">
          build_xql_query · 3 skills
        </text>

        {/* Frontmatter sidecar */}
        <rect x="80" y="375" width="240" height="105" rx="6" className="skill-frontmatter" />
        <text x="200" y="395" textAnchor="middle" className="muted" fontSize="10" fontWeight="700">
          MD FRONTMATTER (every skill)
        </text>
        <text x="92" y="415" className="muted" fontSize="9" fontFamily="JetBrains Mono, monospace">---</text>
        <text x="92" y="428" className="muted" fontSize="9" fontFamily="JetBrains Mono, monospace">name: build_xql_query</text>
        <text x="92" y="441" className="muted" fontSize="9" fontFamily="JetBrains Mono, monospace">displayName: Build XQL Query</text>
        <text x="92" y="454" className="muted" fontSize="9" fontFamily="JetBrains Mono, monospace">description: Use when ...</text>
        <text x="92" y="467" className="muted" fontSize="9" fontFamily="JetBrains Mono, monospace">tools: [run_xql, lookup]</text>

        {/* Arrow source → seed */}
        <path className="edge muted" d="M 330 240 L 400 240 L 400 240" />
        <path className="edge muted" d="M 320 240 L 415 240" markerEnd="url(#arrowMuted)" />
        <text x="370" y="232" textAnchor="middle" className="muted" fontSize="9">
          docker COPY
        </text>
        <text x="370" y="252" textAnchor="middle" className="muted" fontSize="9">
          (image bake)
        </text>

        {/* ── LAYER 2: Boot-time seed ─────────────────────────────── */}
        <text x="425" y="105" className="layer-tag">2. BOOT SEED</text>
        <rect x="425" y="135" width="245" height="180" rx="10" className="seed-card" />
        <text x="547" y="162" textAnchor="middle" className="node-title-small">entrypoint.sh §1</text>
        <text x="547" y="180" textAnchor="middle" className="muted" fontSize="10">
          /app/mcp/skills-default/
        </text>
        <text x="547" y="195" textAnchor="middle" className="muted" fontSize="10">
          ↓ merge (not replace)
        </text>
        <text x="547" y="210" textAnchor="middle" className="muted" fontSize="10">
          /app/skills/ (volume)
        </text>

        <line x1="445" y1="225" x2="650" y2="225" stroke="var(--dgm-stroke-muted)" strokeWidth="0.6" strokeDasharray="3 3" />

        <text x="547" y="245" textAnchor="middle" className="muted" fontSize="10" fontWeight="700">
          Per-release marker
        </text>
        <text x="547" y="262" textAnchor="middle" className="muted" fontSize="9">
          .seeded_version file in volume
        </text>
        <text x="547" y="276" textAnchor="middle" className="muted" fontSize="9">
          mismatch ⇒ re-merge image defaults
        </text>
        <text x="547" y="290" textAnchor="middle" className="muted" fontSize="9">
          new release skills auto-appear;
        </text>
        <text x="547" y="304" textAnchor="middle" className="muted" fontSize="9">
          operator&apos;s custom skills survive
        </text>

        {/* Arrow seed → catalog */}
        <path className="edge muted" d="M 670 225 L 720 225" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 3: MCP catalog ─────────────────────────────────── */}
        <text x="730" y="105" className="layer-tag">3. CATALOG</text>
        <rect x="730" y="135" width="240" height="180" rx="10" className="catalog-glow" />
        <rect x="730" y="135" width="240" height="180" rx="10" className="catalog-card" />
        <text x="850" y="162" textAnchor="middle" className="node-title-small">Embedded MCP</text>
        <text x="850" y="180" textAnchor="middle" className="muted" fontSize="10">
          scans /app/skills/*.md
        </text>
        <text x="850" y="195" textAnchor="middle" className="muted" fontSize="10">
          parses YAML frontmatter
        </text>
        <text x="850" y="210" textAnchor="middle" className="muted" fontSize="10">
          registers each as a tool
        </text>

        <line x1="750" y1="225" x2="950" y2="225" stroke="var(--dgm-stroke-muted)" strokeWidth="0.6" strokeDasharray="3 3" />

        <text x="850" y="245" textAnchor="middle" className="muted" fontSize="10" fontWeight="700">
          Exposed surfaces
        </text>
        <text x="850" y="262" textAnchor="middle" className="muted" fontSize="9">
          GET /api/skills (UI list)
        </text>
        <text x="850" y="276" textAnchor="middle" className="muted" fontSize="9">
          MCP tool catalog → agent
        </text>
        <text x="850" y="290" textAnchor="middle" className="muted" fontSize="9">
          /skills page hydrates from API
        </text>

        {/* Arrow catalog → activation */}
        <path className="edge muted" d="M 970 225 L 1020 225" markerEnd="url(#arrowMuted)" />

        {/* ── LAYER 4: Activation pathways (right column, 3 cards) ── */}
        <text x="1000" y="105" className="layer-tag">4. ACTIVATION</text>

        <rect x="1000" y="135" width="180" height="50" rx="8" className="activate-card slash" />
        <text x="1090" y="156" textAnchor="middle" className="node-title-small">(a) /slash command</text>
        <text x="1090" y="174" textAnchor="middle" className="muted" fontSize="9">
          operator types &quot;/build_xql_query&quot;
        </text>

        <rect x="1000" y="195" width="180" height="50" rx="8" className="activate-card auto" />
        <text x="1090" y="216" textAnchor="middle" className="node-title-small">(b) agent auto-pick</text>
        <text x="1090" y="234" textAnchor="middle" className="muted" fontSize="9">
          frontmatter description match
        </text>

        <rect x="1000" y="255" width="180" height="50" rx="8" className="activate-card job" />
        <text x="1090" y="276" textAnchor="middle" className="node-title-small">(c) action.skill (jobs)</text>
        <text x="1090" y="294" textAnchor="middle" className="muted" fontSize="9">
          scheduled job invokes by name
        </text>

        {/* All 3 → chat context */}
        <path className="edge muted" d="M 1000 160 L 980 160 L 980 460 L 720 460" markerEnd="url(#arrowMuted)" />
        <path className="edge muted" d="M 1000 220 L 985 220 L 985 460" />
        <path className="edge muted" d="M 1000 280 L 990 280 L 990 460" />

        {/* ── LAYER 5: Chat context (bottom) ───────────────────────── */}
        <text x="80" y="495" className="layer-tag">5. RUNTIME ACTIVATION</text>

        <rect x="80" y="510" width="1040" height="100" rx="10" className="chat-card" />
        <text x="600" y="540" textAnchor="middle" className="node-title-small" fontSize="14">
          Chat context — skill body loaded into the LLM prompt
        </text>
        <text x="600" y="562" textAnchor="middle" className="muted" fontSize="11">
          MCP returns the skill&apos;s MD body as system-message content. The agent reads + follows the skill&apos;s
        </text>
        <text x="600" y="578" textAnchor="middle" className="muted" fontSize="11">
          instructions step by step, calling tools as the skill directs (knowledge_search, xdr_run_xql_query, etc.).
        </text>
        <text x="600" y="596" textAnchor="middle" className="muted" fontSize="11">
          The skill&apos;s frontmatter <tspan className="muted" fontFamily="JetBrains Mono, monospace">tools:</tspan> list constrains which tool calls are allowed within the activation.
        </text>

        {/* Layer separator */}
        <line x1="80" y1="640" x2="1120" y2="640" stroke="var(--dgm-stroke-muted)" strokeWidth="0.5" strokeDasharray="2 4" />

        {/* Footer note */}
        <text x="600" y="666" textAnchor="middle" className="muted" fontSize="10">
          Skills are READ-ONLY at agent runtime — the MD body is loaded into the prompt but never re-written.
        </text>
        <text x="600" y="682" textAnchor="middle" className="muted" fontSize="10">
          To edit a skill: modify the file in /app/skills (operator-created) or in the bundle source + redeploy (image-default).
        </text>
        <text x="600" y="698" textAnchor="middle" className="muted" fontSize="10">
          FORCE_SKILLS_SYNC=1 on container restart forces a re-merge regardless of marker state (rare; recovery path).
        </text>
        <text x="600" y="722" textAnchor="middle" className="muted" fontSize="10" fontStyle="italic">
          See also: /skills (operator UI) · /help/user#skills (operator narrative) · build_xql_query.md (largest workflow)
        </text>
      </svg>
    </div>
  );
}
