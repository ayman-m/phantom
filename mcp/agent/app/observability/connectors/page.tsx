"use client";

/**
 * /observability/connectors
 *
 * Operator surface for the MCP connector state machine. Each row
 * shows current state (connected | failed | needs-auth | pending |
 * disabled), last error, consecutive failure count, and per-state
 * actions (Enable / Disable / Probe).
 *
 * Also surfaces image-digest pinning for the running stack.
 * The "Stack image digests" section shows each of the 5 stack-tier
 * services with the sha256:... digest the container is pinned to,
 * and any per-instance connector containers with their digests too.
 * This is what proves the "container recreation tracks image
 * content, not version label" behavior — operators can audit at a
 * glance whether an upgrade actually swapped any images or just
 * bumped the version label.
 *
 * Auto-refreshes every 5s while the page is open so a needs-auth
 * transition shows up without a manual refresh.
 *
 * Distinct from /connectors (which is the install/marketplace
 * surface): this page only deals with RUNTIME health, not
 * configuration.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type ConnectorState =
  | "connected"
  | "failed"
  | "needs-auth"
  | "pending"
  | "disabled";

interface ConnectorRow {
  connector_id: string;
  state: ConnectorState;
  last_transition_at: string | null;
  last_probed_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  configured: boolean;
  in_manifest: boolean;
  /** Where the connector comes from. Absent when the MCP does not report it. */
  origin?: "bundle" | "user" | "orphaned";
}

/** Origin of a state row. When the MCP omits `origin`, it is derived from `in_manifest`. */
function connectorOrigin(c: ConnectorRow): "bundle" | "user" | "orphaned" {
  return c.origin ?? (c.in_manifest ? "bundle" : "orphaned");
}

