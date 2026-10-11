/**
 * UploadDataSourceDialog
 *
 * Modal for uploading OR editing a custom data_source.yaml. Two-phase flow:
 *
 *   1. PREVIEW   — operator pastes YAML (or drops a file); we POST to
 *                  /api/agent/data-sources/user/preview which validates
 *                  against data_source.schema.json + runs vendor
 *                  similarity check. Server returns accept_token.
 *
 *   2. CONFIRM   — if similarity_matches present, operator picks:
 *                    • "Create new vendor" → keep YAML's vendor as-typed
 *                    • "Group under X"     → rewrite vendor field, then
 *                                            RE-PREVIEW for fresh token
 *                                            (since accept_token is bound
 *                                            to the canonical bytes)
 *                  Then POST /api/agent/data-sources/user (new)
 *                  or PUT /api/agent/data-sources/user/{editId} (edit).
 *
 * The page-level component drives this dialog via the `open` prop;
 * `onUploaded(id)` fires when the new source is committed so the parent
 * can refresh the catalog.
 *
 * Pass `editId` to edit an existing user upload:
 *   • The dialog fetches GET /api/agent/data-sources/user/{editId} on
 *     open, pre-fills the YAML textarea with the on-disk content.
 *   • The body's `id` MUST match `editId` — PUT is not rename. The
 *     backend enforces this; the UI is allowed to surface any change but
 *     submission will fail with a 409 if the operator alters `id`.
 *   • Commit goes to PUT instead of POST. accept_token semantics
 *     identical (operator must re-preview after edits to get a fresh
 *     token bound to the canonical bytes).
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface SimilarityMatch {
  vendor: string;
  similarity: "exact" | "levenshtein" | "substring";
  distance: number | null;
}

interface PreviewResponse {
  ok: boolean;
  errors?: string[];
  uploaded_vendor?: string;
  uploaded_id?: string;
  similarity_matches?: SimilarityMatch[];
  bundle_collision?: boolean;
  accept_token?: string;
  error?: string;
}

interface UploadDialogProps {
  open: boolean;
  onClose: () => void;
  onUploaded: (id: string) => void;
  /** When set, the dialog opens in edit mode: pre-fills the
   *  textarea via GET /user/{editId} and submits via PUT. */
  editId?: string | null;
}

type Phase = "input" | "preview" | "committing" | "done" | "loading";

const SAMPLE_YAML = `schema_version: 1
id: acme-app
pack_name: AcmeCorp
rule_name: AcmeCorpEvents
dataset_name: acmecorp_events_raw
vendor: AcmeCorp
product: AcmeApp
description: AcmeCorp's hypothetical security product
categories:
  - Endpoint
version: 1.0.0
origin: user
formats: [JSON, SYSLOG]
# Optional: how logs reach Cortex. "syslog" (default) = CEF/syslog to the
# broker; "http" = JSON through the http-sender connector to an XSIAM HTTP
# Log Collector. Omit the key for syslog.
# delivery: http
is_rawlog_only: false
fields:
  - {name: src_ip, type: ipv4}
  - {name: dst_ip, type: ipv4}
  - {name: username, type: user}
  - {name: severity, type: enum, enum_values: [low, medium, high]}
  - {name: timestamp_ms, type: timestamp_ms}
`;

