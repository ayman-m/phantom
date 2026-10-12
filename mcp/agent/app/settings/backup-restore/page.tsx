/**
 * Backup & Restore — operator-facing page for downloading
 * a complete-state zip and restoring from one.
 *
 * Three sections:
 *   1. Backup — single button that triggers the zip download. Below
 *      it, a list of what the zip contains + the cleartext-secrets
 *      warning so the operator knows the file is sensitive.
 *   2. Restore — two-step flow: upload zip → preview manifest +
 *      section counts via dry_run=true → click Apply to commit.
 *   3. Caveats — non-obvious behaviors (memory embeddings stripped,
 *      knowledge bundles read-only, manifest jobs skipped, etc).
 *
 * All writes go through /api/agent/restore which auth-gates via the
 * phantom_session cookie at middleware.ts. Multipart upload
 * is browser-native (FormData).
 */

"use client";

import { useState } from "react";

import { useNotificationsStore } from "@/lib/stores/notifications";

const glassPanel: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.05)",
};

interface RestoreManifest {
  schema_version?: number;
  phantom_version?: string;
  created_at?: string;
  sections?: string[];
  section_counts?: Record<string, number>;
  warning?: string;
  restore_notes?: string[];
}

interface DryRunResponse {
  dry_run: true;
  manifest: RestoreManifest;
  sections_present: Record<string, number | boolean>;
  restore_order: string[];
  force: boolean;
}

interface ApplyResponse {
  ok: boolean;
  dry_run: false;
  force: boolean;
  schema_version?: number;
  backed_up_from?: string;
  applied: Record<string, number>;
  skipped: Record<string, number>;
  errors: string[];
  warnings: string[];
}

