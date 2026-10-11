"use client";

/**
 * Import Job button — sibling to the "Create Job" link on /jobs.
 *
 * Accepts a .json export produced by JobActions's "Export definition"
 * or "Export runs" menu items. The two export shapes share the same
 * envelope:
 *
 *   {
 *     exported_at: "...",
 *     schema_version: 1,
 *     job: { name, cron, timezone, action, enabled, ... },
 *     runs?: [...]   // present in runs-export only; ignored on import
 *   }
 *
 * Per operator policy: import only re-creates the JOB DEFINITION.
 * Run history is read-only ground truth — exporting runs is for
 * forensic snapshots, not a portable history that can be replayed
 * into another deployment. So `payload.runs` is silently dropped if
 * present.
 *
 * Why a client component (rather than handling this on the server-
 * component /jobs page): the file picker + FileReader + toast
 * lifecycle all need browser-side state. Easier to ship as one
 * focused client component than to retrofit /jobs into "use client"
 * just for this affordance.
 */

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useNotificationsStore } from "@/lib/stores/notifications";

interface ImportEnvelope {
  exported_at?: string;
  schema_version?: number;
  job?: Record<string, unknown>;
  // runs may be present in runs-export but is intentionally ignored.
  runs?: unknown;
}

export function ImportJobButton() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const addToast = useNotificationsStore((s) => s.addToast);

  const handleClick = () => {
    // Reset the input first so the SAME file can be selected twice
    // in a row (browsers fire `change` only when the value changes).
    if (inputRef.current) inputRef.current.value = "";
    inputRef.current?.click();
  };

  const handleFile = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      setBusy(true);
      try {
        const text = await file.text();

        // Parse — surface a friendly error if the file isn't JSON.
        let envelope: ImportEnvelope;
        try {
          envelope = JSON.parse(text) as ImportEnvelope;
        } catch (err) {
          addToast({
            variant: "error",
            title: "Could not import job",
            description: `File is not valid JSON (${
              err instanceof Error ? err.message : "parse error"
            })`,
          });
          return;
        }

        // The envelope must carry a `job` object. We accept ANY
        // shape inside `job` — the MCP's POST /api/v1/jobs is the
        // schema gate; this layer just hands the blob through.
        if (
          !envelope ||
          typeof envelope !== "object" ||
          !envelope.job ||
          typeof envelope.job !== "object"
        ) {
          addToast({
            variant: "error",
            title: "Could not import job",
            description:
              "File doesn't carry a `job` object. Expected an envelope from the Export menu.",
          });
          return;
        }

        // Schema-version sanity check. Bumping the version in the
        // future means we either translate v1 → vN at this layer
        // or refuse with a "produced by an older Phantom; please
        // re-export" message. Today there's only v1.
        if (
          envelope.schema_version !== undefined &&
          envelope.schema_version !== 1
        ) {
          addToast({
            variant: "error",
            title: "Unsupported schema version",
            description: `Got schema_version=${envelope.schema_version}, expected 1.`,
          });
          return;
        }

        // POST to /api/agent/jobs (the Next.js proxy → MCP creates
        // the row). The job blob is sent verbatim; the MCP rejects
        // anything malformed with a 400 + clear message.
        const resp = await fetch("/api/agent/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(envelope.job),
        });

        if (resp.ok) {
          // Success — extract the imported name to show in the
          // toast. Default to the filename if name is missing.
          const created = (await resp.json()) as {
            job?: { name?: string };
          };
          const name = created?.job?.name ?? file.name.replace(/\.json$/i, "");
          addToast({
            variant: "success",
            title: `Imported job "${name}"`,
            description:
              "The runtime DB now has this job. Run history was NOT imported (only the definition).",
          });
          router.refresh();
        } else {
          // Surface the server's error message verbatim (parseError
          // in lib/api/client.ts already extracts {error:"..."} from
          // our route handlers — but the raw fetch here doesn't go
          // through that. Manual extraction.)
          let detail = `Server returned ${resp.status}`;
          try {
            const errBody = (await resp.json()) as { error?: string };
            if (errBody?.error) detail = errBody.error;
          } catch {
            // non-JSON body — fall through
          }
          addToast({
            variant: "error",
            title: "Could not import job",
            description: detail,
          });
        }
      } finally {
        setBusy(false);
      }
    },
    [addToast, router],
  );

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        onChange={handleFile}
        className="hidden"
        aria-label="Import job from .json file"
      />
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-on-surface text-sm font-medium hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          border: "0.5px solid var(--glass-border)",
        }}
        title="Import a job from a .json export"
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
