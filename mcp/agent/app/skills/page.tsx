"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ImportSkillButton } from "./import-button";
import { confirmAction } from "@/lib/stores/confirm";
import { notify } from "@/lib/stores/notifications";

// ─── Types ───────────────────────────────────────────────────────────────────

// Phantom skill categories mirror the on-disk layout under
// bundles/spark/mcp/skills/ — foundation primitives, scenario
// runbooks, validation queries, end-to-end workflows, and
// plugin-contributed skills under plugins/<vendor>/<skill>.md.
type CategoryKey =
  | "all"
  | "foundation"
  | "scenarios"
  | "validation"
  | "workflows"
  | "plugins";

type SourceType = "platform" | "workspace" | "managed" | "plugin";

interface SkillDef {
  id: string;
  name: string;
  displayName: string;
  category: Exclude<CategoryKey, "all">;
  description: string;
  icon: string;
  source: SourceType;
  /** Protected skills cannot be deleted from the UI. */
  locked: boolean;
  /** Path under the skills directory, e.g. "scenarios/port_scan.md". */
  filePath: string;
  sizeBytes: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const CATEGORY_META: Record<
  Exclude<CategoryKey, "all">,
  { label: string; icon: string; color: string; bg: string; border: string; iconBg: string }
> = {
  // Unified tint — mixed blue/green/orange icons across categories
  // looked inconsistent. Each card already
  // carries its category as a labeled chip (so the meaning is preserved
  // without the icon hue carrying it). All four categories now use
  // primary blue tints, which read as a single design language and
  // matches the rest of the app's blue-anchored chrome.
  foundation: {
    label: "Foundation",
    icon: "foundation",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  scenarios: {
    label: "Scenarios",
    icon: "campaign",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  validation: {
    label: "Validation",
    icon: "fact_check",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  workflows: {
    label: "Workflows",
    icon: "workflow",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  plugins: {
    label: "Plugins",
    icon: "extension",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
};

const SOURCE_META: Record<SourceType, { label: string; className: string }> = {
  platform: { label: "PLATFORM", className: "text-on-surface-variant bg-surface-container-high" },
  workspace: { label: "WORKSPACE", className: "text-primary border border-primary/30" },
  managed: { label: "MANAGED", className: "text-secondary border border-secondary/30" },
  // Plugin-contributed skills shipped under plugins/<vendor>/.
  // Vendor name is surfaced in the row's `plugin_vendor` field; this
  // chip just marks "this didn't come from the bundle's built-in
  // categories" without committing to a specific vendor's brand colour.
  plugin: { label: "PLUGIN", className: "text-tertiary border border-tertiary/30" },
};

// The chip row. Counts are NOT stored here: they are derived at render time
// from the same `skills` array the grid renders (SkillsPage::categoryCounts),
// so a chip can never disagree with the list below it.
const CATEGORY_FILTERS: { key: CategoryKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "foundation", label: "Foundation" },
  { key: "scenarios", label: "Scenarios" },
  { key: "validation", label: "Validation" },
  { key: "workflows", label: "Workflows" },
  { key: "plugins", label: "Plugins" },
];

// Summary stats are computed from the live `skills` array (see
// SkillsPage::summaryStats useMemo) rather than hardcoded, so they
// cannot drift out of sync with what /api/skills returns.
//
// The caption is a constant because it doesn't depend on the live count.
const SUMMARY_CAPTIONS = {
  totalCaption: "Registered skills",
} as const;

// Phantom is single-tenant — there are no workspaces. The Workspaces
// column on the skill detail panel still exists in the UI but the
// data is empty. Future work: drop the entire workspace section from
// the detail panel.
const DEFAULT_WORKSPACES: { name: string; slug: string; icon: string; enabled: boolean }[] = [];

// ─── Styles ─────────────────────────────────────────────────────────────────

const glassStyle: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
};

const panelStyle: React.CSSProperties = {
  background: "var(--glass-bg-elev)",
  backdropFilter: "blur(16px)",
  borderLeft: "0.5px solid var(--glass-border)",
};

const ghostBorder: React.CSSProperties = {
  border: "0.5px solid var(--glass-border)",
};

// ─── Sub-Components ─────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div
        className="h-[2px] w-16"
        style={{ background: "linear-gradient(90deg, #1963b3 0%, transparent 100%)" }}
      />
      <span className="font-label uppercase tracking-[0.2em] text-[10px] font-black text-on-surface-variant/40">
        {label}
      </span>
    </div>
  );
}

function SkillCard({
  skill,
  onSelect,
}: {
  skill: SkillDef;
  onSelect: () => void;
}) {
  const cat = CATEGORY_META[skill.category];
  const src = SOURCE_META[skill.source];

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className="p-6 rounded-2xl hover:ring-1 hover:ring-primary/20 transition-all cursor-pointer group"
      style={glassStyle}
    >
      {/* Icon + controls */}
      <div className="flex justify-between mb-6">
        <div
          className={`w-12 h-12 rounded-xl ${cat.iconBg} flex items-center justify-center`}
        >
          <span className={`material-symbols-outlined text-2xl ${cat.color}`}>
            {skill.icon}
          </span>
        </div>
        <div className="flex gap-2 items-center">
          <span
            className={`material-symbols-outlined ${
              skill.locked ? "text-primary-fixed-dim" : "text-on-surface-variant/20"
            }`}
            title={skill.locked ? "Platform Enforced" : "Unlocked"}
          >
            {skill.locked ? "lock" : "lock_open"}
          </span>
        </div>
      </div>
      {/* Display name (frontmatter-driven        </div>
      </div>
      {/* Display name (frontmatter-driven, operator-friendly) +
          canonical name (snake_case, model-facing). `skill.name` is the
          canonical identifier that the agent's chat-prompt sees and
          that skill-binding jobs reference, but it's NOT the operator-
          friendly label. Frontmatter `displayName` is what the card
          shows; the canonical name sits below in monospace as a
          subtitle so operators can still grep by it (helpful when
          troubleshooting "agent says it can't find the skill").
          The font sizing inverts the prior emphasis: displayName is
          the visual primary (text-lg in body font), name is
          secondary (text-xs in monospace under it). */}
      <h3 className="font-headline text-lg font-medium text-on-surface mb-0.5">
        {skill.displayName}
      </h3>
      <p className="font-mono text-xs text-on-surface-variant/60 mb-1">
        {skill.name}
      </p>
      <p className="text-xs font-label text-on-surface-variant uppercase tracking-widest mb-4">
        {cat.label}
      </p>
      <p className="text-sm text-on-surface-variant/70 line-clamp-2 mb-6">
        {skill.description}
      </p>
      {/* Footer */}
      <div className="flex justify-between items-center pt-4 border-t border-outline-variant/30">
        <span className="font-mono text-[10px] text-on-surface-variant/60 truncate">
          {skill.filePath}
        </span>
        <span className={`text-[10px] px-2 py-0.5 rounded ${src.className}`}>
          {src.label}
        </span>
      </div>
    </div>
  );
}

function SkillDetailPanel({
  skill,
  onClose,
  onDownload,
  onSave,
  onDelete,
}: {
  skill: SkillDef;
  onClose: () => void;
  // The detail panel hosts the per-skill CRUD actions.
  // Download is always available (even for locked skills — viewing
  // and saving locally doesn't mutate state). Save fires when the
  // operator edits the body textarea. Delete is gated by the locked
  // flag in the parent handler, but the button is still rendered
  // (disabled) for discoverability.
  onDownload: (skill: SkillDef) => void;
  onSave: (skill: SkillDef, content: string) => Promise<boolean>;
  onDelete: (skill: SkillDef) => void;
}) {
  const cat = CATEGORY_META[skill.category];

  // Local body state. The body auto-loads on panel mount (a lazy-load on
  // click/focus would leave the textarea showing a one-line
  // "See bundles/…" placeholder until you clicked into it, which reads
  // as broken). We hydrate the real MD body via skills_read immediately
  // when the detail panel opens and render a proper loading state in
  // place of the textarea while the fetch is in flight.
  //
  // - `bodyContent`     — the live MD body once loaded, or empty
  //                       string while loading or if the load fails.
  // - `loadState`       — "loading" | "loaded" | "error". Replaces
  //                       the older bodyLoaded + isLoading boolean
  //                       pair so the three rendering modes are an
  //                       explicit enum.
  // - `loadError`       — operator-facing message shown next to the
  //                       Retry button on `loadState === "error"`.
  // - `isSaving`, `dirty` — Save / unsaved-change tracking, unchanged.
  const [bodyContent, setBodyContent] = useState("");
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const loadBody = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const filePath = `${skill.category}/${skill.name}.md`;
      const res = await fetch(
        `/api/skills?file_path=${encodeURIComponent(filePath)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        setLoadError(`Server returned ${res.status}`);
        setLoadState("error");
        return;
      }
      const body = (await res.json()) as {
        success: boolean;
        content?: string;
        error?: string;
      };
      if (body.success && typeof body.content === "string") {
        setBodyContent(body.content);
        setLoadState("loaded");
        setDirty(false);
      } else {
        setLoadError(body.error || "Empty response from /api/skills");
        setLoadState("error");
      }
    } catch (err) {
      setLoadError(
        err instanceof Error
          ? err.message
          : "Network error reaching /api/skills",
      );
      setLoadState("error");
    }
  }, [skill.category, skill.name]);

  // Auto-load on mount (and whenever the panel switches to a
  // different skill — though today the parent unmounts + remounts
  // the panel for each selection, so the dependency change is just
  // belt-and-suspenders).
  useEffect(() => {
    void loadBody();
  }, [loadBody]);

  const isLoading = loadState === "loading";
  const bodyLoaded = loadState === "loaded";

  const saveBody = useCallback(async () => {
    if (!dirty || isSaving) return;
    setIsSaving(true);
    const ok = await onSave(skill, bodyContent);
    setIsSaving(false);
    if (ok) setDirty(false);
  }, [dirty, isSaving, onSave, skill, bodyContent]);

  // Closing with unsaved edits asks first (in-app dialog, not window.confirm).
  const requestClose = useCallback(async () => {
    if (dirty) {
      const discard = await confirmAction({
        title: "Discard unsaved changes?",
        message: "The edits in this skill have not been saved.",
        confirmLabel: "Discard",
        tone: "danger",
      });
      if (!discard) return;
    }
    onClose();
  }, [dirty, onClose]);

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-[2px] animate-[fadeIn_0.2s_ease-out]"
        onClick={() => void requestClose()}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 h-full w-[55%] z-50 shadow-[0_0_80px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col animate-[slideInRight_0.3s_ease-out]"
        style={panelStyle}
      >
        {/* Header */}
        <header className="p-8 pb-6 border-b border-white/5 shrink-0">
          <div className="flex items-start justify-between mb-6">
            <button
              onClick={() => void requestClose()}
              className="w-10 h-10 rounded-full flex items-center justify-center bg-white/5 hover:bg-white/10 transition-all active:scale-95 group"
              aria-label="Close panel"
            >
              <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary-fixed-dim">
                arrow_back
              </span>
            </button>
            {/* Per-skill CRUD action row. Download / Save /
                Delete sit between the back button and the category
                badges. Save is enabled only when the body is dirty.
                Delete is disabled-with-tooltip for locked skills. */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => onDownload(skill)}
                className="h-9 px-3 flex items-center gap-1.5 rounded-full bg-white/5 hover:bg-white/10 transition-all active:scale-95 text-xs font-medium text-on-surface-variant hover:text-on-surface"
                title="Download as .md file"
                aria-label={`Download ${skill.displayName}`}
              >
                <span className="material-symbols-outlined text-base">
                  download
                </span>
                Download
              </button>
              <button
                onClick={() => void saveBody()}
                disabled={!dirty || isSaving}
                className={`h-9 px-3 flex items-center gap-1.5 rounded-full transition-all text-xs font-medium ${
                  dirty && !isSaving
                    ? "bg-primary/20 hover:bg-primary/30 text-primary-fixed-dim active:scale-95"
                    : "bg-white/5 text-on-surface-variant/40 cursor-not-allowed"
                }`}
                title={
                  dirty
                    ? "Save body changes"
                    : "No unsaved changes"
                }
                aria-label="Save edits"
              >
                <span className="material-symbols-outlined text-base">
                  {isSaving ? "hourglass_empty" : "save"}
                </span>
                {isSaving ? "Saving…" : "Save"}
              </button>
              <button
                onClick={() => {
                  if (skill.locked) return;
                  onDelete(skill);
                }}
                disabled={skill.locked}
                className={`h-9 px-3 flex items-center gap-1.5 rounded-full transition-all text-xs font-medium ${
                  skill.locked
                    ? "bg-white/5 text-on-surface-variant/30 cursor-not-allowed"
                    : "bg-red-500/10 hover:bg-red-500/20 text-red-300 hover:text-red-200 active:scale-95"
                }`}
                title={
                  skill.locked
                    ? "Platform-locked — can't be deleted"
                    : "Soft-delete (recoverable from .deleted/)"
                }
                aria-label={`Delete ${skill.displayName}`}
              >
                <span className="material-symbols-outlined text-base">
                  delete
                </span>
                Delete
              </button>
            </div>
            <div className="flex gap-2">
              <span
                className={`px-3 py-1 ${cat.bg} ${cat.border} border rounded-full text-[10px] uppercase tracking-widest font-bold ${cat.color}`}
              >
                {cat.label}
              </span>
              <span className="px-3 py-1 border border-[#424751]/30 rounded-full text-[10px] uppercase tracking-widest font-bold text-on-surface-variant">
                {SOURCE_META[skill.source].label}
              </span>
            </div>
          </div>
          {/* Title color was `text-primary-fixed-dim` (#a7c8ff) which
              has the same value in both themes — bright/legible on the
              navy dark bg, but invisible on the pale-azure light bg.
              Switching to `text-on-surface` makes it theme-aware
              (dark navy on light, pale gray on dark). */}
          <h2 className="text-4xl font-headline font-bold mb-4 tracking-tight flex items-center gap-4">
            <span className="font-mono text-on-surface">{skill.name}</span>
            <span
              className={`material-symbols-outlined text-2xl ${cat.color}`}
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              {skill.icon}
            </span>
          </h2>
          <p className="text-on-surface-variant leading-relaxed max-w-2xl text-lg">
            {skill.description}
          </p>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8 space-y-12 custom-scrollbar">
          {/* Skill Content
              The body auto-loads on panel mount. While
              the fetch is in flight we render a centered loading
              card in place of the textarea (matching the panel's
              ghost-border + bg-surface-container-lowest style). On
              load failure we render an error card with a Retry
              button. Once loaded, the textarea takes over and the
              footer row shows char/token counts + dirty indicator. */}
          <section>
            <SectionHeader label="Skill Content" />
            <div className="relative">
              {isLoading ? (
                <div
                  className="w-full rounded-xl px-5 py-12 flex flex-col items-center justify-center gap-3 bg-surface-container-lowest"
                  style={ghostBorder}
                  role="status"
                  aria-live="polite"
                  aria-busy="true"
                >
                  <span className="material-symbols-outlined text-3xl text-primary-fixed-dim animate-spin">
                    progress_activity
                  </span>
                  <p className="text-sm text-on-surface-variant">
                    Loading skill content…
                  </p>
                  <p className="text-[11px] text-on-surface-variant/60 font-mono">
                    {skill.category}/{skill.name}.md
                  </p>
                </div>
              ) : loadState === "error" ? (
                <div
                  className="w-full rounded-xl px-5 py-10 flex flex-col items-center justify-center gap-3 bg-surface-container-lowest"
                  style={ghostBorder}
                  role="alert"
                >
                  <span className="material-symbols-outlined text-3xl text-error">
                    error
                  </span>
                  <p className="text-sm text-on-surface">
                    Couldn&apos;t load this skill&apos;s body.
                  </p>
                  {loadError && (
                    <p className="text-[11px] text-on-surface-variant/70 font-mono max-w-md text-center">
                      {loadError}
                    </p>
                  )}
                  <button
                    onClick={loadBody}
                    className="mt-1 text-xs text-primary-fixed-dim hover:underline font-medium"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <textarea
                  value={bodyContent}
                  onChange={(e) => {
                    setBodyContent(e.target.value);
                    setDirty(true);
                  }}
                  rows={16}
                  className="w-full bg-surface-container-lowest rounded-xl px-5 py-4 text-sm font-mono text-on-surface-variant leading-relaxed resize-none focus:ring-1 focus:ring-primary-fixed-dim/30 focus:outline-none"
                  style={ghostBorder}
                />
              )}
              <div className="flex items-center justify-between mt-2 px-1">
                <div className="flex items-center gap-4 text-[10px] text-on-surface-variant">
                  <span>
                    {bodyContent.length.toLocaleString()} chars
                  </span>
                  <span>~{Math.ceil(bodyContent.length / 4)} tokens</span>
                  {dirty && bodyLoaded && (
                    <span className="text-amber-300">
                      • Unsaved changes
                    </span>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* Properties — everything here is read from the skill's file and
              its frontmatter; nothing is a setting the agent consults. */}
          <section>
            <SectionHeader label="Properties" />
            <div className="grid grid-cols-1 gap-3">
              {[
                ["Category", CATEGORY_META[skill.category].label],
                ["Source", SOURCE_META[skill.source].label],
                ["File", skill.filePath],
                [
                  "Size",
                  `${skill.sizeBytes.toLocaleString()} bytes (about ${Math.ceil(skill.sizeBytes / 4).toLocaleString()} tokens)`,
                ],
                [
                  "Protection",
                  skill.locked ? "Locked: cannot be deleted from the UI" : "Not locked",
                ],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between p-4 bg-surface-container rounded-xl"
                  style={ghostBorder}
                >
                  <span className="text-sm text-on-surface-variant">{label}</span>
                  <span className="text-sm font-mono text-on-surface text-right break-all">{value}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Phantom is a single-tenant operator install: there is no
              workspace concept anywhere in the MCP, so there is no
              workspace assignment or override section. Skills are
              global to the install; Download, Save and Delete are in
              the header. */}
        </div>

        {/* Footer */}
        <footer className="p-6 border-t border-white/5 bg-surface-container-low/50 flex gap-4 shrink-0">
          <button
            onClick={() => void saveBody()}
            disabled={!dirty || isSaving}
            className="flex-1 py-4 bg-primary-container hover:bg-primary-container/80 text-on-primary-container font-headline font-bold rounded-xl transition-all shadow-lg shadow-primary-fixed-dim/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? "Saving…" : "Save Changes"}
          </button>
          <button
            onClick={() => void requestClose()}
            className="px-6 py-4 bg-surface-container-highest text-on-surface-variant font-headline font-bold rounded-xl transition-all hover:text-on-surface"
          >
            Close
          </button>
        </footer>
      </aside>
    </>
  );
}

// Convert a free-text display name into a deterministic snake_case
// filename. Used for auto-deriving the on-disk name as the operator
// types in the display-name field. Lowercase + non-alphanumeric →
// underscore + collapse runs + trim. We don't enforce uniqueness
// here — the backend rejects duplicates with a clear error.
function slugifyForFilename(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function CreateSkillPanel({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  // Creates skills. Returns
  // true on success so the parent can close us; we keep the
  // operator's draft visible on failure (alert is shown, panel
  // stays open for retry/edit).
  onCreate: (
    category: string,
    filename: string,
    content: string,
  ) => Promise<boolean>;
}) {
  const [contextPreviewOpen, setContextPreviewOpen] = useState(false);
  const [skillContent, setSkillContent] = useState("");
  // New fields required by the backend POST. Category is one of
  // foundation/scenarios/validation/workflows; filename is the .md
  // file name (we'll auto-append .md if missing). displayName is
  // optional but pre-fills the frontmatter so the new skill renders
  // with a label instead of falling back to the filename stem.
  const [createCategory, setCreateCategory] =
    useState<Exclude<CategoryKey, "all">>("scenarios");
  const [createFilename, setCreateFilename] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [creating, setCreating] = useState(false);

  // Compose the actual MD body that hits the backend. If the
  // operator left the optional fields blank we skip frontmatter
  // generation entirely — the backend will list the skill with
  // legacy heading-based display name and operators can add
  // frontmatter later via Edit.
  const handleCreate = useCallback(async () => {
    if (!createFilename.trim()) {
      notify("warning", "Filename is required.");
      return;
    }
    if (!skillContent.trim()) {
      notify("warning", "Skill content cannot be empty.");
      return;
    }
    let body = skillContent;
    if (createDisplayName.trim() || createDescription.trim()) {
      // Compose minimal frontmatter. We don't import yaml on the
      // client; we hand-build a YAML string. Strings are quoted
      // with single quotes to avoid issues with spaces.
      const fmLines = [
        `name: ${createFilename.replace(/\.md$/, "")}`,
        createDisplayName.trim() &&
          `displayName: ${JSON.stringify(createDisplayName.trim())}`,
        `category: ${createCategory}`,
        createDescription.trim() &&
          `description: ${JSON.stringify(createDescription.trim())}`,
        `source: workspace`,
        `locked: false`,
      ].filter(Boolean);
      body = `---\n${fmLines.join("\n")}\n---\n\n${skillContent}`;
    }
    setCreating(true);
    const ok = await onCreate(createCategory, createFilename, body);
    setCreating(false);
    if (ok) onClose();
  }, [
    createCategory,
    createDescription,
    createDisplayName,
    createFilename,
    onClose,
    onCreate,
    skillContent,
  ]);

  const charCount = skillContent.length;
  const tokenEstimate = Math.round(charCount / 2.6);

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed top-0 right-0 h-full w-[55%] z-50 flex flex-col shadow-2xl rounded-l-[2rem] overflow-hidden animate-[slideInRight_0.3s_ease-out]"
        style={panelStyle}
      >
        {/* Header */}
        <div className="px-8 pt-8 pb-6 border-b border-white/10 shrink-0">
          <div className="flex justify-between items-start">
            <div>
              <h2 className="text-3xl font-bold font-headline tracking-tight text-on-surface">
                Create Skill
              </h2>
              <p className="text-on-surface-variant text-sm mt-1">
                Add a new skill to the platform registry
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-full transition-colors text-on-surface-variant"
              aria-label="Close panel"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-8 py-8 space-y-12 custom-scrollbar">
          {/* Skill Identity */}
          <section className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-1 w-12 bg-[#a7c8ff] rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim">
                Skill Identity
              </span>
            </div>
            <div className="space-y-6">
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Display Name <span className="text-[#ffb4ab]">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. SQL Injection Scenario"
                  value={createDisplayName}
                  onChange={(e) => {
                    setCreateDisplayName(e.target.value);
                    // Auto-derive filename slug from display name —
                    // operators rarely care about the on-disk
                    // filename, and a deterministic slug avoids
                    // weird-character-in-filename errors. Only
                    // overwrites if the operator hasn't manually
                    // edited the filename field.
                    if (
                      !createFilename ||
                      createFilename ===
                        slugifyForFilename(createDisplayName)
                    ) {
                      setCreateFilename(slugifyForFilename(e.target.value));
                    }
                  }}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50"
                />
                <p className="text-[10px] text-on-surface-variant">
                  Operator-facing label shown on the card and in the chat agent&apos;s skill list.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Filename <span className="text-[#ffb4ab]">*</span>
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="sql_injection_scenario"
                    value={createFilename}
                    onChange={(e) => setCreateFilename(e.target.value)}
                    className="flex-1 bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm font-mono focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50"
                  />
                  <span className="text-xs text-on-surface-variant font-mono">.md</span>
                </div>
                <p className="text-[10px] text-on-surface-variant">
                  Canonical identifier used by the chat agent. Auto-derived from display name; edit if you need a different on-disk name.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Category
                </label>
                <div className="relative">
                  <div className="absolute left-4 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-[#a7c8ff]" />
                  <select
                    value={createCategory}
                    onChange={(e) =>
                      setCreateCategory(
                        e.target.value as Exclude<CategoryKey, "all">,
                      )
                    }
                    className="w-full bg-surface-container-highest border-none rounded-xl pl-9 pr-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface appearance-none"
                  >
                    <option value="foundation">Foundation</option>
                    <option value="scenarios">Scenarios</option>
                    <option value="validation">Validation</option>
                    <option value="workflows">Workflows</option>
                  </select>
                  <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 text-on-surface-variant pointer-events-none">
                    expand_more
                  </span>
                </div>
                <p className="text-[10px] text-on-surface-variant">
                  Determines which directory the MD file lands in under <code>bundles/spark/mcp/skills/</code>.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Description
                </label>
                <textarea
                  rows={3}
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="One-line summary the chat agent will see in <available_skills>. Be concise and specific — this is what the model uses to decide whether to apply the skill."
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50 resize-none"
                />
              </div>
            </div>
          </section>

          {/* Skill Content */}
          <section className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-1 w-12 bg-[#a7c8ff] rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim">
                Skill Content
              </span>
            </div>
            <div>
              <textarea
                rows={16}
                value={skillContent}
                onChange={(e) => setSkillContent(e.target.value)}
                placeholder="Enter the skill content that will be injected into the agent's context..."
                className="w-full bg-surface-container-lowest rounded-xl px-5 py-4 text-sm font-mono text-on-surface-variant leading-relaxed resize-none focus:ring-1 focus:ring-primary-fixed-dim/30 focus:outline-none"
                style={ghostBorder}
              />
              <div className="flex items-center justify-between mt-2 px-1">
                <div className="flex items-center gap-4 text-[10px] text-on-surface-variant">
                  <span>{charCount.toLocaleString()} / 20,000 chars</span>
                  <span>~{tokenEstimate} tokens</span>
                </div>
                <button className="text-[10px] text-primary-fixed-dim hover:underline font-medium">
                  Preview
                </button>
              </div>
            </div>
          </section>

          {/* Context Preview (Collapsible) */}
          <section className="space-y-4 pb-4">
            <button
              onClick={() => setContextPreviewOpen(!contextPreviewOpen)}
              className="flex items-center gap-3 w-full text-left"
            >
              <div className="h-1 w-12 bg-[#a7c8ff]/50 rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim/60">
                Context Preview
              </span>
              <span className="material-symbols-outlined text-sm text-on-surface-variant/40 ml-auto">
                {contextPreviewOpen ? "expand_less" : "expand_more"}
              </span>
            </button>
            {contextPreviewOpen && (
              <div
                className="bg-surface-container-lowest rounded-xl p-5 text-xs font-mono text-on-surface-variant/60 leading-relaxed"
                style={ghostBorder}
              >
                {skillContent ? (
                  <pre className="whitespace-pre-wrap">{skillContent}</pre>
                ) : (
                  <p className="text-on-surface-variant/50 italic">
                    Enter skill content above to see how it will appear in the agent context.
                  </p>
                )}
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <footer className="bg-surface-container-low px-8 py-6 flex items-center justify-between border-t border-white/5 shrink-0">
          <span className="text-[10px] text-on-surface-variant/60 italic">
            {creating
              ? "Creating skill on the agent…"
              : "All fields can be modified after creation"}
          </span>
          <div className="flex items-center gap-4">
            <button
              onClick={onClose}
              disabled={creating}
              className="px-6 py-2.5 text-sm font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={creating || !createFilename.trim() || !skillContent.trim()}
              className="flex items-center gap-2 px-8 py-2.5 bg-gradient-to-r from-[#1963b3] to-[#2D8DF0] text-on-surface rounded-xl font-bold font-headline shadow-lg shadow-[#a7c8ff]/20 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <span className="material-symbols-outlined text-sm">
                {creating ? "hourglass_empty" : "add"}
              </span>
              {creating ? "Creating…" : "Create Skill"}
            </button>
          </div>
        </footer>
      </div>
    </>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

// ─── Live → SkillDef mapping ────────────────────────────────────────────────

// Shape returned by GET /api/skills (skills_list_all on the MCP). Keys
// match `skills_crud.py::get_all_skills` after the frontmatter
// migration; skills without frontmatter fall through with empty
// strings and we apply defaults below.
interface LiveSkillRow {
  name: string;
  displayName?: string;
  category: string;
  description?: string;
  icon?: string;
  source?: string;
  locked?: boolean;
  attack?: string[];
  filename: string;
  file_path: string;
  size_bytes?: number;
  modified?: number;
  has_frontmatter?: boolean;
  // Present only on plugin-contributed skills (those
  // discovered under plugins/<vendor>/*.md). Surfaces vendor
  // attribution to the UI without forcing the row's main category
  // off the standard four built-in categories.
  plugin_vendor?: string;
}

// Sensible defaults for a skill row missing frontmatter — keeps the
// card render-safe even before an operator migrates an old skill.
function liveRowToSkillDef(row: LiveSkillRow): SkillDef {
  // `plugins` joins the four built-in categories.
  // Backend surfaces plugin-contributed skills under
  // plugins/<vendor>/*.md with category="plugins" and a
  // `plugin_vendor` field on the row. Anything else (malformed
  // category in frontmatter, future categories not yet known to the
  // UI) still defaults to "scenarios" rather than crashing the
  // render — better to mis-bucket than to break the page.
  const category = (
    ["foundation", "scenarios", "validation", "workflows", "plugins"].includes(
      row.category,
    )
      ? row.category
      : "scenarios"
  ) as Exclude<CategoryKey, "all">;

  return {
    id: `${category}-${row.name}`,
    name: row.name,
    displayName: row.displayName || row.name,
    category,
    description:
      row.description ||
      "(No description in frontmatter. Edit the skill MD to add one.)",
    icon: row.icon || "extension",
    source: ((row.source as SourceType) || "platform"),
    locked: Boolean(row.locked),
    filePath: row.file_path,
    sizeBytes: row.size_bytes || 0,
  };
}

export default function SkillsPage() {
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<SkillDef | null>(null);
  const [showCreatePanel, setShowCreatePanel] = useState(false);

  // Skills are loaded live from /api/skills (which calls the MCP's
  // skills_list_all); the on-disk skills directory is the only source, so a
  // skill that is added, edited or removed on disk shows up here without a
  // code change.
  const [skills, setSkills] = useState<SkillDef[]>([]);
  const [liveLoadStatus, setLiveLoadStatus] = useState<
    "loading" | "live" | "error"
  >("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/skills", { cache: "no-store" });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const body = (await res.json()) as {
          success?: boolean;
          skills?: LiveSkillRow[];
        };
        if (cancelled) return;
        if (Array.isArray(body.skills)) {
          setSkills(body.skills.map(liveRowToSkillDef));
          setLiveLoadStatus("live");
        } else {
          setLiveLoadStatus("error");
        }
      } catch {
        if (!cancelled) setLiveLoadStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ─── CRUD handlers ─────────────────────────────
  // All four backend operations (skills_create / skills_read /
  // skills_update / skills_delete) already exist as MCP tools and
  // are surfaced through the /api/skills route handler. This is just
  // the UI plumbing that calls them.
  //
  // The shape we send/receive:
  //   GET    /api/skills                        → list (used at mount)
  //   GET    /api/skills?file_path=foo.md       → read body content
  //   POST   /api/skills {category,filename,content}  → create
  //   PUT    /api/skills {file_path,content}    → update body
  //   DELETE /api/skills?file_path=foo.md       → soft-delete (.deleted/)
  //
  // After any write op we re-fetch the list so the page reflects the
  // new state. We don't optimistically update — the server is the
  // source of truth, especially since soft-delete + backup-on-update
  // means there's filesystem state we want to round-trip through.

  const refetchSkills = useCallback(async () => {
    try {
      const res = await fetch("/api/skills", { cache: "no-store" });
      if (!res.ok) return;
      const body = (await res.json()) as { skills?: LiveSkillRow[] };
      if (Array.isArray(body.skills)) {
        setSkills(body.skills.map(liveRowToSkillDef));
        setLiveLoadStatus("live");
      }
    } catch {
      // Network blip — leave the existing array in place rather than
      // wiping it. Next interaction will retry.
    }
  }, []);

  const handleDownloadSkill = useCallback(async (skill: SkillDef) => {
    // Fetch the live MD body, then trigger a browser download. The
    // file_path on the skill points back at the canonical location
    // under bundles/spark/mcp/skills/<category>/<filename>.md.
    const filePath = `${skill.category}/${skill.name}.md`;
    try {
      const res = await fetch(
        `/api/skills?file_path=${encodeURIComponent(filePath)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        notify("error", `Download failed: ${res.status}`);
        return;
      }
      const body = (await res.json()) as {
        success: boolean;
        content?: string;
        error?: string;
      };
      if (!body.success || !body.content) {
        notify("error", body.error || "Download failed: empty response");
        return;
      }
      const blob = new Blob([body.content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${skill.name}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      notify("error", `Download failed: ${err instanceof Error ? err.message : err}`);
    }
  }, []);

  const handleSaveSkill = useCallback(
    async (skill: SkillDef, newContent: string) => {
      // Update existing skill body via PUT. Backend creates a
      // .md.bak before overwriting, so manual rollback is one
      // shell command if the operator regrets the edit.
      const filePath = `${skill.category}/${skill.name}.md`;
      try {
        const res = await fetch("/api/skills", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: filePath, content: newContent }),
        });
        const body = (await res.json()) as {
          success: boolean;
          message?: string;
          error?: string;
        };
        if (!res.ok || !body.success) {
          notify("error", body.error || `Save failed: ${res.status}`);
          return false;
        }
        await refetchSkills();
        return true;
      } catch (err) {
        notify("error", `Save failed: ${err instanceof Error ? err.message : err}`);
        return false;
      }
    },
    [refetchSkills],
  );

  const handleDeleteSkill = useCallback(
    async (skill: SkillDef) => {
      if (skill.locked) {
        notify("warning", `"${skill.displayName}" is platform-locked and can't be deleted.`);
        return;
      }
      const ok = await confirmAction({
        title: `Delete skill "${skill.displayName}"?`,
        message:
          "The MD file moves to /app/skills/.deleted/ on the server (recoverable via docker cp / docker exec), but it disappears from the agent's skill registry immediately.",
        confirmLabel: "Delete",
        tone: "danger",
      });
      if (!ok) return;
      const filePath = `${skill.category}/${skill.name}.md`;
      try {
        const res = await fetch(
          `/api/skills?file_path=${encodeURIComponent(filePath)}`,
          { method: "DELETE" },
        );
        const body = (await res.json()) as {
          success: boolean;
          error?: string;
        };
        if (!res.ok || !body.success) {
          notify("error", body.error || `Delete failed: ${res.status}`);
          return;
        }
        // Close the detail panel + refresh the list.
        setSelectedSkill(null);
        await refetchSkills();
      } catch (err) {
        notify("error", `Delete failed: ${err instanceof Error ? err.message : err}`);
      }
    },
    [refetchSkills],
  );

  const handleCreateSkill = useCallback(
    async (
      category: string,
      filename: string,
      content: string,
    ): Promise<boolean> => {
      // Ensure .md suffix — the backend rejects without it. We could
      // strip + re-add, but it's cleaner to require operators name
      // their file the way it'll be saved.
      if (!filename.endsWith(".md")) filename += ".md";
      try {
        const res = await fetch("/api/skills", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, filename, content }),
        });
        const body = (await res.json()) as {
          success: boolean;
          error?: string;
        };
        if (!res.ok || !body.success) {
          notify("error", body.error || `Create failed: ${res.status}`);
          return false;
        }
        await refetchSkills();
        return true;
      } catch (err) {
        notify("error", `Create failed: ${err instanceof Error ? err.message : err}`);
        return false;
      }
    },
    [refetchSkills],
  );

  const filteredSkills = useMemo(() => {
    let result = [...skills];
    if (categoryFilter !== "all") {
      result = result.filter((s) => s.category === categoryFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.displayName.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q)
      );
    }
    return result;
  }, [skills, categoryFilter, searchQuery]);

  // Summary widgets derive from the LIVE skills array, so they cannot
  // drift from what /api/skills returns.
  const summaryStats = useMemo(() => {
    const categories = new Set(skills.map((s) => s.category));
    return {
      total: skills.length,
      categories: categories.size,
    };
  }, [skills]);

  // Chip counts come from the same array the grid filters, so "(N)" on a
  // chip is exactly the number of cards that chip shows (before the search
  // box narrows them).
  const categoryCounts = useMemo(() => {
    const counts: Record<CategoryKey, number> = {
      all: skills.length,
      foundation: 0,
      scenarios: 0,
      validation: 0,
      workflows: 0,
      plugins: 0,
    };
    for (const s of skills) counts[s.category] += 1;
    return counts;
  }, [skills]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-8">
        {/* ── Page Header ──────────────────────────────────── */}
        {/* Standardized to the jobs-style pattern (icon + title +
            subtitle, no breadcrumb). Drops the previous
            Runtime > Skills navigation flow which was inconsistent
            with every other page. */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                auto_awesome
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Skills
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Browse, edit and create the skills the agent can apply.
            </p>
          </div>
          {/* Phantom is a single-tenant agent install; there's no
              workspace concept here, so the header carries just the
              operator-actionable affordances: Import + Create. */}
          <div className="flex items-center gap-4">
            <ImportSkillButton onImported={refetchSkills} />
            <button
              onClick={() => setShowCreatePanel(true)}
              className="text-white px-6 py-2.5 rounded-xl font-bold font-headline flex items-center gap-2 shadow-[0px_20px_40px_rgba(25,99,179,0.15)] active:scale-95 transition-transform"
              style={{
                background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
              }}
            >
              <span className="material-symbols-outlined text-lg">add</span>
              Create Skill
            </button>
          </div>
        </header>

        {/* ── Summary Strip — horizontal layout (icon left, number+
            caption right). Replaces the vertical stacked layout
            where the number sat below the icon on a new line.
            Theme-aware tints (bg-primary/15 instead of hardcoded
            rgba) so the icon backgrounds reflow on theme switch. */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-primary/15 flex items-center justify-center text-primary shrink-0">
              <span className="material-symbols-outlined">auto_awesome</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Total Skills
              </p>
              <p className="text-2xl font-bold font-headline text-on-surface">
                {summaryStats.total}
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                {SUMMARY_CAPTIONS.totalCaption}
              </p>
            </div>
          </div>
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-tertiary/15 flex items-center justify-center text-tertiary shrink-0">
              <span className="material-symbols-outlined">category</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Categories
              </p>
              <p className="text-2xl font-bold font-headline text-tertiary">
                {summaryStats.categories}
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                Skill taxonomies
              </p>
            </div>
          </div>
        </section>

        {/* ── Filter Bar ─────────────────────────────────────
            Theme-aware bg + text. The pill row was hardcoded
            bg-surface-container-low with on-surface-variant text — fine in dark
            mode, invisible in light (dark text on dark pill).
            Switched to bg-surface-container-low (CSS-var driven) +
            text-on-surface-variant for the inactive state, secondary
            (green) for the active chip — matches the rest of the
            app's "active = green" rule. */}
        <section className="flex flex-col md:flex-row gap-6 items-center justify-between">
          <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-surface-container-low border border-outline-variant/30">
            {CATEGORY_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setCategoryFilter(f.key)}
                className={`px-5 py-2 rounded-xl text-sm font-medium transition-colors ${
                  categoryFilter === f.key
                    ? "bg-secondary-container/40 text-secondary font-bold"
                    : "text-on-surface hover:bg-surface-container-high"
                }`}
              >
                {f.label} ({categoryCounts[f.key]})
              </button>
            ))}
          </div>
          <div className="relative w-full md:w-80">
            <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-on-surface-variant">
              search
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search skills..."
              className="w-full bg-surface-container-low py-3 pl-12 pr-4 rounded-xl border border-outline-variant/30 focus:border-primary focus:ring-0 text-sm text-on-surface placeholder:text-on-surface-variant/60"
            />
          </div>
        </section>

        {/* ── Skill Grid ────────────────────────────────────── */}
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredSkills.map((skill) => (
            <SkillCard
              key={skill.id}
              skill={skill}
              onSelect={() => setSelectedSkill(skill)}
            />
          ))}
          {filteredSkills.length === 0 && liveLoadStatus === "loading" && (
            <p className="col-span-3 py-16 text-center text-sm text-on-surface-variant">
              Loading skills…
            </p>
          )}
          {filteredSkills.length === 0 && liveLoadStatus === "error" && (
            <div className="col-span-3 flex flex-col items-center justify-center py-16 text-center">
              <span className="material-symbols-outlined text-4xl text-error/60 mb-3">
                error
              </span>
              <p className="text-sm font-bold text-on-surface-variant">
                Could not load the skills list
              </p>
              <button
                onClick={() => void refetchSkills()}
                className="text-xs font-bold text-primary-fixed-dim hover:underline mt-2"
              >
                Try again
              </button>
            </div>
          )}
          {filteredSkills.length === 0 && liveLoadStatus === "live" && (
            <div className="col-span-3 flex flex-col items-center justify-center py-16 text-center">
              <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">
                search_off
              </span>
              <p className="text-sm font-bold text-on-surface-variant">
                {skills.length === 0
                  ? "No skills installed yet"
                  : "No skills match your filter"}
              </p>
              {skills.length > 0 && (
                <button
                  onClick={() => {
                    setCategoryFilter("all");
                    setSearchQuery("");
                  }}
                  className="text-xs font-bold text-primary-fixed-dim hover:underline mt-2"
                >
                  Clear filters
                </button>
              )}
            </div>
          )}
        </section>
      </div>

      {/* ── Skill Detail Panel ──────────────────────────────── */}
      {selectedSkill && (
        <SkillDetailPanel
          skill={selectedSkill}
          onClose={() => setSelectedSkill(null)}
          onDownload={handleDownloadSkill}
          onSave={handleSaveSkill}
          onDelete={handleDeleteSkill}
        />
      )}

      {/* ── Create Skill Panel ────────────────────────────── */}
      {showCreatePanel && (
        <CreateSkillPanel
          onClose={() => setShowCreatePanel(false)}
          onCreate={handleCreateSkill}
        />
      )}

      {/* ── Animations ─────────────────────────────────────── */}
      <style jsx>{`
        @keyframes slideInRight {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes fadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(140, 145, 157, 0.2);
          border-radius: 10px;
        }
      `}</style>
    </div>
  );
}
