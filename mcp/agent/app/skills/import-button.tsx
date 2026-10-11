"use client";

/**
 * Import Skill button — sibling to "Create Skill" on /skills.
 *
 * Accepts a `.md` file with optional YAML frontmatter (the
 * skills format) and POSTs to /api/skills with the category + filename
 * + content the backend's `skills_create` MCP tool expects.
 *
 * Operator workflow:
 *   - Click Import → file picker
 *   - Pick a .md file → frontmatter parsed client-side to extract
 *     `category` (defaults to "scenarios" if frontmatter is missing
 *     or doesn't include the field — the backend rejects unknown
 *     categories with a clear error in that case)
 *   - POST as a fresh skill (we don't merge with an existing skill
 *     of the same name; the backend errors with "skill already
 *     exists" and the operator either renames the file or deletes
 *     the old one first)
 *   - On success, the parent calls `onImported()` to refetch the
 *     live skills list so the new card appears immediately
 *
 * The shape lines up 1:1 with the equivalent `import-button.tsx`
 * for jobs — same disabled-while-busy + toast UX.
 */

import { useCallback, useRef, useState } from "react";

import { useNotificationsStore } from "@/lib/stores/notifications";

const VALID_CATEGORIES = new Set([
  "foundation",
  "scenarios",
  "validation",
  "workflows",
]);

// Minimal client-side frontmatter parser — same regex shape as the
// Python `_FRONTMATTER_RE` in skills_crud.py. We don't ship a YAML
// library to the client just for this; the only fields we care about
// (category, name) are simple `key: value` lines, so a per-line
// regex is sufficient.
function parseFrontmatter(content: string): {
  fm: Record<string, string>;
  body: string;
} {
  const FRONTMATTER_RE = /^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/;
  const match = content.match(FRONTMATTER_RE);
  if (!match) return { fm: {}, body: content };
  const fmText = match[1];
  const body = match[2];
  const fm: Record<string, string> = {};
  for (const rawLine of fmText.split("\n")) {
    const line = rawLine.trim();
    // Skip blank lines + list-continuation lines (start with `-` or
    // 2+ spaces). We only care about top-level scalar fields here.
    if (!line || line.startsWith("-") || /^[ \t]+/.test(rawLine)) continue;
    const colonIdx = line.indexOf(":");
    if (colonIdx <= 0) continue;
    const key = line.slice(0, colonIdx).trim();
    let value = line.slice(colonIdx + 1).trim();
    // Strip surrounding quotes if present
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    fm[key] = value;
  }
  return { fm, body };
}

interface ImportSkillButtonProps {
  /** Called after a successful import so the parent can refresh the
   *  live skills list (the new skill should appear in the grid
   *  immediately, not after a manual reload). */
  onImported: () => void | Promise<void>;
}

export function ImportSkillButton({ onImported }: ImportSkillButtonProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const addToast = useNotificationsStore((s) => s.addToast);

  const handleClick = useCallback(() => {
    if (busy) return;
    inputRef.current?.click();
  }, [busy]);

  const handleFile = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const inputEl = event.currentTarget;
      const file = inputEl.files?.[0];
      if (!file) return;
      // Reset the input so re-importing the same file (e.g. after a
      // failed first attempt) re-fires the change event.
      inputEl.value = "";

      setBusy(true);
      try {
        const text = await file.text();
        const { fm } = parseFrontmatter(text);

        // Resolve filename: prefer frontmatter `name` (operator-set
        // canonical id) → fall back to the actual filename → final
        // fallback "imported_skill". Always ensure .md suffix.
        let filename =
          (fm.name && fm.name.trim()) ||
          file.name.replace(/\.md$/, "") ||
          "imported_skill";
        if (!filename.endsWith(".md")) filename = `${filename}.md`;

        // Resolve category from frontmatter; default to "scenarios"
        // if missing or unknown. The backend re-validates so an
        // operator-typed garbage category surfaces a clean error.
        const fmCategory = (fm.category || "").trim().toLowerCase();
        const category = VALID_CATEGORIES.has(fmCategory)
          ? fmCategory
          : "scenarios";

        const res = await fetch("/api/skills", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category,
            filename,
            content: text,
          }),
        });
        const body = (await res.json()) as {
          success: boolean;
          error?: string;
          path?: string;
        };
        if (!res.ok || !body.success) {
          addToast({
            variant: "error",
            title: "Import failed",
            description:
              body.error ||
              `Server returned ${res.status}. The MD file may already exist (rename and re-import) or have invalid frontmatter.`,
          });
          return;
        }
        addToast({
          variant: "success",
          title: `Imported skill "${filename.replace(/\.md$/, "")}"`,
          description: `Saved to bundles/spark/mcp/skills/${category}/. The chat agent picks it up on the next turn.`,
        });
        await onImported();
      } catch (err) {
        addToast({
          variant: "error",
          title: "Import failed",
          description:
            err instanceof Error
              ? err.message
              : "Could not read the file or reach /api/skills.",
        });
      } finally {
        setBusy(false);
      }
    },
    [addToast, onImported],
  );

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".md,text/markdown"
        onChange={handleFile}
        className="hidden"
        aria-label="Import skill from .md file"
      />
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-on-surface text-sm font-medium hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          border: "0.5px solid var(--glass-border)",
        }}
        title="Import a skill from a .md file (with optional YAML frontmatter)"
      >
        {busy ? (
          <>
            <span className="material-symbols-outlined text-lg animate-spin">
              progress_activity
            </span>
            Importing…
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-lg">upload</span>
            Import
          </>
        )}
      </button>
    </>
  );
}