/** Shape of /api/agent/digests response. */
interface StackImageDigest {
  service: string;
  digest: string | null;
  pinned: boolean;
}
interface ConnectorInstanceDigest {
  connector_id: string;
  instance_id: string;
  instance_name: string;
  digest: string | null;
  /** The digest the install pins for this connector (null for an uploaded connector). */
  pinned_digest?: string | null;
  /** The running image is not the pinned one: the container is stale. */
  drift?: boolean;
  /** "cached" = the registry pull failed and a local copy was run. */
  image_pull?: "pulled" | "cached" | null;
  pinning_mode: "digest" | "tag";
  image_ref: string;
}
interface DigestsResponse {
  version: string;
  generated_at: string;
  stack: StackImageDigest[];
  connectors: ConnectorInstanceDigest[];
  connectors_error?: string;
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const REFRESH_MS = 5000;

export default function ConnectorsHealthPage() {
  const [connectors, setConnectors] = useState<ConnectorRow[]>([]);
  const [digests, setDigests] = useState<DigestsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchConnectors = useCallback(async () => {
    setError(null);
    try {
      // Fetch both endpoints in parallel — they're independent. The
      // digests fetch is more tolerant of failure (we render the
      // connector state machine even if digest info is missing) so
      // its error surfaces inline in the digests panel rather than
      // setting the page-level error banner.
      const [rConnectors, rDigests] = await Promise.all([
        fetch("/api/agent/connectors", { cache: "no-store" }),
        fetch("/api/agent/digests", { cache: "no-store" }).catch(() => null),
      ]);

      if (!rConnectors.ok)
        throw new Error(`connectors fetch ${rConnectors.status}`);
      const connectorsData = (await rConnectors.json()) as {
        connectors?: ConnectorRow[];
      };
      setConnectors(connectorsData.connectors ?? []);

      if (rDigests && rDigests.ok) {
        const digestsData = (await rDigests.json()) as DigestsResponse;
        setDigests(digestsData);
      } else if (rDigests) {
        // 4xx/5xx — keep stale digest data if any, surface a soft
        // warning. Older stacks return a different version
        // shape; we degrade gracefully.
        setDigests((prev) => prev);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void fetchConnectors();
  }, [fetchConnectors]);

  useEffect(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => {
      void fetchConnectors();
    }, REFRESH_MS);
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [connectors, fetchConnectors]);

  const handleAction = useCallback(
    async (id: string, action: "disable" | "enable" | "probe") => {
      setBusy(`${id}:${action}`);
      try {
        const r = await fetch(
          `/api/agent/connectors/${encodeURIComponent(id)}/${action}`,
          { method: "POST" },
        );
        if (!r.ok) {
          const text = await r.text().catch(() => "");
          throw new Error(`${action} ${r.status}: ${text.slice(0, 120)}`);
        }
        await fetchConnectors();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [fetchConnectors],
  );

  const summary = (() => {
    const counts: Record<ConnectorState | "total", number> = {
      total: connectors.length,
      connected: 0,
      failed: 0,
      "needs-auth": 0,
      pending: 0,
      disabled: 0,
    };
    for (const c of connectors) counts[c.state] += 1;
    return counts;
  })();

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                cable
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Connector health
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9 max-w-2xl">
              Per-connector lifecycle state. Click Probe to run a
              connector&apos;s read-only test again, Disable to mark it
              disabled (the instance switch on /connectors is what
              pauses its tools), or Reauth (when shown) to re-test
              after you fix its credentials. Auto-refreshes every {REFRESH_MS / 1000}s.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void fetchConnectors()}
            disabled={loading}
            className="px-4 py-2 rounded-xl text-xs font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-base align-middle mr-1">
              refresh
            </span>
            Refresh
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          <SummaryChip label="Total" count={summary.total} tone="neutral" />
          <SummaryChip label="Connected" count={summary.connected} tone="ok" />
          <SummaryChip label="Pending" count={summary.pending} tone="warn" />
          <SummaryChip
            label="Needs auth"
            count={summary["needs-auth"]}
            tone="warn"
          />
          <SummaryChip label="Failed" count={summary.failed} tone="err" />
          <SummaryChip
            label="Disabled"
            count={summary.disabled}
            tone="neutral"
          />
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {/* Image-digest pinning panel. Rendered above the
            connector state-machine list because the digest info is
            stack-wide context that frames the per-connector rows
            below. Hidden entirely when there is no digest data, so
            we don't show an empty section. */}
        {digests && (digests.stack.length > 0 || digests.connectors.length > 0) && (
          <StackImagesSection digests={digests} />
        )}

        {loading && connectors.length === 0 ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading connectors…
          </div>
        ) : connectors.length === 0 ? (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <p className="text-sm text-on-surface-variant">
              No connectors registered yet. The MCP discovers
              connectors on first tool call; check
              <code className="font-mono mx-1">
                bundles/spark/manifest.yaml
              </code>
              <span className="font-mono">toolConnectors</span>.
            </p>
          </div>
        ) : (
          <div className="grid gap-2">
            {connectors.map((c) => (
              <ConnectorRowCard
                key={c.connector_id}
                connector={c}
                busy={
                  busy === `${c.connector_id}:disable` ||
                  busy === `${c.connector_id}:enable` ||
                  busy === `${c.connector_id}:probe`
                }
                onAction={handleAction}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * StackImagesSection — image-digest panel.
 *
 * Renders two sub-tables:
 *   1. Stack-tier services (5 rows: phantom-agent, xlog, caldera,
 *      phantom-updater, phantom-browser) with their pinned digest
 *      and a "digest" or "tag (legacy)" badge. The badge serves as
 *      a tripwire — on a clean install all 5 should show
 *      "digest"; any "tag (legacy)" badge means the operator's .env
 *      is missing manifest-managed lines (common after a manual edit
 *      that deleted DIGEST_* values).
 *   2. Per-instance connector containers (variable rows depending on
 *      what the operator has created). Same digest + pinning_mode
 *      shape. Only rendered when there's at least one such instance.
 *
 * The full sha256 digest is too long for at-a-glance readability, so
 * we display only the first 12 chars after `sha256:` (the standard
 * Docker short-form). The full digest is in the title attribute for
 * copy/audit purposes.
 *
 * Pinning-mode badge colors mirror the rest of the page's tone
 * vocabulary (ok = secondary, warn = tertiary).
 */
function StackImagesSection({ digests }: { digests: DigestsResponse }) {
  const fmtDigest = (d: string | null) =>
    d && d.startsWith("sha256:") ? d.slice("sha256:".length, 19) + "…" : "—";

  const stackPinned = digests.stack.filter((s) => s.pinned).length;
  const stackTotal = digests.stack.length;

  return (
    <div className="rounded-2xl p-4" style={glassCard}>
      <div className="flex items-baseline justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-base text-on-surface-variant">
            verified
          </span>
          <h2 className="font-headline text-sm font-semibold text-on-surface">
            Image digests
          </h2>
          <span className="text-[11px] text-on-surface-variant/70 font-mono">
            v{digests.version}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-on-surface-variant">
          <span>
            <span className="text-on-surface font-mono">
              {stackPinned}/{stackTotal}
            </span>{" "}
            stack services digest-pinned
          </span>
          {digests.connectors.length > 0 && (
            <span>
              <span className="text-on-surface font-mono">
                {digests.connectors.length}
              </span>{" "}
              instance container{digests.connectors.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>

      {/* Stack-tier digest rows */}
      <div className="space-y-1">
        {digests.stack.map((row) => (
          <div
            key={row.service}
            className="flex items-center gap-3 px-3 py-1.5 rounded text-[11px] hover:bg-white/5"
          >
            <span className="font-mono text-on-surface min-w-[140px] truncate">
              {row.service}
            </span>
            <span
              className={cn(
                "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
                row.pinned
                  ? "bg-secondary/15 text-secondary"
                  : "bg-tertiary/15 text-tertiary",
              )}
              title={
                row.pinned
                  ? "Image is pinned by content digest"
                  : "Tag-based pinning (legacy fallback). Re-run phantom-installer to apply the digest manifest."
              }
            >
              {row.pinned ? "digest" : "tag (legacy)"}
            </span>
            <span
              className="font-mono text-on-surface-variant ml-auto"
              title={row.digest ?? ""}
            >
              {fmtDigest(row.digest)}
            </span>
          </div>
        ))}
      </div>

      {/* Per-instance connector digest rows (only shown when present) */}
      {digests.connectors.length > 0 && (
        <>
          <div className="mt-4 mb-2 text-[10px] font-label uppercase tracking-wider text-on-surface-variant/60">
            Per-instance connector containers
          </div>
          <div className="space-y-1">
            {digests.connectors.map((row) => (
              <div
                key={`${row.connector_id}:${row.instance_id}`}
                className="flex items-center gap-3 px-3 py-1.5 rounded text-[11px] hover:bg-white/5"
              >
                <span className="font-mono text-on-surface min-w-[140px] truncate">
                  {row.connector_id}
                </span>
                <span className="font-mono text-on-surface-variant truncate min-w-[120px]">
                  {row.instance_name}
                </span>
                <span
                  className={cn(
                    "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
                    row.pinning_mode === "digest"
                      ? "bg-secondary/15 text-secondary"
                      : "bg-tertiary/15 text-tertiary",
                  )}
                  title={
                    row.pinning_mode === "digest"
                      ? "Container started with a digest-pinned image"
                      : "Container is tag-pinned. The next stack upgrade will recreate it even if its image content didn't change. Surface in /observability for visibility; not a fault per se."
                  }
                >
                  {row.pinning_mode}
                </span>
                {row.drift && (
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider bg-error/15 text-error"
                    title={`Running ${fmtDigest(row.digest)} but the install pins ${fmtDigest(row.pinned_digest ?? null)}. The updater recreates a drifted container on its next 5-minute sweep; if this stays, check the phantom-updater log.`}
                  >
                    drifted
                  </span>
                )}
                {row.image_pull === "cached" && (
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider bg-tertiary/15 text-tertiary"
                    title="The registry pull failed when this container was started, so it runs a local copy of the image that may be out of date. Check the host's network access to ghcr.io and the phantom-updater log."
                  >
                    cached image
                  </span>
                )}
                <span
                  className="font-mono text-on-surface-variant ml-auto"
                  title={row.digest ?? ""}
                >
                  {fmtDigest(row.digest)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Soft error banner if the per-instance query failed */}
      {digests.connectors_error && (
        <div className="mt-3 px-3 py-2 rounded text-[11px] bg-tertiary/10 text-tertiary border border-tertiary/30">
          Per-instance connector digests unavailable: {digests.connectors_error}
        </div>
      )}
    </div>
  );
}

function SummaryChip({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "ok" | "warn" | "err" | "neutral";
}) {
  const cls =
    tone === "ok"
      ? "bg-secondary/15 text-secondary"
      : tone === "warn"
        ? "bg-tertiary/15 text-tertiary"
        : tone === "err"
          ? "bg-error/15 text-error"
          : "bg-white/5 text-on-surface-variant";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px]",
        cls,
      )}
    >
      <span className="font-label uppercase tracking-wider">{label}</span>
      <span className="font-mono">{count}</span>
    </span>
  );
}

function ConnectorRowCard({
  connector,
  busy,
  onAction,
}: {
  connector: ConnectorRow;
  busy: boolean;
  onAction: (id: string, action: "disable" | "enable" | "probe") => void;
}) {
  const tone = stateTone(connector.state);
  const id = connector.connector_id;
  return (
    <div
      className="rounded-2xl p-4 flex items-start gap-3"
      style={glassCard}
    >
      <span
        className={cn("w-2.5 h-2.5 rounded-full shrink-0 mt-1.5", tone.dot)}
        title={tone.label}
        aria-label={tone.label}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="font-mono text-sm font-semibold text-on-surface truncate">
            {id}
          </span>
          <span
            className={cn(
              "text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-wider",
              tone.bg,
              tone.fg,
            )}
          >
            {tone.label}
          </span>
          {!connector.configured && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant/60"
              title="No instance configured for this connector"
            >
              not configured
            </span>
          )}
          {connectorOrigin(connector) === "user" && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant/60"
              title="Uploaded through the marketplace; not part of the bundle"
            >
              uploaded
            </span>
          )}
          {connectorOrigin(connector) === "orphaned" && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-error/10 text-error"
              title="State row exists but the connector is neither in the bundle manifest nor an uploaded connector"
            >
              orphaned
            </span>
          )}
          {connector.consecutive_failures > 1 && (
            <span className="text-[10px] font-mono text-error">
              {connector.consecutive_failures}× failures
            </span>
          )}
          <span className="ml-auto text-[10px] text-on-surface-variant/50 font-mono">
            {connector.last_transition_at
              ? new Date(connector.last_transition_at).toLocaleString()
              : "—"}
          </span>
        </div>
        {connector.last_error && (
          <p className="text-[11px] text-on-surface-variant font-mono break-all">
            {connector.last_error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {connector.state === "needs-auth" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAction(id, "probe")}
            className="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-tertiary/15 text-tertiary hover:bg-tertiary/25 transition-colors disabled:opacity-50"
            title="Retry — assumes you've fixed the auth upstream"
          >
            Reauth
          </button>
        )}
        {connector.state !== "disabled" ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction(id, "probe")}
              aria-label="Probe connector"
              className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
              title="Probe (run the connector's read-only test now)"
            >
              <span className="material-symbols-outlined text-base">
                refresh
              </span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction(id, "disable")}
              aria-label="Disable connector"
              className="p-1.5 rounded hover:bg-error/10 text-on-surface-variant hover:text-error transition-colors disabled:opacity-50"
              title="Mark disabled (the instance switch on /connectors pauses the tools)"
            >
              <span className="material-symbols-outlined text-base">
                block
              </span>
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAction(id, "enable")}
            className="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-primary/15 text-primary hover:bg-primary/25 transition-colors disabled:opacity-50"
          >
            Enable
          </button>
        )}
      </div>
    </div>
  );
}

function stateTone(s: ConnectorState): {
  dot: string;
  bg: string;
  fg: string;
  label: string;
} {
  switch (s) {
    case "connected":
      return {
        dot: "bg-secondary",
        bg: "bg-secondary/15",
        fg: "text-secondary",
        label: "Connected",
      };
    case "pending":
      return {
        dot: "bg-tertiary animate-pulse",
        bg: "bg-tertiary/15",
        fg: "text-tertiary",
        label: "Pending",
      };
    case "failed":
      return {
        dot: "bg-error",
        bg: "bg-error/15",
        fg: "text-error",
        label: "Failed",
      };
    case "needs-auth":
      return {
        dot: "bg-tertiary",
        bg: "bg-tertiary/15",
        fg: "text-tertiary",
        label: "Needs auth",
      };
    case "disabled":
      return {
        dot: "bg-outline",
        bg: "bg-white/5",
        fg: "text-on-surface-variant",
        label: "Disabled",
      };
  }
}