export default function BackupRestorePage() {
  const addToast = useNotificationsStore((s) => s.addToast);

  // ── Backup state ─────────────────────────────────────────────────
  const [downloading, setDownloading] = useState(false);

  // ── Restore state ────────────────────────────────────────────────
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<DryRunResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<ApplyResponse | null>(null);

  async function handleDownload() {
    setDownloading(true);
    try {
      const r = await fetch("/api/agent/backup", { cache: "no-store" });
      if (!r.ok) {
        const detail = await r.text();
        throw new Error(
          `Server returned ${r.status}: ${detail.slice(0, 200)}`,
        );
      }
      const blob = await r.blob();
      // Pull filename from Content-Disposition; fall back to a stamp.
      let filename = "phantom-backup.zip";
      const cd = r.headers.get("content-disposition");
      if (cd) {
        const m = cd.match(/filename="?([^"]+)"?/);
        if (m) filename = m[1];
      }
      // Trigger save via temp <a>.
      const a = document.createElement("a");
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      addToast({
        variant: "success",
        title: "Backup downloaded",
        description: `${filename} (${(blob.size / 1024).toFixed(0)} KB). Treat as sensitive — contains plaintext secrets.`,
      });
    } catch (err) {
      addToast({
        variant: "error",
        title: "Backup failed",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDownloading(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setPreview(null);
    setResult(null);
  }

  async function handlePreview() {
    if (!file) return;
    setPreviewing(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/agent/restore?dry_run=true", {
        method: "POST",
        body: fd,
      });
      const data = (await r.json()) as DryRunResponse | { error: string };
      if (!r.ok || "error" in data) {
        throw new Error(
          ("error" in data ? data.error : null) ??
            `Server returned ${r.status}`,
        );
      }
      setPreview(data);
    } catch (err) {
      addToast({
        variant: "error",
        title: "Could not parse zip",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPreviewing(false);
    }
  }

  async function handleApply() {
    if (!file) return;
    setApplying(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const url = force ? "/api/agent/restore?force=true" : "/api/agent/restore";
      const r = await fetch(url, { method: "POST", body: fd });
      const data = (await r.json()) as ApplyResponse | { error: string };
      if (!r.ok || "error" in data) {
        throw new Error(
          ("error" in data ? data.error : null) ??
            `Server returned ${r.status}`,
        );
      }
      setResult(data);
      const totalApplied = Object.values(data.applied || {}).reduce(
        (a, b) => a + b,
        0,
      );
      addToast({
        variant: data.ok ? "success" : "warning",
        title: data.ok ? "Restore complete" : "Restore completed with errors",
        description: `Applied ${totalApplied} entries across ${Object.keys(
          data.applied || {},
        ).length} sections.${
          data.errors?.length ? ` ${data.errors.length} error(s).` : ""
        }`,
      });
    } catch (err) {
      addToast({
        variant: "error",
        title: "Restore failed",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setApplying(false);
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setResult(null);
    setForce(false);
  }

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Header — matches /skills layout pattern */}
        <header>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary">
              backup
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
              Backup &amp; Restore
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9">
            Download or restore a complete-state snapshot of your Phantom deployment.
          </p>
        </header>

      {/* ───────────────────── BACKUP ───────────────────── */}
      <section className="rounded-2xl p-8 space-y-5" style={glassPanel}>
        <div>
          <h2 className="font-headline font-semibold text-lg text-on-surface">
            Download backup
          </h2>
          <p className="text-xs text-on-surface-variant/70 mt-1">
            One zip with all operator-owned state. Hit the button — your
            browser saves the file.
          </p>
        </div>

        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="px-5 py-2.5 rounded-xl bg-primary text-on-primary text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-[18px]">
            {downloading ? "hourglass_top" : "download"}
          </span>
          {downloading ? "Building zip…" : "Download backup (.zip)"}
        </button>

        <div className="text-xs text-on-surface-variant/80 space-y-2 pt-2 border-t border-white/5">
          <p>
            <strong className="text-on-surface">Contents:</strong> personality
            blob, connector instances + cleartext secrets, memory entries
            (without embeddings), runtime job definitions, all skill MD
            files, knowledge bundle docs, and your workflow state (journeys
            marked tested, saved metric bookmarks). Manifest jobs are NOT
            included — they reseed from manifest.yaml at boot.
          </p>
          <p className="text-warning">
            <span className="material-symbols-outlined text-[14px] align-text-bottom mr-1">
              warning
            </span>
            <strong>The zip contains plaintext API keys and webhook
            secrets.</strong>{" "}
            Do not commit it to version control or share over unencrypted
            channels.
          </p>
        </div>
      </section>

      {/* ───────────────────── RESTORE ───────────────────── */}
      <section className="rounded-2xl p-8 space-y-5" style={glassPanel}>
        <div>
          <h2 className="font-headline font-semibold text-lg text-on-surface">
            Restore from backup
          </h2>
          <p className="text-xs text-on-surface-variant/70 mt-1">
            Upload a phantom-backup-*.zip. Preview what would land, then
            click Apply.
          </p>
        </div>

        {/* Step 1: file picker */}
        <div className="space-y-2">
          <label
            htmlFor="backup-file"
            className="block text-xs font-medium uppercase tracking-wider text-on-surface-variant/80"
          >
            Backup file
          </label>
          <input
            id="backup-file"
            type="file"
            accept=".zip,application/zip"
            onChange={handleFileChange}
            disabled={previewing || applying}
            className="block w-full text-sm text-on-surface-variant/90 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-surface-container-highest file:text-on-surface hover:file:bg-surface-container"
          />
          {file && (
            <p className="text-xs text-on-surface-variant/70">
              Selected: {file.name} ({(file.size / 1024).toFixed(0)} KB)
            </p>
          )}
        </div>

        {/* Step 2: preview button */}
        {file && !preview && (
          <button
            type="button"
            onClick={handlePreview}
            disabled={previewing}
            className="px-5 py-2.5 rounded-xl bg-surface-container-highest text-on-surface text-sm font-medium hover:bg-surface-container transition-colors disabled:opacity-50 inline-flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">
              {previewing ? "hourglass_top" : "preview"}
            </span>
            {previewing ? "Parsing zip…" : "Preview restore plan"}
          </button>
        )}

        {/* Step 3: preview + apply */}
        {preview && (
          <div className="space-y-4 border-t border-white/5 pt-5">
            <div>
              <h3 className="text-sm font-medium text-on-surface">
                Restore plan
              </h3>
              <p className="text-xs text-on-surface-variant/70">
                Backed up from Phantom v
                {preview.manifest?.phantom_version || "unknown"} on{" "}
                {preview.manifest?.created_at?.slice(0, 19) || "unknown"}
              </p>
            </div>
            <ul className="text-sm text-on-surface-variant/90 space-y-1.5 font-mono">
              {Object.entries(preview.sections_present).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className="text-on-surface">
                    {typeof v === "boolean"
                      ? v
                        ? "✓ present"
                        : "— absent"
                      : `${v} entries`}
                  </span>
                </li>
              ))}
            </ul>

            <label className="flex items-center gap-2 text-sm text-on-surface-variant/90 pt-2">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                disabled={applying}
                className="rounded"
              />
              <span>
                Overwrite existing entries (force)
                <span className="block text-xs text-on-surface-variant/60">
                  Without this, name collisions are skipped. Personality is
                  always overwritten regardless.
                </span>
              </span>
            </label>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={handleApply}
                disabled={applying}
                className="px-5 py-2.5 rounded-xl bg-primary text-on-primary text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50 inline-flex items-center gap-2"
              >
                <span className="material-symbols-outlined text-[18px]">
                  {applying ? "hourglass_top" : "restore"}
                </span>
                {applying ? "Applying…" : "Apply restore"}
              </button>
              <button
                type="button"
                onClick={reset}
                disabled={applying}
                className="px-5 py-2.5 rounded-xl bg-surface-container-highest text-on-surface-variant/90 text-sm font-medium hover:bg-surface-container transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Step 4: result */}
        {result && (
          <div className="space-y-3 border-t border-white/5 pt-5">
            <h3 className="text-sm font-medium text-on-surface">
              Restore result
            </h3>
            <ul className="text-sm text-on-surface-variant/90 space-y-1.5 font-mono">
              {Object.entries(result.applied || {}).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className="text-success">
                    {v} applied
                    {result.skipped?.[k]
                      ? `, ${result.skipped[k]} skipped`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
            {result.warnings?.length > 0 && (
              <div className="bg-warning/10 border border-warning/30 rounded-lg p-3 text-xs text-on-surface-variant/90 space-y-1">
                <p className="font-medium text-warning">Warnings</p>
                {result.warnings.map((w, i) => (
                  <p key={i} className="font-mono">
                    • {w}
                  </p>
                ))}
              </div>
            )}
            {result.errors?.length > 0 && (
              <div className="bg-error/10 border border-error/30 rounded-lg p-3 text-xs text-on-surface-variant/90 space-y-1">
                <p className="font-medium text-error">Errors</p>
                {result.errors.map((e, i) => (
                  <p key={i} className="font-mono">
                    • {e}
                  </p>
                ))}
              </div>
            )}
            <button
              type="button"
              onClick={reset}
              className="px-5 py-2.5 rounded-xl bg-surface-container-highest text-on-surface-variant/90 text-sm font-medium hover:bg-surface-container transition-colors"
            >
              Done — clear and restore another
            </button>
          </div>
        )}
      </section>

      {/* ───────────────────── CAVEATS ───────────────────── */}
      <section className="rounded-2xl p-8 space-y-3" style={glassPanel}>
        <h2 className="font-headline font-semibold text-lg text-on-surface">
          What to know
        </h2>
        <ul className="text-xs text-on-surface-variant/85 space-y-2 list-disc pl-5">
          <li>
            <strong className="text-on-surface">Memory embeddings are
            stripped</strong> from the backup. Embedding vectors are bound
            to a specific embedder/dimensionality; the destination
            re-embeds entries on next semantic search. First search after
            restore may be slightly slower.
          </li>
          <li>
            <strong className="text-on-surface">Knowledge bundles are
            image-baked</strong> and read-only at runtime. The zip carries
            doc content for reference + audit, but the restore endpoint
            does not write — the destination&rsquo;s KB content is
            determined by its container image.
          </li>
          <li>
            <strong className="text-on-surface">Manifest jobs are not
            exported.</strong> They reseed automatically from{" "}
            <code className="font-mono">manifest.yaml</code> at every boot.
            Only runtime jobs (the ones you created via{" "}
            <code className="font-mono">/jobs/new</code>) round-trip.
          </li>
          <li>
            <strong className="text-on-surface">Restore is order-aware</strong>
            : personality → instances+secrets → skills → memory → knowledge
            (no-op) → data sources → workflow state → jobs. Job restores after connectors so a runtime
            job referencing <code className="font-mono">phantom_create_data_worker</code>
            doesn&rsquo;t fail-closed at first cron tick.
          </li>
          <li>
            <strong className="text-on-surface">Name collisions are skipped
            by default</strong> — your existing data is preserved unless
            you tick &ldquo;Overwrite existing entries.&rdquo; Personality
            is the exception (single-row, always overwritten). If a
            section&rsquo;s existing entries cannot be read, that section
            is skipped and listed under Warnings rather than written
            blind.
          </li>
          <li>
            <strong className="text-on-surface">PHANTOM_SECRET_KEK does
            NOT need to match</strong> across source and destination. The
            zip carries cleartext secrets; the destination re-encrypts
            under its own KEK on restore.
          </li>
        </ul>
      </section>
      </div>
    </div>
  );
}