export function UploadDataSourceDialog({
  open,
  onClose,
  onUploaded,
  editId,
}: UploadDialogProps) {
  const isEdit = Boolean(editId);
  const [phase, setPhase] = useState<Phase>("input");
  const [yamlText, setYamlText] = useState("");
  const [previewResp, setPreviewResp] = useState<PreviewResponse | null>(null);
  const [vendorChoice, setVendorChoice] = useState<"create_new" | "group_under">(
    "create_new",
  );
  const [groupVendor, setGroupVendor] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setPhase("input");
      setYamlText("");
      setPreviewResp(null);
      setVendorChoice("create_new");
      setGroupVendor("");
      setError(null);
    }
  }, [open]);

  // When entering edit mode, fetch the existing YAML to
  // pre-fill the textarea. We re-serialize the doc as YAML client-side
  // so the operator can edit any field; the body still goes through
  // /user/preview → PUT for the same accept_token validation.
  useEffect(() => {
    if (!open || !editId) return;
    let cancelled = false;
    setPhase("loading");
    setError(null);
    (async () => {
      try {
        const resp = await fetch(
          `/api/agent/data-sources/user/${encodeURIComponent(editId)}`,
          { cache: "no-store" },
        );
        const payload = (await resp.json()) as {
          ok?: boolean;
          doc?: Record<string, unknown>;
          error?: string;
        };
        if (cancelled) return;
        if (!resp.ok || !payload.ok || !payload.doc) {
          setError(payload.error ?? `Load failed (HTTP ${resp.status})`);
          setPhase("input");
          return;
        }
        // Strip server-managed timestamps so the operator only sees what
        // they own. The server re-stamps updated_at on PUT regardless.
        const doc = { ...payload.doc };
        delete (doc as Record<string, unknown>).updated_at;
        // Convert to YAML for the textarea. The simplest pretty-printer
        // is JSON — schema validator + canonical bytes parser both
        // accept JSON too (yaml.safe_load handles both). The operator
        // can re-format to YAML if they prefer.
        setYamlText(yamlifyDoc(doc));
        setPhase("input");
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setPhase("input");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, editId]);

  // Auto-focus the textarea when modal opens
  useEffect(() => {
    if (open && phase === "input") {
      textareaRef.current?.focus();
    }
  }, [open, phase]);

  const handlePreview = useCallback(async () => {
    setError(null);
    if (!yamlText.trim()) {
      setError("YAML content is required");
      return;
    }
    try {
      const resp = await fetch("/api/agent/data-sources/user/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: yamlText }),
      });
      const payload = (await resp.json()) as PreviewResponse;
      if (!resp.ok || !payload.ok) {
        setError(
          payload.errors?.join("; ") ??
            payload.error ??
            `Preview failed (HTTP ${resp.status})`,
        );
        return;
      }
      setPreviewResp(payload);
      setPhase("preview");
      // Default group_vendor to the top similarity match if present
      if (payload.similarity_matches && payload.similarity_matches.length > 0) {
        setGroupVendor(payload.similarity_matches[0].vendor);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [yamlText]);

  const handleCommit = useCallback(async () => {
    if (!previewResp?.accept_token) {
      setError("No accept_token from preview — re-preview first");
      return;
    }
    setError(null);
    setPhase("committing");
    try {
      let bodyYaml = yamlText;
      // If group_under, rewrite the vendor field client-side then re-preview
      // to get a fresh accept_token bound to the rewritten bytes.
      let acceptToken = previewResp.accept_token;
      if (vendorChoice === "group_under" && groupVendor &&
          groupVendor !== previewResp.uploaded_vendor) {
        bodyYaml = rewriteVendorField(yamlText, groupVendor);
        // Re-preview to get fresh token
        const repreview = await fetch("/api/agent/data-sources/user/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml: bodyYaml }),
        });
        const rp = (await repreview.json()) as PreviewResponse;
        if (!repreview.ok || !rp.ok || !rp.accept_token) {
          setError(
            "Re-preview failed after group_under rewrite: " +
              (rp.errors?.join("; ") ?? rp.error ?? "unknown"),
          );
          setPhase("preview");
          return;
        }
        acceptToken = rp.accept_token;
      }

      const url = isEdit
        ? `/api/agent/data-sources/user/${encodeURIComponent(editId!)}`
        : "/api/agent/data-sources/user";
      const method = isEdit ? "PUT" : "POST";
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          yaml: bodyYaml,
          accept_token: acceptToken,
          vendor_choice: vendorChoice,
        }),
      });
      const payload = await resp.json();
      if (!resp.ok || !payload.ok) {
        setError(
          payload.errors?.join("; ") ??
            payload.error ??
            `${isEdit ? "Save" : "Commit"} failed (HTTP ${resp.status})`,
        );
        setPhase("preview");
        return;
      }
      setPhase("done");
      onUploaded(payload.id);
      // Auto-close after a brief success state
      setTimeout(() => onClose(), 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("preview");
    }
  }, [previewResp, yamlText, vendorChoice, groupVendor, onUploaded, onClose, isEdit, editId]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface-container-low border border-outline-variant/30 rounded-xl shadow-2xl w-[760px] max-w-[92vw] max-h-[88vh] overflow-y-auto">
        {/* Header */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/30">
          <div>
            <h2 className="font-headline text-xl font-semibold text-on-surface">
              {isEdit ? "Edit data source" : "Upload data source"}
            </h2>
            <p className="text-xs text-on-surface-variant mt-1">
              {isEdit
                ? `Editing ${editId}. Changing the id field is not allowed — to rename, delete + re-upload.`
                : "Paste a custom data_source.yaml — schema-validated before commit."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface p-1 rounded transition-colors"
            aria-label="Close"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </header>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {phase === "input" && (
            <>
              <div className="flex items-center justify-between">
                <label
                  htmlFor="yaml-textarea"
                  className="text-sm font-medium text-on-surface"
                >
                  YAML content
                </label>
                <button
                  type="button"
                  onClick={() => setYamlText(SAMPLE_YAML)}
                  className="text-xs text-primary hover:underline"
                >
                  Insert sample
                </button>
              </div>
              <textarea
                ref={textareaRef}
                id="yaml-textarea"
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                placeholder="Paste your data_source.yaml content here..."
                className="w-full min-h-[280px] font-mono text-xs p-3 bg-surface border border-outline-variant/40 rounded-md text-on-surface focus:outline-none focus:border-primary"
                spellCheck={false}
              />
              <details className="text-xs">
                <summary className="cursor-pointer text-on-surface-variant hover:text-on-surface">
                  Image guidelines (for the optional `logo` field)
                </summary>
                <ul className="mt-2 pl-4 space-y-1 text-on-surface-variant">
                  <li>• Format: SVG preferred; PNG/JPEG accepted as fallback</li>
                  <li>• Size: ≤ 50 KB pre-base64 (operator-UI enforces)</li>
                  <li>• Dimensions: up to 512×512 for raster</li>
                  <li>• Background: transparent</li>
                  <li>
                    • Encode bytes as base64 and place under{" "}
                    <code className="font-mono">logo.data</code> with
                    matching <code className="font-mono">mime_type</code>
                  </li>
                </ul>
              </details>
              {error && (
                <div className="text-xs text-error bg-error-container/20 px-3 py-2 rounded border border-error/30">
                  {error}
                </div>
              )}
            </>
          )}

          {phase === "preview" && previewResp && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-surface-container p-3 rounded">
                  <div className="text-xs text-on-surface-variant uppercase tracking-wider">
                    Uploaded vendor
                  </div>
                  <div className="font-mono text-sm text-on-surface mt-1">
                    {previewResp.uploaded_vendor}
                  </div>
                </div>
                <div className="bg-surface-container p-3 rounded">
                  <div className="text-xs text-on-surface-variant uppercase tracking-wider">
                    ID
                  </div>
                  <div className="font-mono text-xs text-on-surface mt-1 break-all">
                    {previewResp.uploaded_id}
                  </div>
                </div>
              </div>

              {previewResp.bundle_collision && (
                <div className="text-xs text-error bg-error-container/20 px-3 py-2 rounded border border-error/30">
                  ⚠ This id collides with a bundled data source. The commit
                  will fail. Please change the YAML&apos;s{" "}
                  <code className="font-mono">id</code> field.
                </div>
              )}

              {previewResp.similarity_matches &&
                previewResp.similarity_matches.length > 0 && (
                  <div className="border border-tertiary/30 bg-tertiary-container/20 p-4 rounded">
                    <div className="text-sm font-medium text-on-surface mb-2">
                      Did you mean...?
                    </div>
                    <div className="text-xs text-on-surface-variant mb-3">
                      The vendor name{" "}
                      <span className="font-mono text-on-surface">
                        {previewResp.uploaded_vendor}
                      </span>{" "}
                      is similar to existing vendors. Choose to group under one,
                      or create a new vendor entry.
                    </div>

                    <label className="flex items-start gap-2 mb-2 cursor-pointer">
                      <input
                        type="radio"
                        name="vendor-choice"
                        checked={vendorChoice === "create_new"}
                        onChange={() => setVendorChoice("create_new")}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="text-sm text-on-surface">
                          Create new vendor:{" "}
                          <span className="font-mono">
                            {previewResp.uploaded_vendor}
                          </span>
                        </div>
                        <div className="text-xs text-on-surface-variant">
                          The YAML&apos;s vendor field is kept as-typed.
                        </div>
                      </div>
                    </label>

                    <label className="flex items-start gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="vendor-choice"
                        checked={vendorChoice === "group_under"}
                        onChange={() => setVendorChoice("group_under")}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="text-sm text-on-surface">
                          Group under existing vendor:
                        </div>
                        <select
                          value={groupVendor}
                          onChange={(e) => setGroupVendor(e.target.value)}
                          disabled={vendorChoice !== "group_under"}
                          className="mt-1 w-full bg-surface border border-outline-variant/40 rounded px-2 py-1 text-sm text-on-surface disabled:opacity-40"
                        >
                          {previewResp.similarity_matches.map((m) => (
                            <option key={m.vendor} value={m.vendor}>
                              {m.vendor} ({m.similarity}
                              {m.distance !== null ? ` · dist=${m.distance}` : ""})
                            </option>
                          ))}
                        </select>
                        <div className="text-xs text-on-surface-variant mt-1">
                          The vendor field will be rewritten before commit;
                          your new source shows up under this vendor in the
                          catalog grouping.
                        </div>
                      </div>
                    </label>
                  </div>
                )}

              {(!previewResp.similarity_matches ||
                previewResp.similarity_matches.length === 0) && (
                <div className="text-xs text-on-surface-variant px-3 py-2 bg-surface-container rounded">
                  ✓ No similarity matches — this looks like a new vendor.
                </div>
              )}

              {error && (
                <div className="text-xs text-error bg-error-container/20 px-3 py-2 rounded border border-error/30">
                  {error}
                </div>
              )}
            </>
          )}

          {phase === "loading" && (
            <div className="flex flex-col items-center py-12">
              <div className="material-symbols-outlined animate-spin text-primary text-4xl">
                progress_activity
              </div>
              <div className="text-sm text-on-surface-variant mt-3">
                Loading existing data_source.yaml...
              </div>
            </div>
          )}

          {phase === "committing" && (
            <div className="flex flex-col items-center py-12">
              <div className="material-symbols-outlined animate-spin text-primary text-4xl">
                progress_activity
              </div>
              <div className="text-sm text-on-surface-variant mt-3">
                {isEdit ? "Saving changes..." : "Writing data_source.yaml..."}
              </div>
            </div>
          )}

          {phase === "done" && (
            <div className="flex flex-col items-center py-12">
              <div className="material-symbols-outlined text-tertiary text-5xl">
                check_circle
              </div>
              <div className="text-sm text-on-surface mt-3 font-medium">
                {isEdit ? "Changes saved" : "Upload committed"}
              </div>
              <div className="text-xs text-on-surface-variant mt-1">
                {isEdit
                  ? "Your edits are live; the catalog has been refreshed."
                  : "The new source appears in Browse with a User-upload badge."}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="flex items-center justify-end gap-2 px-6 py-4 border-t border-outline-variant/30 bg-surface-container/40">
          <button
            type="button"
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface text-sm px-4 py-2 rounded transition-colors"
          >
            Cancel
          </button>
          {phase === "input" && (
            <button
              type="button"
              onClick={handlePreview}
              disabled={!yamlText.trim()}
              className="bg-primary text-on-primary text-sm px-4 py-2 rounded font-medium disabled:opacity-40 hover:bg-primary/90 transition-colors"
            >
              Preview
            </button>
          )}
          {phase === "preview" && (
            <>
              <button
                type="button"
                onClick={() => setPhase("input")}
                className="text-on-surface-variant hover:text-on-surface text-sm px-4 py-2 rounded transition-colors"
              >
                {isEdit ? "Back" : "Edit"}
              </button>
              <button
                type="button"
                onClick={handleCommit}
                disabled={previewResp?.bundle_collision === true}
                className="bg-primary text-on-primary text-sm px-4 py-2 rounded font-medium disabled:opacity-40 hover:bg-primary/90 transition-colors"
              >
                {isEdit ? "Save changes" : "Commit upload"}
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}


/**
 * Replace the `vendor:` field in a YAML text without parsing+reserializing.
 *
 * We can't use a real YAML parser here because we want to preserve the
 * operator's formatting / comments / whitespace exactly — the only change
 * is the vendor value. A regex on the line is sufficient because the YAML
 * format we expect is top-level `vendor: <name>` (multi-line vendor blocks
 * are not allowed by data_source.schema.json).
 */
function rewriteVendorField(yaml: string, newVendor: string): string {
  // Match `vendor: <value>` at line start (no leading whitespace) — top-level field.
  return yaml.replace(/^vendor:\s*[^\n]*$/m, `vendor: ${newVendor}`);
}

/**
 * Re-serialize a parsed data_source doc as YAML-ish text for the
 * textarea. The upload path is YAML-or-JSON tolerant (both
 * parse via `yaml.safe_load` server-side), so pretty-printed JSON is
 * fine — the canonical_yaml_bytes serializer normalizes either form
 * to the same SHA-256.
 *
 * Why not use a real YAML serializer? js-yaml would add ~50KB to the
 * bundle and we don't need round-trip fidelity (the operator's about
 * to edit the doc anyway). JSON is unambiguous + every schema field is
 * representable in JSON.
 *
 * Order convention mirrors data_source.schema.json: top-level fields
 * in declaration order, then arrays/objects with stable internal order.
 */
function yamlifyDoc(doc: Record<string, unknown>): string {
  // Field order matches the SAMPLE_YAML at the top of this file so the
  // operator sees a familiar layout. Unknown fields land after.
  const ordered: Record<string, unknown> = {};
  const order = [
    "schema_version",
    "id",
    "pack_name",
    "rule_name",
    "dataset_name",
    "vendor",
    "product",
    "description",
    "categories",
    "use_cases",
    "version",
    "origin",
    "author",
    "created_at",
    "formats",
    "is_rawlog_only",
    "fields",
    "logo",
  ];
  for (const k of order) {
    if (k in doc) ordered[k] = doc[k];
  }
  for (const k of Object.keys(doc)) {
    if (!(k in ordered)) ordered[k] = doc[k];
  }
  return JSON.stringify(ordered, null, 2);
}
