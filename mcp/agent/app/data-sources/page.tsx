"use client";

/**
 * /data-sources — Marketplace Data Sources page.
 *
 * UI structure modeled after the operator-supplied mockups (Obsidian
 * Lens / Spark Spectrum aesthetic). All colors use Phantom's Material 3
 * token system so light + dark themes switch automatically — no hex
 * literals in the JSX.
 *
 * Components in this file (top-to-bottom):
 *   - DataSourcesPage          page shell + tabs + state owner
 *   - NotificationStack        success / error banners (auto-dismiss success)
 *   - BrowseSection            Browse tab body (search + filters + grid)
 *   - InstalledSection         Installed tab body (grid)
 *   - BrowsePackCard           one card per pack in Browse view
 *   - InstalledCard            one card per installed schema
 *   - SkeletonCard             shimmer placeholder
 *   - EmptyState               no-results / empty / error variants
 *   - ErrorPanel               full-screen error variant for catalog failures
 *   - DetailDrawer             right-slide drawer with schema fields + XDM
 *   - UninstallModal           destructive confirm modal
 *   - AmbientGlow              decorative background blobs
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useTheme, type Theme } from "@/lib/use-theme";
import { MarkdownContent } from "@/components/markdown-content";

import { filterAgentix } from "./categories";
import { UploadDataSourceDialog } from "./upload-dialog";

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Append ?theme= query to a logo URL so the server-side route
 * resolves the correct light/dark SVG variant. The base URL comes from
 * the catalog (no theme baked in).
 *
 * The UI ALWAYS requests the LIGHT variant regardless of the
 * operator's theme. The icon panel renders against a constant neutral
 * (near-white) background that doesn't change with theme, so we never
 * need the dark variant. This sidesteps two problems with the prior
 * theme-coupled approach:
 *   1. `Cache-Control: immutable` + cross-render image-element caching
 *      sometimes caused stale variants to render after theme toggle.
 *   2. White-text dark variants rendered invisibly against light-theme
 *      panels when the variant switch didn't fire cleanly.
 *
 * The `?theme=` query is still passed for backward compatibility with
 * any external callers; UI code uses `withLightVariant` exclusively.
 */
function withTheme(url: string | null, theme: Theme): string | null {
  if (!url) return null;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}theme=${theme}`;
}

/**
 * UI's canonical logo URL builder. Always requests the light
 * variant because the icon panel is theme-independent (constant white).
 */
function withLightVariant(url: string | null): string | null {
  return withTheme(url, "light");
}

/**
 * Reusable logo-or-fallback renderer. Three render sites
 * (VendorCard, BrowsePackCard, InstalledCard) all need:
 *
 *   1. A constant near-white background panel (`#F7F8FA`) — never
 *      theme-coupled, so white-fill SVGs stay visible in both themes.
 *
 *   2. A fallback `inventory_2` icon when EITHER no logo URL is given
 *      OR the URL 404s at fetch time. The onError handler renders the
 *      fallback icon (rather than just hiding the <img>), so packs whose
 *      vendor doesn't have a baked SVG never show a blank panel.
 *
 * Sizing varies by site, so the caller passes the max-width/-height
 * Tailwind class. This component owns nothing visual beyond the panel
 * background + the img + the fallback.
 */
function LogoOrFallback({
  logoUrl,
  alt,
  imgClassName,
  panelClassName,
  iconClassName,
  lazy = true,
}: {
  logoUrl: string | null;
  alt: string;
  imgClassName: string;
  panelClassName: string;
  iconClassName?: string;
  lazy?: boolean;
}) {
  const [errored, setErrored] = useState(false);
  const showFallback = !logoUrl || errored;
  return (
    <div
      className={panelClassName}
      style={{ backgroundColor: "#F7F8FA" }}
    >
      {showFallback ? (
        <span
          className={
            iconClassName ??
            "material-symbols-outlined text-4xl text-on-surface-variant/50"
          }
        >
          inventory_2
        </span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logoUrl ?? undefined}
          alt={alt}
          className={imgClassName}
          loading={lazy ? "lazy" : undefined}
          onError={() => setErrored(true)}
        />
      )}
    </div>
  );
}

// ── Types ───────────────────────────────────────────────────────────

interface DataSource {
  id: string;
  pack_name: string;
  rule_name: string;
  dataset_name: string;
  pack_version: string | null;
  is_rawlog_only: boolean;
  field_count: number;
  non_meta_field_count: number;
  supported_modules: string[];
  pack_description: string | null;
  logo_url: string | null;
  logo_type: "svg" | "png" | null;
  installed_at: string;
  installed_by: string | null;
  is_pinned: boolean;
  pinned_version: string | null;
  source_revision: string | null;
  // Operator-curated product-type labels
  use_cases?: string[];
  // Vendor-level logo URL. Same value for every pack of
  // the same vendor (F5ASM / F5LTM / F5APM all share F5's logo).
  // Computed server-side in list_data_sources.
  vendor_key?: string;
  vendor_display_name?: string;
  vendor_logo_url?: string | null;
  // Origin lookup so the Installed tab + DetailDrawer can
  // surface an Edit button for user uploads. Computed server-side by
  // joining the YAML loader with the installed store.
  origin?: "bundle" | "user";
  // Operator-facing simulation guidance from the YAML's
  // `how_to_use:` field. Multi-line markdown describing multi-dataset
  // handling, CEF-wrap wire format, MR-firing quirks, MR-saturation
  // ceilings, MR-filter requirements per vendor. Rendered as a
  // "How to use" section in the DetailDrawer when non-empty.
  // Sourced server-side via `_enrich_with_vendor_meta` overlay.
  how_to_use?: string;
  // Two-tier validation marks (see BrowseRow). The
  // DetailDrawer renders the same Mapping/Raw Validated pill so the
  // mark is consistent between the Browse card and the detail view.
  validated?: boolean;
  raw_validated?: boolean;
  // How synthetic logs reach Cortex. "syslog" (default, also when
  // absent) = CEF/syslog via the broker; "http" = JSON through the
  // `http-sender` connector to an XSIAM HTTP Log Collector.
  delivery?: "syslog" | "http";
}

interface DataSourceField {
  name: string;
  type: string | null;
  is_array: boolean;
  is_meta: boolean;
  // Field description sourced from the bundled YAML. Drives
  // the agent's understanding of what a field represents when
  // generating logs.
  description?: string;
  // Synthetic-but-realistic example wire value sourced from
  // the bundled YAML. Renders as a monospace token in the drawer's
  // Example column so the operator (and any downstream modeling rule)
  // can see exactly what shape the value takes on the wire.
  example?: string;
}

interface DataSourceXdmMapping {
  xdm_path: string;
  raw_expr: string;
}

interface DataSourceWithSchema extends DataSource {
  fields: DataSourceField[];
  // The schema carries no xdm_mappings field: data sources
  // are vendor-neutral specs; XDM is Cortex-specific. The DrawerDetail
  // renders no XDM Path Mappings section.
  // Server flag indicating the response was built on-the-fly
  // from the cortex-content baked tree (uninstalled preview) vs read
  // from the install store. Drawer renders an Install CTA when true.
  is_preview?: boolean;
}

interface CatalogRow {
  pack_name: string;
  rule_name: string;
  dataset_name: string;
  field_count: number;
  non_meta_field_count: number;
  is_rawlog_only: boolean;
  logo_url: string | null;
  logo_type: "svg" | "png" | null;
  supported_modules: string[];
  pack_description: string | null;
  pack_version: string | null;
  // Operator-curated product-type labels (Firewall, WAF,
  // MFA, Storage, etc.). Replaces `categories` as the source of
  // vendor-card badges + powers the filter strip.
  use_cases?: string[];
  // Vendor-level logo URL. Same value for every pack of
  // the same vendor. Use this for InstalledCard + PackRow logos
  // (consistent within a vendor) instead of `logo_url` which is
  // per-pack.
  vendor_logo_url?: string | null;
  installed: boolean;
  // Server-enriched fields (joined from vendor_map.yaml + pack_metadata.json)
  vendor_key?: string;
  vendor_display_name?: string;
  vendor_primary_color?: string;
  categories?: string[];
  // Distinguishes operator-uploaded sources for the "User upload" badge
  origin?: "bundle" | "user";
  id?: string;  // YAML id (e.g. "AcmeCorp__AcmeCorpEvents__acmecorp_events_raw")
  // When true, render the green "Mapping Validated" pill on the
  // Browse-page row. Source: YAML's `validated:` field — the source was
  // verified end-to-end against the live tenant and its modeling rule
  // populates xdm.* (or its parsing rule extracts the columns when there is
  // no modeling rule). The strong tier.
  validated?: boolean;
  // When true, render the amber "Raw Validated" pill. Source:
  // YAML's `raw_validated:` field — the vendor's pack is NOT installed so
  // parsing/modeling can't be exercised, but a raw-dataset query confirmed our
  // synthetic data lands the exact field names the rule would read. Proven
  // shape, ready-to-map on install. Mutually exclusive with `validated`.
  raw_validated?: boolean;
  // See DataSource.delivery.
  delivery?: "syslog" | "http";
}

interface CatalogResponse {
  ok: boolean;
  rows: CatalogRow[];
  packs_scanned: number;
  rules_found: number;
  structured_rules: number;
  rawlog_rules: number;
  error?: string;
}

interface InstallResponse {
  ok: boolean;
  data_source_ids?: string[];
  fields_count?: number;
  datasets_installed?: number;
  datasets_in_rule?: number;
  pack_version?: string | null;
  error?: string;
}

type Tab = "browse" | "installed";

interface Notification {
  id: number;
  kind: "success" | "error";
  title: string;
  message: string;
}

// ── Main Page ───────────────────────────────────────────────────────

export default function DataSourcesPage() {
  const [tab, setTab] = useState<Tab>("browse");

  // Theme drives which SVG variant the logo route serves
  const { theme } = useTheme();

  // Installed state
  const [installed, setInstalled] = useState<DataSource[]>([]);
  const [installedLoading, setInstalledLoading] = useState(true);
  const [installedError, setInstalledError] = useState<string | null>(null);

  // Catalog state
  const [catalog, setCatalog] = useState<CatalogRow[] | null>(null);
  const [catalogStats, setCatalogStats] = useState<{
    packs_scanned: number;
    rules_found: number;
    structured_rules: number;
    rawlog_rules: number;
  } | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [browseSearch, setBrowseSearch] = useState("");
  const [expandedPacks, setExpandedPacks] = useState<Set<string>>(new Set());

  // Per-row install spinner key
  const [installingRowId, setInstallingRowId] = useState<string | null>(null);

  // Upload-dialog open state
  // When editingId is non-null the same dialog renders in
  // edit mode (pre-fills via GET /user/{id}, submits via PUT). The two
  // states are exclusive — opening the upload form clears editingId,
  // opening edit sets uploadOpen=true + editingId=<id>.
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  // SP-4 — versioned edit of a SYSTEM (bundle) source's how_to_use.
  // Holds the in-flight source whose guidance the operator is editing;
  // null when the editor is closed. Distinct from editingId (user uploads).
  const [editingSource, setEditingSource] = useState<DataSourceWithSchema | null>(
    null,
  );

  // SP-5 — version-history panel target (list/view/roll back). null
  // when closed.
  const [historySource, setHistorySource] = useState<DataSourceWithSchema | null>(
    null,
  );

  // Detail drawer
  const [detail, setDetail] = useState<DataSourceWithSchema | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Uninstall confirm
  const [pendingUninstall, setPendingUninstall] = useState<DataSource | null>(
    null,
  );
  const [uninstalling, setUninstalling] = useState(false);

  // Notifications
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const nextNotifId = useRef(1);

  const pushNotification = useCallback(
    (n: Omit<Notification, "id">) => {
      const id = nextNotifId.current++;
      setNotifications((prev) => [{ id, ...n }, ...prev]);
      if (n.kind === "success") {
        setTimeout(() => {
          setNotifications((prev) => prev.filter((x) => x.id !== id));
        }, 5000);
      }
    },
    [],
  );
  const dismissNotification = useCallback((id: number) => {
    setNotifications((prev) => prev.filter((x) => x.id !== id));
  }, []);

  // ── Data fetchers ────────────────────────────────────────────────

  const loadInstalled = useCallback(async () => {
    setInstalledLoading(true);
    setInstalledError(null);
    try {
      const resp = await fetch("/api/agent/data-sources", { cache: "no-store" });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${resp.status}`);
      }
      const body = (await resp.json()) as { data_sources: DataSource[] };
      setInstalled(body.data_sources);
    } catch (e) {
      setInstalledError(e instanceof Error ? e.message : String(e));
    } finally {
      setInstalledLoading(false);
    }
  }, []);

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      // Rawlog-only sources are always filtered out at the
      // catalog level. They lack structured field schemas, so they
      // can't drive vendor-faithful simulation (no schema_override
      // possible). The previous operator-facing toggle added clutter
      // without practical value. Power users can still hit
      // ?include_rawlog=true directly via curl if they really need them.
      const params = new URLSearchParams({ xsiam_only: "true" });
      const resp = await fetch(
        `/api/agent/data-sources/catalog?${params.toString()}`,
        { cache: "no-store" },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${resp.status}`);
      }
      const body = (await resp.json()) as CatalogResponse;
      if (!body.ok) throw new Error(body.error ?? "catalog returned ok=false");
      setCatalog(body.rows);
      setCatalogStats({
        packs_scanned: body.packs_scanned,
        rules_found: body.rules_found,
        structured_rules: body.structured_rules,
        rawlog_rules: body.rawlog_rules,
      });
    } catch (e) {
      setCatalogError(e instanceof Error ? e.message : String(e));
      setCatalog(null);
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  // Initial loads
  useEffect(() => {
    loadInstalled();
  }, [loadInstalled]);
  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  // ── Install / uninstall / detail ─────────────────────────────────

  const handleInstall = useCallback(
    // Accept any shape with the three identity fields so the
    // detail drawer can invoke install with a DataSourceWithSchema (preview
    // mode), not just a CatalogRow from Browse.
    async (row: { pack_name: string; rule_name: string; dataset_name: string }) => {
      const rowId = `${row.pack_name}/${row.rule_name}/${row.dataset_name}`;
      setInstallingRowId(rowId);
      try {
        const resp = await fetch("/api/agent/data-sources/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pack_name: row.pack_name,
            rule_name: row.rule_name,
            dataset_name: row.dataset_name,
          }),
        });
        const payload = (await resp.json().catch(() => ({}))) as InstallResponse;
        if (!resp.ok || !payload.ok) {
          throw new Error(payload.error ?? `HTTP ${resp.status}`);
        }
        pushNotification({
          kind: "success",
          title: "Installation complete",
          message: `Installed ${row.pack_name}/${row.rule_name}/${row.dataset_name} (${payload.fields_count ?? 0} fields).`,
        });
        await Promise.all([loadInstalled(), loadCatalog()]);
      } catch (e) {
        pushNotification({
          kind: "error",
          title: "Installation failed",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setInstallingRowId(null);
      }
    },
    [loadInstalled, loadCatalog, pushNotification],
  );

  const handleConfirmUninstall = useCallback(async () => {
    if (!pendingUninstall) return;
    setUninstalling(true);
    const row = pendingUninstall;
    try {
      const resp = await fetch(
        `/api/agent/data-sources/${encodeURIComponent(row.pack_name)}/${encodeURIComponent(row.rule_name)}/${encodeURIComponent(row.dataset_name)}`,
        { method: "DELETE" },
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${resp.status}`);
      }
      pushNotification({
        kind: "success",
        title: "Uninstalled",
        message: `Removed ${row.pack_name}/${row.rule_name}/${row.dataset_name}.`,
      });
      setPendingUninstall(null);
      setDetail(null);
      await Promise.all([loadInstalled(), loadCatalog()]);
    } catch (e) {
      pushNotification({
        kind: "error",
        title: "Uninstall failed",
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setUninstalling(false);
    }
  }, [pendingUninstall, loadInstalled, loadCatalog, pushNotification]);

  const handleOpenDetail = useCallback(
    async (row: DataSource | CatalogRow) => {
      setDetailLoading(true);
      setDetail(null);
      try {
        const resp = await fetch(
          `/api/agent/data-sources/${encodeURIComponent(row.pack_name)}/${encodeURIComponent(row.rule_name)}/${encodeURIComponent(row.dataset_name)}/schema`,
          { cache: "no-store" },
        );
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body.error ?? `HTTP ${resp.status}`);
        }
        const body = (await resp.json()) as { data_source: DataSourceWithSchema };
        setDetail(body.data_source);
      } catch (e) {
        pushNotification({
          kind: "error",
          title: "Could not load schema",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setDetailLoading(false);
      }
    },
    [pushNotification],
  );

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar relative">
      <AmbientGlow />

      <div className="relative z-10 max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {/* Page Header */}
        <header>
          <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
            Data Sources
          </h1>
          <p className="text-sm text-on-surface-variant mt-1.5 max-w-2xl">
            Vendor-faithful log schemas. Installed schemas drive how Phantom
            generates simulated logs for that vendor.
          </p>
        </header>

        {/* Tabs */}
        <div className="flex items-center gap-6 border-b border-outline-variant/15 pb-0">
          <div className="flex gap-1">
            <TabButton
              label="Browse"
              active={tab === "browse"}
              onClick={() => setTab("browse")}
            />
            <TabButton
              label={`Installed (${installed.length})`}
              active={tab === "installed"}
              onClick={() => setTab("installed")}
            />
          </div>
          <div className="ml-auto flex items-center gap-3 pb-3">
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider text-primary hover:text-primary/80 transition-colors"
              title="Upload a custom data_source.yaml"
            >
              <span className="material-symbols-outlined text-base">
                upload_file
              </span>
              Upload data source
            </button>
            <button
              type="button"
              onClick={tab === "browse" ? loadCatalog : loadInstalled}
              className="text-on-surface-variant hover:text-on-surface flex items-center gap-1.5 text-xs font-mono uppercase tracking-wider transition-colors"
            >
              <span className="material-symbols-outlined text-base">refresh</span>
              Refresh
            </button>
          </div>
        </div>

        {/* Notification stack */}
        {notifications.length > 0 && (
          <NotificationStack
            notifications={notifications}
            onDismiss={dismissNotification}
          />
        )}

        {/* Tab body */}
        {tab === "browse" ? (
          <BrowseSection
            catalog={catalog}
            stats={catalogStats}
            loading={catalogLoading}
            error={catalogError}
            search={browseSearch}
            onSearchChange={setBrowseSearch}
            onReload={loadCatalog}
            onInstall={handleInstall}
            installingRowId={installingRowId}
            expandedPacks={expandedPacks}
            onToggleExpanded={(packName) => {
              setExpandedPacks((prev) => {
                const next = new Set(prev);
                if (next.has(packName)) next.delete(packName);
                else next.add(packName);
                return next;
              });
            }}
            onOpenDetail={handleOpenDetail}
            onEdit={(id) => {
              setEditingId(id);
              setUploadOpen(true);
            }}
            theme={theme}
          />
        ) : (
          <InstalledSection
            rows={installed}
            loading={installedLoading}
            error={installedError}
            onOpenDetail={handleOpenDetail}
            onUninstall={setPendingUninstall}
            onEdit={(id) => {
              setEditingId(id);
              setUploadOpen(true);
            }}
            onSwitchToBrowse={() => setTab("browse")}
            theme={theme}
          />
        )}
      </div>

      {/* Drawer (right-slide) */}
      {(detail || detailLoading) && (
        <DetailDrawer
          detail={detail}
          loading={detailLoading}
          onClose={() => setDetail(null)}
          onUninstall={(ds) => setPendingUninstall(ds)}
          onInstall={async (row) => {
            await handleInstall(row);
            // After install, refetch the schema so the drawer flips from
            // preview mode to installed mode (is_preview: false + xdm_mappings).
            await handleOpenDetail({ ...row } as CatalogRow);
          }}
          onEdit={(id) => {
            setEditingId(id);
            setUploadOpen(true);
            setDetail(null);
          }}
          onEditSystem={(d) => setEditingSource(d)}
          onHistory={(d) => setHistorySource(d)}
          installing={
            !!detail &&
            installingRowId ===
              `${detail.pack_name}/${detail.rule_name}/${detail.dataset_name}`
          }
          theme={theme}
        />
      )}

      {/* Uninstall confirm modal */}
      {pendingUninstall && (
        <UninstallModal
          row={pendingUninstall}
          uninstalling={uninstalling}
          onCancel={() => setPendingUninstall(null)}
          onConfirm={handleConfirmUninstall}
        />
      )}

      {/* SP-4 — versioned how_to_use editor for system sources. */}
      {editingSource && (
        <EditDataSourceModal
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSaved={async (newVersion) => {
            const saved = editingSource;
            setEditingSource(null);
            pushNotification({
              kind: "success",
              title: "Guidance saved",
              message: `${saved.pack_name} now on version ${newVersion}. The original is preserved as version 1.`,
            });
            // Refetch the drawer so the edited how_to_use shows immediately.
            if (detail) await handleOpenDetail(saved);
          }}
        />
      )}

      {/* SP-5 — version history + rollback panel. */}
      {historySource && (
        <VersionHistoryModal
          source={historySource}
          onClose={() => setHistorySource(null)}
          onChanged={async (newVersion) => {
            const src = historySource;
            setHistorySource(null);
            pushNotification({
              kind: "success",
              title: "Rolled back",
              message: `${src.pack_name} is now on version ${newVersion} (the prior versions are kept in history).`,
            });
            if (detail) await handleOpenDetail(src);
          }}
        />
      )}

      {/* Upload dialog; also handles edit. */}
      <UploadDataSourceDialog
        open={uploadOpen}
        editId={editingId}
        onClose={() => {
          setUploadOpen(false);
          setEditingId(null);
        }}
        onUploaded={(id) => {
          const isEdit = Boolean(editingId);
          pushNotification({
            kind: "success",
            title: isEdit ? "Changes saved" : "Upload committed",
            message: isEdit
              ? `Updated data source ${id}.`
              : `Uploaded data source ${id}.`,
          });
          loadCatalog();
          // Also refresh the Installed list so the edit
          // shows on the Installed tab (if currently installed).
          if (isEdit) loadInstalled();
        }}
      />
    </div>
  );
}

// ── Tab button ──────────────────────────────────────────────────────

/**
 * Small "HTTP" pill for data sources whose `delivery` is "http". Those
 * sources are sent through the `http-sender` connector as JSON, not through
 * the syslog/CEF data-worker path, so operators need to tell them apart on
 * sight. Renders nothing for syslog (the default).
 */
function HttpDeliveryPill({
  delivery,
  className = "",
}: {
  delivery?: "syslog" | "http";
  className?: string;
}) {
  if (delivery !== "http") return null;
  return (
    <span
      className={`text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/30 ${className}`}
      title="Delivered through the http-sender connector as JSON (HTTP collector), not syslog/CEF"
    >
      HTTP
    </span>
  );
}

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative px-4 py-2.5 text-xs font-mono uppercase tracking-wider transition-colors ${
        active
          ? "text-primary font-bold"
          : "text-on-surface-variant hover:text-on-surface"
      }`}
      aria-pressed={active}
    >
      {label}
      {active && (
        <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-t" />
      )}
    </button>
  );
}

// ── Ambient background glow ─────────────────────────────────────────

function AmbientGlow() {
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-primary/[0.04] rounded-full blur-[120px]" />
      <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] bg-secondary/[0.04] rounded-full blur-[100px]" />
    </div>
  );
}

// ── Notification stack ──────────────────────────────────────────────

function NotificationStack({
  notifications,
  onDismiss,
}: {
  notifications: Notification[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      {notifications.map((n) => (
        <div
          key={n.id}
          className={`glass-panel rounded-lg border p-4 flex items-start gap-3 relative overflow-hidden ${
            n.kind === "success"
              ? "border-secondary/20"
              : "border-error/20"
          }`}
        >
          <div
            className={`absolute -left-10 -top-10 w-24 h-24 rounded-full blur-2xl pointer-events-none ${
              n.kind === "success" ? "bg-secondary/10" : "bg-error/20"
            }`}
          />
          <span
            className={`material-symbols-outlined flex-shrink-0 mt-0.5 ${
              n.kind === "success" ? "text-secondary" : "text-error"
            }`}
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            {n.kind === "success" ? "check_circle" : "error"}
          </span>
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-headline font-semibold text-on-surface mb-0.5">
              {n.title}
            </h4>
            <p className="text-sm text-on-surface-variant">{n.message}</p>
          </div>
          <button
            type="button"
            onClick={() => onDismiss(n.id)}
            aria-label="Dismiss"
            className="text-on-surface-variant hover:text-on-surface transition-colors p-1 rounded flex-shrink-0"
          >
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        </div>
      ))}
    </div>
  );
}

// ── Browse section ──────────────────────────────────────────────────

function BrowseSection({
  catalog,
  stats,
  loading,
  error,
  search,
  onSearchChange,
  onReload,
  onInstall,
  installingRowId,
  expandedPacks,
  onToggleExpanded,
  onOpenDetail,
  onEdit,
  theme,
}: {
  catalog: CatalogRow[] | null;
  stats: {
    packs_scanned: number;
    rules_found: number;
    structured_rules: number;
    rawlog_rules: number;
  } | null;
  loading: boolean;
  error: string | null;
  search: string;
  onSearchChange: (s: string) => void;
  onReload: () => void;
  onInstall: (row: CatalogRow) => void;
  installingRowId: string | null;
  expandedPacks: Set<string>;
  onToggleExpanded: (packName: string) => void;
  onOpenDetail: (row: CatalogRow) => void;
  // Opens the upload dialog in edit mode for the given id.
  onEdit: (id: string) => void;
  theme: Theme;
}) {
  // Operator-curated use-case filter. Selected labels
  // narrow the vendor grid to vendors whose use_cases intersect the
  // selection. Empty selection = no filter (show all). Set so we
  // can quickly check membership.
  const [selectedUseCases, setSelectedUseCases] = useState<Set<string>>(new Set());

  // Origin filter. "all" shows everything; "bundle" shows
  // only the image-baked System sources; "user" shows only operator-
  // uploaded sources from /app/data/user_data_sources/. Rows missing
  // the optional `origin` field are treated as bundle (default for
  // pre-enrichment catalog shapes).
  const [originFilter, setOriginFilter] = useState<"all" | "bundle" | "user">("all");

  // Group rows by pack_name
  const grouped = useMemo(() => {
    const m = new Map<string, CatalogRow[]>();
    if (!catalog) return m;
    const lowered = search.trim().toLowerCase();
    for (const r of catalog) {
      if (lowered) {
        const hay = [
          r.pack_name,
          r.rule_name,
          r.dataset_name,
          r.pack_description ?? "",
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(lowered)) continue;
      }
      // Origin filter. "bundle" rejects user-uploaded;
      // "user" rejects bundle (and undefined-origin legacy rows).
      if (originFilter === "bundle" && r.origin === "user") continue;
      if (originFilter === "user" && r.origin !== "user") continue;
      // Use-case filter. If any chips are selected, the
      // vendor must have at least one matching use_case to survive.
      if (selectedUseCases.size > 0) {
        const matches = (r.use_cases ?? []).some((uc) => selectedUseCases.has(uc));
        if (!matches) continue;
      }
      // Group by vendor_key, not pack_name. Multiple packs of
      // the same vendor (Microsoft has 26, Cisco has 9, etc.) coalesce into
      // one outer card; the inner pack list expands on click. Fall back to
      // pack_name as the group key when vendor_key is absent (older catalog
      // shapes without enrichment).
      const key = r.vendor_key ?? r.pack_name;
      const list = m.get(key) ?? [];
      list.push(r);
      m.set(key, list);
    }
    return m;
  }, [catalog, search, selectedUseCases, originFilter]);

  // Compute the full set of use_cases present in the
  // catalog (across ALL rows, not just the filtered ones) so the
  // filter chip strip is stable as the operator toggles chips.
  // Counts come from the FILTERED set so chips reflect what's
  // currently visible.
  const useCaseChips = useMemo(() => {
    if (!catalog) return [];
    const totalsAll = new Map<string, number>();
    for (const r of catalog) {
      for (const uc of r.use_cases ?? []) {
        totalsAll.set(uc, (totalsAll.get(uc) ?? 0) + 1);
      }
    }
    return Array.from(totalsAll.entries())
      .sort((a, b) => {
        // Selected chips float to the front so the active set is
        // easy to see + uncheck. Then by count desc, then alpha.
        const aSel = selectedUseCases.has(a[0]) ? 0 : 1;
        const bSel = selectedUseCases.has(b[0]) ? 0 : 1;
        if (aSel !== bSel) return aSel - bSel;
        if (a[1] !== b[1]) return b[1] - a[1];
        return a[0].localeCompare(b[0]);
      })
      .map(([label, count]) => ({ label, count }));
  }, [catalog, selectedUseCases]);

  const toggleUseCase = useCallback((uc: string) => {
    setSelectedUseCases((prev) => {
      const next = new Set(prev);
      if (next.has(uc)) next.delete(uc);
      else next.add(uc);
      return next;
    });
  }, []);

  const clearUseCases = useCallback(() => setSelectedUseCases(new Set()), []);

  // Sort vendor groups by display_name (case-insensitive).
  const vendorKeys = useMemo(() => {
    return Array.from(grouped.keys()).sort((a, b) => {
      const ar = grouped.get(a)?.[0];
      const br = grouped.get(b)?.[0];
      const an = (ar?.vendor_display_name ?? a).toLowerCase();
      const bn = (br?.vendor_display_name ?? b).toLowerCase();
      return an.localeCompare(bn);
    });
  }, [grouped]);

  if (error) return <ErrorPanel message={error} onRetry={onReload} />;

  return (
    <section className="space-y-5">
      {/* Toolbar */}
      <div className="glass-panel rounded-xl p-4 flex flex-col md:flex-row gap-3 items-stretch md:items-center">
        <div className="relative flex-1">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-base">
            search
          </span>
          <input
            type="text"
            placeholder="Search vendor, pack, or dataset…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full bg-surface-container-lowest border border-outline-variant/25 text-on-surface text-sm font-mono rounded-lg pl-10 pr-9 py-2.5 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors placeholder:text-on-surface-variant/60"
          />
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-error transition-colors p-1"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          )}
        </div>
        {/* Origin filter. "System" = image-baked bundle
            (the 197+ vendor catalogue that ships with the release).
            "User" = operator-uploaded sources written to the
            phantom_mcp_data volume via the upload dialog. Native
            select kept simple — 3 options, doesn't merit a custom
            popover dropdown. */}
        <label className="flex items-center gap-2 text-sm text-on-surface-variant px-2 shrink-0">
          <span className="material-symbols-outlined text-base">filter_list</span>
          <span className="hidden sm:inline">Source</span>
          <select
            value={originFilter}
            onChange={(e) => setOriginFilter(e.target.value as "all" | "bundle" | "user")}
            aria-label="Filter by data source origin"
            className="bg-surface-container-lowest border border-outline-variant/25 text-on-surface text-sm rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
          >
            <option value="all">All</option>
            <option value="bundle">System</option>
            <option value="user">User</option>
          </select>
        </label>
      </div>

      {/* Stats summary */}
      {stats && !loading && (
        <div className="flex items-center gap-2 text-xs font-mono text-on-surface-variant px-1">
          <span>{stats.packs_scanned} packs</span>
          <span className="text-outline-variant">·</span>
          <span>{stats.rules_found} rules shown</span>
          <span className="text-outline-variant">·</span>
          <span className="text-secondary">{stats.structured_rules} structured</span>
          {stats.rawlog_rules > 0 && (
            <>
              <span className="text-outline-variant">·</span>
              <span className="text-tertiary">{stats.rawlog_rules} rawlog-only</span>
            </>
          )}
        </div>
      )}

      {/* Use-case filter, dropdown form. Material 3 styled trigger + floating
          multi-select panel. Operator picks multiple use cases (Cisco
          is Firewall AND EDR; one source matches multiple types per
          the YAML's use_cases[]). Selected use cases also render as
          inline removable pills below the trigger so the active set is
          visible without opening the panel. */}
      {useCaseChips.length > 0 && (
        <UseCaseFilter
          chips={useCaseChips}
          selected={selectedUseCases}
          onToggle={toggleUseCase}
          onClearAll={clearUseCases}
          onSelectAll={() => setSelectedUseCases(new Set(useCaseChips.map((c) => c.label)))}
        />
      )}

      {/* Grid */}
      {loading && catalog === null ? (
        <SkeletonGrid />
      ) : vendorKeys.length === 0 ? (
        <EmptyState
          icon="search_off"
          headline="No matching packs"
          body={
            search
              ? "Try a different search term or clear the filter."
              : "Catalog returned zero results."
          }
          ctaLabel={search ? "Clear search" : undefined}
          onCta={search ? () => onSearchChange("") : undefined}
        />
      ) : (
        // `grid-flow-row-dense` lets the auto-placer backfill gaps
        // when an expanded tray (full-row span) is inserted between cards.
        // Without it, sibling cards on the same row as an expanded card would
        // stretch to match the tray height — operator perceived that as
        // "neighbours expanding too." With dense flow + the tray pulled out
        // of VendorCard, sibling cards stay at constant height and subsequent
        // rows get pushed down instead.
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 grid-flow-row-dense">
          {vendorKeys.map((vendorKey) => {
            const rows = grouped.get(vendorKey)!;
            const first = rows[0];
            const vendorDisplay = first.vendor_display_name ?? vendorKey;
            // Pick the logo URL from the FIRST row that
            // actually has one, not just rows[0]. If
            // rows[0]'s logo_url is null/404, the whole vendor
            // card would show the placeholder icon EVEN WHEN OTHER
            // packs in the same vendor group carry valid logos.
            // Fallback to null when no row
            // has a logo — LogoOrFallback then renders inventory_2.
            const logoRow = rows.find((r) => r.logo_url) ?? first;
            const cardLogoUrl = logoRow.logo_url ?? null;
            // Badges come from the operator-curated `use_cases`, not the
            // XSIAM platform `categories`. Dedupe
            // across all the vendor's packs (most vendors are 1-3
            // use_cases; same value usually repeats per pack).
            const useCaseSet = new Set<string>();
            for (const r of rows) {
              for (const uc of r.use_cases ?? []) useCaseSet.add(uc);
            }
            const badges = Array.from(useCaseSet).slice(0, 4);
            const allInstalled = rows.every((r) => r.installed);
            const someInstalled = rows.some((r) => r.installed);
            const isExpanded = expandedPacks.has(vendorKey);
            // Operator-uploaded vendor badge
            const hasUserUpload = rows.some((r) => r.origin === "user");
            return (
              <Fragment key={vendorKey}>
                <VendorCard
                  vendorKey={vendorKey}
                  vendorDisplay={vendorDisplay}
                  rowsCount={rows.length}
                  logoUrl={withLightVariant(cardLogoUrl)}
                  badges={badges}
                  expanded={isExpanded}
                  allInstalled={allInstalled}
                  someInstalled={someInstalled}
                  hasUserUpload={hasUserUpload}
                  onToggle={() => onToggleExpanded(vendorKey)}
                />
                {isExpanded && (
                  <ExpandedTray
                    vendorKey={vendorKey}
                    rows={rows}
                    onInstall={onInstall}
                    installingRowId={installingRowId}
                    onOpenDetail={onOpenDetail}
                    onEdit={onEdit}
                  />
                )}
              </Fragment>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Use-case filter dropdown ─────────────────────────────
//
// Material 3 styled
// multi-select dropdown (instead of a long chip strip):
//
//   * Trigger: pill-shaped button with filter icon, label, count badge
//     of currently selected use cases, and chevron-down indicator.
//   * Panel: floating absolute-positioned card with rounded corners +
//     soft shadow + glass-panel styling. Width caps at ~340px so it
//     fits next to the trigger without crowding.
//   * Panel header: "Filter by use case" title + Select-all / Clear
//     actions.
//   * Search input within the panel — 44 use cases is plenty for
//     keyboard navigation but a filter input is faster.
//   * Scrollable checkbox list. Selected items float to the top
//     (operator can quickly uncheck without scrolling back).
//   * Inline selected pills below the trigger so the active filter set
//     is visible at a glance without opening the panel; click any pill
//     to remove that filter.
//
// Click-outside + Escape-key close. Same `useEffect + ref` pattern as
// ApprovalModeDropdown in chat-header.tsx (kept consistent for theme +
// behavior across the app).

interface UseCaseChip {
  label: string;
  count: number;
}

function UseCaseFilter({
  chips,
  selected,
  onToggle,
  onClearAll,
  onSelectAll,
}: {
  chips: UseCaseChip[];
  selected: Set<string>;
  onToggle: (uc: string) => void;
  onClearAll: () => void;
  onSelectAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const filterInputRef = useRef<HTMLInputElement>(null);

  // Close on click-outside + Escape
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  // Auto-focus the panel filter input when the dropdown opens so the
  // operator can start typing immediately.
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => filterInputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Reset filter input when the panel closes so the next open starts fresh.
  useEffect(() => {
    if (!open) setFilter("");
  }, [open]);

  const selectedCount = selected.size;
  const allCount = chips.length;

  // Filter + sort: selected → matches → by count desc → alpha.
  const visibleChips = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return chips
      .filter((c) => (q ? c.label.toLowerCase().includes(q) : true))
      .sort((a, b) => {
        const aSel = selected.has(a.label) ? 0 : 1;
        const bSel = selected.has(b.label) ? 0 : 1;
        if (aSel !== bSel) return aSel - bSel;
        if (a.count !== b.count) return b.count - a.count;
        return a.label.localeCompare(b.label);
      });
  }, [chips, selected, filter]);

  // Inline pills (below trigger) — only renders when selection is
  // non-empty. Capped to first 6 to avoid runaway; "+N more" indicator
  // for the rest, click opens the panel.
  const inlinePills = useMemo(
    () => chips.filter((c) => selected.has(c.label)).slice(0, 6),
    [chips, selected],
  );
  const overflowCount = selectedCount - inlinePills.length;

  return (
    <div ref={ref} className="relative px-1">
      <div className="flex flex-wrap items-center gap-2">
        {/* Trigger */}
        <button
          type="button"
          onClick={() => setOpen((p) => !p)}
          aria-haspopup="listbox"
          aria-expanded={open}
          className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-xs font-mono transition-all border ${
            selectedCount > 0
              ? "bg-primary/15 text-primary border-primary/40 hover:bg-primary/20"
              : "bg-surface-container-lowest/60 text-on-surface-variant border-outline-variant/30 hover:bg-surface-container/80 hover:text-on-surface"
          }`}
        >
          <span className="material-symbols-outlined text-sm">filter_list</span>
          <span className="uppercase tracking-wider">Use case</span>
          {selectedCount > 0 && (
            <span className="bg-primary text-on-primary rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none">
              {selectedCount}
            </span>
          )}
          <span
            className={`material-symbols-outlined text-sm transition-transform ${
              open ? "rotate-180" : ""
            }`}
          >
            arrow_drop_down
          </span>
        </button>

        {/* Inline removable pills */}
        {inlinePills.map((c) => (
          <button
            key={c.label}
            type="button"
            onClick={() => onToggle(c.label)}
            className="group inline-flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded-full bg-primary/10 text-primary border border-primary/25 hover:bg-primary/20 transition-colors"
            title={`Remove "${c.label}" filter`}
          >
            <span>{c.label}</span>
            <span className="material-symbols-outlined text-[12px] opacity-60 group-hover:opacity-100 transition-opacity">
              close
            </span>
          </button>
        ))}
        {overflowCount > 0 && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="text-[10px] font-mono px-2 py-1 rounded-full bg-surface-container/60 text-on-surface-variant border border-outline-variant/30 hover:text-on-surface transition-colors"
          >
            +{overflowCount} more
          </button>
        )}
      </div>

      {/* Floating panel */}
      {open && (
        <div
          role="listbox"
          aria-multiselectable
          className="absolute left-1 top-full mt-2 z-50 w-[340px] max-w-[calc(100vw-2rem)] glass-panel rounded-2xl border border-outline-variant/30 shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-outline-variant/15 flex items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-on-surface">
                Filter by use case
              </div>
              <div className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant mt-0.5">
                {selectedCount} of {allCount} selected
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              {selectedCount < allCount && (
                <button
                  type="button"
                  onClick={onSelectAll}
                  className="text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded-md text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-colors"
                  title="Select all use cases"
                >
                  All
                </button>
              )}
              {selectedCount > 0 && (
                <button
                  type="button"
                  onClick={onClearAll}
                  className="text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded-md text-on-surface-variant hover:text-error hover:bg-error/10 transition-colors"
                  title="Clear all selections"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {/* Filter input */}
          <div className="px-3 pt-3 pb-2">
            <div className="relative">
              <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-base pointer-events-none">
                search
              </span>
              <input
                ref={filterInputRef}
                type="text"
                placeholder="Filter use cases…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="w-full bg-surface-container-lowest border border-outline-variant/25 text-on-surface text-xs font-mono rounded-lg pl-9 pr-2.5 py-1.5 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors placeholder:text-on-surface-variant/50"
              />
            </div>
          </div>

          {/* Checkbox list */}
          <div className="max-h-[320px] overflow-y-auto custom-scrollbar py-1">
            {visibleChips.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-on-surface-variant/70 italic">
                No use cases match &ldquo;{filter}&rdquo;
              </div>
            ) : (
              visibleChips.map((c) => {
                const isSelected = selected.has(c.label);
                return (
                  <button
                    key={c.label}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => onToggle(c.label)}
                    className={`w-full flex items-center gap-2.5 px-4 py-2 text-xs transition-colors ${
                      isSelected
                        ? "bg-primary/8 text-on-surface hover:bg-primary/15"
                        : "text-on-surface hover:bg-surface-container/60"
                    }`}
                  >
                    {/* Custom checkbox — bigger touch target + M3-aligned shape */}
                    <span
                      className={`flex-none w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
                        isSelected
                          ? "bg-primary border-primary"
                          : "border-outline-variant/50"
                      }`}
                      aria-hidden="true"
                    >
                      {isSelected && (
                        <span className="material-symbols-outlined text-on-primary text-[13px] leading-none">
                          check
                        </span>
                      )}
                    </span>
                    <span className="flex-1 text-left font-mono">{c.label}</span>
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded-full ${
                        isSelected
                          ? "bg-primary/20 text-primary"
                          : "bg-surface-container/50 text-on-surface-variant"
                      }`}
                    >
                      {c.count}
                    </span>
                  </button>
                );
              })
            )}
          </div>

          {/* Footer hint */}
          <div className="px-4 py-2 border-t border-outline-variant/15 text-[10px] font-mono uppercase tracking-wider text-on-surface-variant/70">
            Multiple selections = OR (any match)
          </div>
        </div>
      )}
    </div>
  );
}

// ── Vendor card ────────────────────
// Constant-height card: icon LEFT, title + badges + chevron RIGHT.
// The expanded inner pack list moved OUT to ExpandedTray (rendered as
// a separate full-row sibling in the grid) so neighbour cards don't
// stretch when this card is expanded.

function VendorCard({
  vendorKey,
  vendorDisplay,
  rowsCount,
  logoUrl,
  badges,
  expanded,
  allInstalled,
  someInstalled,
  hasUserUpload,
  onToggle,
}: {
  vendorKey: string;
  vendorDisplay: string;
  rowsCount: number;
  logoUrl: string | null;
  badges: string[];
  expanded: boolean;
  allInstalled: boolean;
  someInstalled: boolean;
  hasUserUpload?: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={`glass-panel rounded-xl ghost-border overflow-hidden flex transition-colors ${
        expanded ? "border-primary/40" : "hover:border-primary/30"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex items-stretch text-left w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded-xl"
        aria-expanded={expanded}
        aria-controls={`vendor-tray-${vendorKey}`}
      >
        {/* Icon panel — 112px wide. Constant near-white background that
            does NOT change with theme, so every logo is visible in both
            themes regardless of its color makeup. Routed through
            LogoOrFallback so 404s render the inventory_2 icon instead of
            leaving the panel blank. */}
        <LogoOrFallback
          logoUrl={logoUrl}
          alt={`${vendorDisplay} logo`}
          panelClassName="flex-none w-28 border-r border-outline-variant/20 flex items-center justify-center p-3"
          imgClassName="max-h-[72px] max-w-[88px] object-contain"
          iconClassName="material-symbols-outlined text-4xl text-on-surface-variant/40"
        />
        {/* Body */}
        <div className="flex-1 min-w-0 p-4 flex flex-col justify-center gap-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <h3
                className="font-headline font-bold text-on-surface truncate text-lg leading-tight"
                title={vendorDisplay}
              >
                {vendorDisplay}
              </h3>
              <p className="text-xs text-on-surface-variant font-mono mt-0.5">
                {rowsCount} data source{rowsCount === 1 ? "" : "s"}
                {allInstalled ? " · all installed" : someInstalled ? " · some installed" : ""}
              </p>
            </div>
            <span
              className={`material-symbols-outlined text-on-surface-variant/70 transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
              aria-hidden="true"
            >
              expand_more
            </span>
          </div>
          {/* Category badges */}
          {(badges.length > 0 || hasUserUpload) && (
            <div className="flex flex-wrap gap-1.5">
              {hasUserUpload && (
                <span
                  className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-tertiary/15 text-tertiary border border-tertiary/25"
                  title="At least one data source under this vendor was uploaded by the operator"
                >
                  User upload
                </span>
              )}
              {badges.map((badge) => (
                <span
                  key={badge}
                  className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/15"
                >
                  {badge}
                </span>
              ))}
            </div>
          )}
        </div>
      </button>
    </div>
  );
}

// ── Expanded tray ─────────────────────────────────────────
// Full-row-wide sibling rendered AFTER an expanded VendorCard in the
// grid. `col-span-full` forces it onto a new row spanning all columns
// so siblings on the same visual row as the expanded card stay
// constant height. `grid-auto-flow: row dense` (applied to the parent
// grid) lets the auto-placer backfill any gap left in the same row.

function ExpandedTray({
  vendorKey,
  rows,
  onInstall,
  installingRowId,
  onOpenDetail,
  onEdit,
}: {
  vendorKey: string;
  rows: CatalogRow[];
  onInstall: (row: CatalogRow) => void;
  installingRowId: string | null;
  onOpenDetail: (row: CatalogRow) => void;
  onEdit: (id: string) => void;
}) {
  return (
    <div
      id={`vendor-tray-${vendorKey}`}
      className="col-span-full glass-panel rounded-xl ghost-border border-primary/30 overflow-hidden divide-y divide-outline-variant/10"
    >
      {rows
        .slice()
        .sort((a, b) => a.pack_name.localeCompare(b.pack_name))
        .map((row) => (
          <PackRow
            key={`${row.pack_name}/${row.rule_name}/${row.dataset_name}`}
            row={row}
            installing={
              installingRowId === `${row.pack_name}/${row.rule_name}/${row.dataset_name}`
            }
            onInstall={() => onInstall(row)}
            onOpenDetail={() => onOpenDetail(row)}
            onEdit={onEdit}
          />
        ))}
    </div>
  );
}

// Single data-source row inside an expanded VendorCard.
function PackRow({
  row,
  installing,
  onInstall,
  onOpenDetail,
  onEdit,
}: {
  row: CatalogRow;
  installing: boolean;
  onInstall: () => void;
  onOpenDetail: () => void;
  // Opens the edit dialog for user-uploaded sources. Only
  // rendered when `row.origin === "user"`.
  onEdit: (id: string) => void;
}) {
  const modules = filterAgentix(row.supported_modules);
  const isUser = row.origin === "user";
  // Export YAML. Sits to the left of Install/installed
  // affordance. Hits /api/agent/data-sources/{pack}/{rule}/{dataset}/export,
  // which streams the raw on-disk YAML with a Content-Disposition
  // attachment header so the browser saves it to disk.
  const exportHref =
    `/api/agent/data-sources/${encodeURIComponent(row.pack_name)}` +
    `/${encodeURIComponent(row.rule_name)}` +
    `/${encodeURIComponent(row.dataset_name)}/export`;
  return (
    <div className="flex items-center gap-3 px-4 py-3 hover:bg-surface-container/30 transition-colors">
      <button
        type="button"
        onClick={onOpenDetail}
        className="flex-1 min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded -m-1 p-1"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-sm text-on-surface truncate">
            {row.pack_name}
          </span>
          {row.is_rawlog_only && (
            <span className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-tertiary/10 text-tertiary border border-tertiary/15">
              rawlog
            </span>
          )}
          {isUser && (
            <span
              className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary border border-tertiary/25"
              title="Operator-uploaded data source"
            >
              user
            </span>
          )}
          <HttpDeliveryPill delivery={row.delivery} />
          {/* Two-tier validation pill. MAPPING (green): the
              modeling rule populates xdm.* on the live tenant (or the parsing
              rule extracts columns when there's no modeling rule) — proven to
              map. RAW (amber): the pack isn't installed so mapping can't be
              exercised, but a raw-dataset query confirmed our data lands the
              exact field names the rule would read — proven shape, ready-to-map.
              The two are mutually exclusive; mapping takes precedence. */}
          {row.validated ? (
            <span
              className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-secondary/15 text-secondary border border-secondary/30"
              title="Mapping-validated: tested live on XSIAM — the modeling rule populates xdm.* (or the parsing rule extracts columns). Proven to map."
            >
              Mapping Validated
            </span>
          ) : row.raw_validated ? (
            <span
              className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary border border-tertiary/30"
              title="Raw-validated: the vendor pack isn't installed, but a raw-dataset query confirmed our synthetic data lands the exact field names the rule would read. Proven shape, ready-to-map on install."
            >
              Raw Validated
            </span>
          ) : null}
        </div>
        <p className="text-xs text-on-surface-variant font-mono mt-0.5 truncate">
          {row.rule_name} / {row.dataset_name} · {row.non_meta_field_count} fields
          {modules.length > 0 ? ` · ${modules.slice(0, 3).join(", ")}` : ""}
        </p>
      </button>
      {/* Edit affordance for user uploads. Sits between the
          title and Install/installed status so the operator can hit it
          regardless of install state. Bundled (origin === "bundle") rows
          have no Edit affordance; they're read-only by spec. */}
      {isUser && row.id && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onEdit(row.id!);
          }}
          className="flex-none flex items-center gap-1 text-xs font-mono text-on-surface-variant hover:text-primary px-2 py-1 rounded-md hover:bg-primary/10 transition-colors"
          aria-label="Edit data source"
          title="Edit this user-uploaded data source"
        >
          <span className="material-symbols-outlined text-sm">edit</span>
          Edit
        </button>
      )}
      {/* Export YAML. Always-visible alongside Install or
          the installed badge so operators can grab the spec at any
          point in the install lifecycle (e.g. fork a bundled pack into
          a user upload without installing it first). Renders as an
          anchor with `download` so the browser saves rather than
          navigates; styled to match the Edit affordance below. */}
      <a
        href={exportHref}
        // Filename is just the dataset name (e.g.
        // `aws_waf_raw.yaml`). The server's Content-Disposition is
        // authoritative; this `download` attr is a hint for browsers
        // that ignore the header.
        download={`${row.dataset_name}.yaml`}
        onClick={(e) => e.stopPropagation()}
        className="flex-none flex items-center gap-1 text-xs font-mono text-on-surface-variant hover:text-primary px-2 py-1 rounded-md hover:bg-primary/10 transition-colors"
        aria-label="Export data source YAML"
        title="Download this pack's data_source.yaml"
      >
        <span className="material-symbols-outlined text-sm">download</span>
        Export
      </a>
      {row.installed ? (
        <span className="flex-none flex items-center gap-1 text-xs font-mono text-secondary px-2 py-1">
          <span className="material-symbols-outlined text-sm">check_circle</span>
          installed
        </span>
      ) : (
        <button
          type="button"
          onClick={onInstall}
          disabled={installing}
          /* Pill-shaped filled button. Solid `bg-primary text-on-primary`
             gives WCAG AAA contrast in both themes; `rounded-full`
             is the M3 button shape we use elsewhere. */
          className="flex-none px-4 py-1.5 text-xs font-medium rounded-full bg-primary text-on-primary hover:bg-primary-dim disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          {installing ? "Installing…" : "Install"}
        </button>
      )}
    </div>
  );
}

// ── Installed section ───────────────────────────────────────────────

function InstalledSection({
  rows,
  loading,
  error,
  onOpenDetail,
  onUninstall,
  onEdit,
  onSwitchToBrowse,
  theme,
}: {
  rows: DataSource[];
  loading: boolean;
  error: string | null;
  onOpenDetail: (row: DataSource) => void;
  onUninstall: (row: DataSource) => void;
  // Opens edit dialog. Only triggered for `origin === "user"`.
  onEdit: (id: string) => void;
  onSwitchToBrowse: () => void;
  theme: Theme;
}) {
  if (error) return <ErrorPanel message={error} onRetry={() => location.reload()} />;
  if (loading && rows.length === 0) return <SkeletonGrid />;
  if (rows.length === 0) {
    return (
      <EmptyState
        icon="inventory_2"
        headline="No data sources installed yet"
        body="Browse the catalog to add vendor schemas. Phantom uses installed schemas to generate vendor-faithful simulated logs."
        ctaLabel="Open Browse"
        onCta={onSwitchToBrowse}
      />
    );
  }
  return (
    <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      {rows.map((row) => (
        <InstalledCard
          key={row.id}
          row={row}
          onOpenDetail={() => onOpenDetail(row)}
          onUninstall={() => onUninstall(row)}
          onEdit={onEdit}
          theme={theme}
        />
      ))}
    </section>
  );
}

// ── Browse pack card ────────────────────────────────────────────────

function BrowsePackCard({
  packName,
  rows,
  logoUrl,
  description,
  packVersion,
  supportedModules,
  expanded,
  allInstalled,
  someInstalled,
  onToggle,
  onInstall,
  installingRowId,
  onOpenDetail,
}: {
  packName: string;
  rows: CatalogRow[];
  logoUrl: string | null;
  description: string | null;
  packVersion: string | null;
  supportedModules: string[];
  expanded: boolean;
  allInstalled: boolean;
  someInstalled: boolean;
  onToggle: () => void;
  onInstall: (row: CatalogRow) => void;
  installingRowId: string | null;
  onOpenDetail: (row: CatalogRow) => void;
}) {
  return (
    <div className="glass-panel rounded-xl ghost-border flex flex-col overflow-hidden hover:border-primary/30 transition-colors">
      {/* Logo banner — routed through LogoOrFallback for
          (a) constant near-white background, and (b) fallback
          inventory_2 icon on 404. */}
      <LogoOrFallback
        logoUrl={logoUrl}
        alt={`${packName} logo`}
        panelClassName="h-24 flex items-center justify-center px-5 py-3 border-b border-outline-variant/10"
        imgClassName="max-h-full max-w-[160px] object-contain"
        iconClassName="material-symbols-outlined text-4xl text-on-surface-variant/50"
      />

      {/* Body */}
      <div className="p-5 flex-1 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3
              className="font-headline font-bold text-on-surface truncate"
              title={packName}
            >
              {packName}
            </h3>
            <p className="text-xs text-on-surface-variant font-mono mt-0.5">
              {rows.length} dataset{rows.length === 1 ? "" : "s"}
              {packVersion ? ` · v${packVersion}` : ""}
            </p>
          </div>
          {allInstalled ? (
            <span
              className="material-symbols-outlined text-base text-secondary"
              title="All datasets installed"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              check_circle
            </span>
          ) : someInstalled ? (
            <span
              className="material-symbols-outlined text-base text-tertiary"
              title="Some datasets installed"
            >
              indeterminate_check_box
            </span>
          ) : null}
        </div>

        {description && (
          <p
            className="text-xs text-on-surface-variant line-clamp-2 leading-relaxed"
            title={description}
          >
            {description}
          </p>
        )}

        {/* Module chips — strip "agentix" via filterAgentix (every pack supports agentix; it's noise) */}
        {(() => {
          const visible = filterAgentix(supportedModules);
          if (visible.length === 0) return null;
          return (
            <div className="flex flex-wrap gap-1.5">
              {visible.slice(0, 4).map((m) => (
                <span
                  key={m}
                  className="text-[10px] font-mono px-2 py-0.5 rounded text-primary border border-primary/25 bg-primary/5"
                >
                  {m}
                </span>
              ))}
            </div>
          );
        })()}

        {/* Toggle */}
        <button
          type="button"
          onClick={onToggle}
          className="mt-auto flex items-center justify-center gap-1.5 text-xs font-mono uppercase tracking-wider text-on-surface-variant hover:text-on-surface transition-colors pt-3 border-t border-outline-variant/10"
        >
          <span className="material-symbols-outlined text-base">
            {expanded ? "expand_less" : "expand_more"}
          </span>
          {expanded ? "Hide datasets" : "Show datasets"}
        </button>

        {/* Dataset list */}
        {expanded && (
          <div className="space-y-1.5 pt-2">
            {rows.map((row) => {
              const rowId = `${row.pack_name}/${row.rule_name}/${row.dataset_name}`;
              const isInstalling = installingRowId === rowId;
              return (
                <div
                  key={rowId}
                  className="flex items-center justify-between gap-2 bg-surface-container-low/40 rounded-md p-2 group/row"
                >
                  <div
                    className="min-w-0 flex-1 cursor-pointer"
                    onClick={() => onOpenDetail(row)}
                  >
                    <p
                      className="font-mono text-[11px] text-on-surface truncate group-hover/row:text-primary transition-colors"
                      title={row.dataset_name}
                    >
                      {row.dataset_name}
                    </p>
                    <p className="text-[10px] text-on-surface-variant mt-0.5">
                      {row.rule_name} ·{" "}
                      {row.is_rawlog_only
                        ? "rawlog-only"
                        : `${row.non_meta_field_count} fields`}
                    </p>
                  </div>
                  {row.installed ? (
                    <span className="text-[10px] uppercase tracking-wider text-secondary font-medium px-2 py-1 font-mono">
                      Installed
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onInstall(row)}
                      disabled={isInstalling}
                      className="text-[11px] px-2.5 py-1 rounded bg-primary text-on-primary font-medium hover:bg-primary-dim disabled:opacity-50 flex items-center gap-1 transition-colors"
                    >
                      {isInstalling ? (
                        <>
                          <span className="material-symbols-outlined text-sm animate-spin">
                            progress_activity
                          </span>
                          Installing
                        </>
                      ) : (
                        <>
                          <span className="material-symbols-outlined text-sm">
                            download
                          </span>
                          Install
                        </>
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Installed card ──────────────────────────────────────────────────

function InstalledCard({
  row,
  onOpenDetail,
  onUninstall,
  onEdit,
  theme,
}: {
  row: DataSource;
  onOpenDetail: () => void;
  onUninstall: () => void;
  // Opens edit dialog; rendered as a small icon button next
  // to Uninstall when row.origin === "user".
  onEdit: (id: string) => void;
  theme: Theme;
}) {
  // InstalledCard prefers the vendor-level logo (same logo
  // every pack from the same vendor) over the per-pack logo (which
  // varies per pack and can be a white-on-white SVG for
  // some packs). Fall back to per-pack logo if no vendor logo
  // available (defensive — backend always populates vendor_logo_url).
  const themedLogo = withLightVariant(row.vendor_logo_url ?? row.logo_url);
  const isStructured = !row.is_rawlog_only;
  return (
    <div
      className="glass-panel rounded-xl ghost-border overflow-hidden flex flex-col cursor-pointer hover:border-primary/30 transition-colors group"
      onClick={onOpenDetail}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onOpenDetail();
      }}
    >
      {/* Constant near-white panel (theme-independent), via
          LogoOrFallback so 404s show the inventory_2 icon. */}
      <LogoOrFallback
        logoUrl={themedLogo}
        alt={`${row.pack_name} logo`}
        panelClassName="h-24 flex items-center justify-center px-5 py-3 border-b border-outline-variant/15"
        imgClassName="max-h-full max-w-[160px] object-contain"
        iconClassName="material-symbols-outlined text-4xl text-on-surface-variant/50"
      />
      <div className="p-5 flex-1 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="font-headline font-bold text-on-surface truncate">
              {row.pack_name}
            </h3>
            <p className="text-xs text-on-surface-variant font-mono mt-0.5 truncate">
              {row.rule_name} / {row.dataset_name}
            </p>
          </div>
          {row.is_pinned && (
            <span
              className="material-symbols-outlined text-base text-primary flex-shrink-0"
              title={`Pinned to ${row.pinned_version ?? "?"}`}
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              push_pin
            </span>
          )}
        </div>
        {row.pack_description && (
          <p className="text-xs text-on-surface-variant line-clamp-2 leading-relaxed">
            {row.pack_description}
          </p>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
              isStructured
                ? "text-secondary border-secondary/25 bg-secondary/5"
                : "text-tertiary border-tertiary/30 bg-tertiary/5"
            }`}
          >
            {isStructured
              ? `${row.non_meta_field_count} vendor fields`
              : "Raw-log only"}
          </span>
          {row.pack_version && (
            <span className="text-[10px] font-mono px-2 py-0.5 rounded text-on-surface-variant border border-outline-variant/25 bg-surface-container-low/50">
              v{row.pack_version}
            </span>
          )}
          <HttpDeliveryPill delivery={row.delivery} />
        </div>
        <div className="mt-auto pt-3 border-t border-outline-variant/10 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-mono uppercase text-on-surface-variant">
              {row.installed_by ?? "—"}
            </span>
            {row.origin === "user" && (
              <span
                className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary border border-tertiary/25"
                title="Uploaded by the operator (editable)"
              >
                user
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {/* Edit affordance for installed user uploads.
                Same edit-pencil convention as the PackRow Edit
                button, but a compact icon-only form since the
                InstalledCard footer is tight on horizontal real
                estate. */}
            {row.origin === "user" && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(row.id);
                }}
                aria-label="Edit data source"
                title="Edit this user-uploaded data source"
                className="text-on-surface-variant hover:text-primary transition-colors p-1 rounded hover:bg-primary/10"
              >
                <span className="material-symbols-outlined text-base">edit</span>
              </button>
            )}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onUninstall();
              }}
              aria-label="Uninstall"
              className="text-on-surface-variant hover:text-error transition-colors p-1 rounded hover:bg-error/10"
            >
              <span className="material-symbols-outlined text-base">delete</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Skeleton loading grid ───────────────────────────────────────────

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <SkeletonCard key={i} delaySec={i * 0.1} />
      ))}
    </div>
  );
}

function SkeletonCard({ delaySec = 0 }: { delaySec?: number }) {
  return (
    <div className="glass-panel rounded-xl ghost-border p-5 flex flex-col gap-4 relative overflow-hidden">
      <div
        className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/30 to-transparent"
        style={{ animation: `shimmer 2s ${delaySec}s infinite linear` }}
      />
      <div className="flex justify-between items-start">
        <div
          className="w-12 h-12 rounded-lg skeleton-shimmer ghost-border"
          style={{ animationDelay: `${delaySec}s` }}
        />
        <div
          className="w-8 h-8 rounded-full skeleton-shimmer"
          style={{ animationDelay: `${delaySec}s` }}
        />
      </div>
      <div className="space-y-2.5">
        <div
          className="h-5 w-3/4 rounded-md skeleton-shimmer"
          style={{ animationDelay: `${delaySec}s` }}
        />
        <div
          className="h-3 w-1/2 rounded-md skeleton-shimmer opacity-70"
          style={{ animationDelay: `${delaySec}s` }}
        />
      </div>
      <div className="space-y-1.5">
        <div
          className="h-2.5 w-full rounded skeleton-shimmer opacity-50"
          style={{ animationDelay: `${delaySec}s` }}
        />
        <div
          className="h-2.5 w-5/6 rounded skeleton-shimmer opacity-50"
          style={{ animationDelay: `${delaySec}s` }}
        />
      </div>
      <div className="flex gap-2 mt-2 pt-3 border-t border-outline-variant/10">
        <div
          className="h-5 w-16 rounded-full skeleton-shimmer opacity-80"
          style={{ animationDelay: `${delaySec}s` }}
        />
        <div
          className="h-5 w-20 rounded-full skeleton-shimmer opacity-80"
          style={{ animationDelay: `${delaySec}s` }}
        />
      </div>
    </div>
  );
}

// ── Empty state ─────────────────────────────────────────────────────

function EmptyState({
  icon,
  headline,
  body,
  ctaLabel,
  onCta,
}: {
  icon: string;
  headline: string;
  body: string;
  ctaLabel?: string;
  onCta?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center relative">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-30">
        <div className="w-64 h-64 bg-primary/15 rounded-full blur-[100px]" />
      </div>
      <div className="relative z-10 max-w-md mx-auto flex flex-col items-center">
        <div className="w-20 h-20 mb-5 rounded-full bg-surface-container-low border border-outline-variant/15 flex items-center justify-center">
          <span className="material-symbols-outlined text-[42px] text-on-surface-variant/50">
            {icon}
          </span>
        </div>
        <h2 className="font-headline text-2xl font-bold text-on-surface mb-2 tracking-tight">
          {headline}
        </h2>
        <p className="text-sm text-on-surface-variant leading-relaxed max-w-[320px] mb-6">
          {body}
        </p>
        {ctaLabel && onCta && (
          <button
            type="button"
            onClick={onCta}
            className="glass-panel border border-outline-variant/30 hover:border-primary/40 hover:bg-primary/5 text-on-surface hover:text-primary font-headline text-sm tracking-wider uppercase px-6 py-2.5 rounded transition-all duration-200 flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-base">refresh</span>
            {ctaLabel}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Error panel (full-section) ──────────────────────────────────────

function ErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-center justify-center py-16 relative">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-[500px] h-[500px] bg-error/5 rounded-full blur-[100px]" />
      </div>
      <div className="glass-panel relative z-10 w-full max-w-2xl rounded-xl border border-error/20 p-8 flex flex-col items-center text-center">
        <div className="w-20 h-20 rounded-full bg-error/10 flex items-center justify-center mb-6 border border-error/30 relative">
          <div className="absolute inset-0 rounded-full border border-error/50 animate-ping opacity-20" />
          <span
            className="material-symbols-outlined text-[3rem] text-error"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            error
          </span>
        </div>
        <h1 className="font-headline text-2xl text-on-surface font-bold tracking-tight mb-3">
          Catalog unavailable
        </h1>
        <div className="bg-surface-container-low rounded-lg border border-outline-variant/15 p-4 mb-6 w-full">
          <p className="font-mono text-xs text-error/80 leading-relaxed text-left break-words">
            <span className="text-error font-bold">&gt; ERROR:</span> {message}
          </p>
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="group relative px-6 py-2.5 rounded bg-surface-container border border-outline-variant/30 hover:border-primary transition-colors flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-primary group-hover:rotate-180 transition-transform duration-500">
            refresh
          </span>
          <span className="font-headline font-medium text-primary uppercase tracking-widest text-sm">
            Retry
          </span>
        </button>
      </div>
    </div>
  );
}

// ── Detail drawer ───────────────────────────────────────────────────

function DetailDrawer({
  detail,
  loading,
  onClose,
  onUninstall,
  onInstall,
  onEdit,
  onEditSystem,
  onHistory,
  installing,
  theme,
}: {
  detail: DataSourceWithSchema | null;
  loading: boolean;
  onClose: () => void;
  onUninstall: (ds: DataSource) => void;
  // Install handler for the preview case (uninstalled pack)
  onInstall: (row: { pack_name: string; rule_name: string; dataset_name: string }) => void;
  // Opens edit dialog for user uploads. Surfaced in the
  // footer alongside Install/Uninstall when detail.origin === "user".
  onEdit: (id: string) => void;
  // SP-4 — opens the versioned how_to_use editor for SYSTEM
  // (bundle) sources. Distinct from onEdit (user uploads edit their own
  // YAML directly); a system edit creates an operator override version,
  // original preserved as v1. Surfaced for origin !== "user".
  onEditSystem: (detail: DataSourceWithSchema) => void;
  // SP-5 — opens the version-history panel (list/view/roll back).
  // Surfaced for system sources alongside Edit guidance.
  onHistory: (detail: DataSourceWithSchema) => void;
  installing: boolean;
  theme: Theme;
}) {
  const [fieldFilter, setFieldFilter] = useState("");

  const fields = detail
    ? [...detail.fields]
        .filter((f) => {
          if (!fieldFilter) return true;
          // Filter matches name OR description (operator can
          // search "Source IP" and find src/srcip/source_ip/etc.).
          const q = fieldFilter.toLowerCase();
          return (
            f.name.toLowerCase().includes(q) ||
            (f.description ?? "").toLowerCase().includes(q)
          );
        })
        .sort((a, b) => {
          if (a.is_meta !== b.is_meta) return a.is_meta ? -1 : 1;
          return a.name.localeCompare(b.name);
        })
    : [];
  const metaFields = fields.filter((f) => f.is_meta);
  const vendorFields = fields.filter((f) => !f.is_meta);
  // Drawer header also uses the vendor-level logo so e.g.
  // every F5 pack's drawer shows the F5 mark, not per-pack variants.
  const themedDetailLogo = detail
    ? withLightVariant(detail.vendor_logo_url ?? detail.logo_url)
    : null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="w-[55%] h-full flex flex-col glass-panel border-l border-outline-variant/15 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <header className="flex-none p-5 pb-3 border-b border-outline-variant/10">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              {/* Detail-drawer logo also goes through
                  LogoOrFallback — same panel background + 404 handling
                  semantics as Browse/Installed cards. */}
              <LogoOrFallback
                logoUrl={detail ? themedDetailLogo : null}
                alt={detail ? detail.pack_name : "Loading"}
                panelClassName="w-12 h-12 rounded-lg flex items-center justify-center ghost-border flex-shrink-0 overflow-hidden"
                imgClassName="max-h-full max-w-full object-contain p-1"
                iconClassName="material-symbols-outlined text-2xl text-on-surface-variant/60"
                lazy={false}
              />
              <div className="min-w-0">
                <h2 className="font-headline text-xl font-bold text-on-surface tracking-tight truncate">
                  {detail ? detail.pack_name : "Loading…"}
                </h2>
                {detail && (
                  <div className="text-[11px] font-mono text-on-surface-variant bg-surface-container-low/60 ghost-border py-0.5 px-1.5 rounded inline-block mt-1 truncate max-w-full">
                    {detail.rule_name} / {detail.dataset_name}
                  </div>
                )}
                {/* HTTP-delivery marker (http-sender connector, not syslog/CEF). */}
                <HttpDeliveryPill delivery={detail?.delivery} className="ml-2 align-middle" />
                {/* Same two-tier validation pill as the
                    Browse card so the mark is consistent across surfaces. */}
                {detail?.validated ? (
                  <span
                    className="ml-2 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-secondary/15 text-secondary border border-secondary/30 align-middle"
                    title="Mapping-validated: tested live on XSIAM — the modeling rule populates xdm.* (or the parsing rule extracts columns). Proven to map."
                  >
                    Mapping Validated
                  </span>
                ) : detail?.raw_validated ? (
                  <span
                    className="ml-2 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary border border-tertiary/30 align-middle"
                    title="Raw-validated: the vendor pack isn't installed, but a raw-dataset query confirmed our synthetic data lands the exact field names the rule would read. Proven shape, ready-to-map on install."
                  >
                    Raw Validated
                  </span>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="text-on-surface-variant hover:text-on-surface p-1 rounded hover:bg-surface-container transition-colors flex-shrink-0"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </header>

        {/* Body */}
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-on-surface-variant">
            <span className="material-symbols-outlined animate-spin text-2xl mr-2">
              progress_activity
            </span>
            Loading schema…
          </div>
        ) : !detail ? (
          <div className="flex-1 flex items-center justify-center text-on-surface-variant">
            No detail loaded.
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto custom-scrollbar px-5 py-5 space-y-6">
            {/* Stat tiles */}
            <section className="grid grid-cols-4 gap-2">
              <StatTile label="Total Fields" value={String(detail.field_count)} />
              <StatTile
                label="Vendor Fields"
                value={String(detail.non_meta_field_count)}
              />
              <StatTile
                label="Style"
                value={detail.is_rawlog_only ? "Raw-log" : "Structured"}
                tone={detail.is_rawlog_only ? "tertiary" : undefined}
              />
              <StatTile
                label="Version"
                value={detail.pack_version ? `v${detail.pack_version}` : "—"}
                tone="secondary"
                pinned={detail.is_pinned}
              />
            </section>

            {/* Description */}
            {detail.pack_description && (
              <p className="text-sm text-on-surface-variant leading-relaxed">
                {detail.pack_description}
              </p>
            )}

            {/* Operator-facing simulation guidance from the
                YAML's `how_to_use:` field. Markdown body covering the
                vendor's MR pattern (flat-field vs nested-JSON), CEF-wrap
                wire format, multi-dataset handling, MR-filter quirks
                (timestamp shape, discriminator field), sentinel values,
                and the single-event XDM ceiling. Hidden when the field
                is empty (currently only the validated-vendor subset
                ships with content; the rest serve no how_to_use). */}
            {detail.how_to_use && detail.how_to_use.trim() && (
              <details
                className="bg-surface-container/40 rounded-lg ghost-border overflow-hidden group"
                open
              >
                <summary className="cursor-pointer select-none flex items-center gap-2 px-3 py-2 border-b border-outline-variant/15 text-sm font-headline text-on-surface hover:bg-surface-container/80 transition-colors">
                  <span className="material-symbols-outlined text-base text-primary">
                    play_circle
                  </span>
                  How to simulate this data source
                  <span className="material-symbols-outlined text-sm text-on-surface-variant ml-auto group-open:rotate-180 transition-transform">
                    expand_more
                  </span>
                </summary>
                <div className="px-4 py-3 text-sm leading-relaxed text-on-surface-variant max-h-[400px] overflow-y-auto">
                  <MarkdownContent>{detail.how_to_use}</MarkdownContent>
                </div>
              </details>
            )}

            {/* Use-case tag pills sourced from the operator-curated
                `use_cases:` field (the supported_modules row is hidden: the
                "xsiam" pill that renders for every YAML-loader row carries
                no operator-visible meaning). */}
            {detail.use_cases && detail.use_cases.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-on-surface-variant mr-1">
                  Use case:
                </span>
                {detail.use_cases.map((uc) => (
                  <span
                    key={uc}
                    className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-primary/15 text-on-surface border border-primary/30"
                  >
                    {uc}
                  </span>
                ))}
              </div>
            )}

            {/* Schema fields */}
            <section className="space-y-3">
              <h3 className="font-headline text-base text-on-surface border-b border-outline-variant/15 pb-2">
                Schema Fields
              </h3>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-base">
                  search
                </span>
                <input
                  type="text"
                  placeholder="Filter by name or description…"
                  value={fieldFilter}
                  onChange={(e) => setFieldFilter(e.target.value)}
                  className="w-full bg-surface-container-lowest text-on-surface text-sm rounded-lg py-2 pl-10 pr-3 ghost-border focus:outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant/50"
                />
              </div>

              {/* Table header — 12 cols split 3/2/4/3 (Name /
                  Type / Description / Example). Header text stays
                  theme-aware via `text-on-surface`. */}
              <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-surface-container/60 rounded-t-lg border-b border-outline-variant/30 text-[10px] font-mono uppercase tracking-widest text-on-surface">
                <div className="col-span-3">Name</div>
                <div className="col-span-2 text-center">Type</div>
                <div className="col-span-4">Description</div>
                <div className="col-span-3">Example</div>
              </div>

              {/* Meta group */}
              {metaFields.length > 0 && (
                <div className="bg-surface-container-low/50 rounded-lg p-2 ghost-border space-y-0.5">
                  <div className="text-[10px] uppercase tracking-widest text-on-surface-variant/60 px-2 pb-1 border-b border-outline-variant/10 mb-1">
                    Meta Data
                  </div>
                  {metaFields.map((f) => (
                    <FieldRow key={f.name} field={f} tag="meta" />
                  ))}
                </div>
              )}

              {/* Vendor group */}
              {vendorFields.length > 0 && (
                <div className="bg-surface-container-highest/60 rounded-lg p-2 ghost-border space-y-0.5">
                  <div className="text-[10px] uppercase tracking-widest text-primary/60 px-2 pb-1 border-b border-outline-variant/10 mb-1">
                    Vendor Specific
                  </div>
                  {vendorFields.map((f) => (
                    <FieldRow key={f.name} field={f} tag="vendor" />
                  ))}
                </div>
              )}

              {fields.length === 0 && (
                <p className="text-xs text-on-surface-variant italic text-center py-4">
                  No fields match the filter.
                </p>
              )}
            </section>

            {/* No XDM Path Mappings section: data
                sources are vendor-neutral specs; XDM is Cortex-specific
                and lives downstream of the wire format. */}
            <div className="h-6" />
          </div>
        )}

        {/* Footer — Install CTA in preview mode (uninstalled), Uninstall otherwise.
            Edit CTA sits alongside when origin === "user". */}
        {detail && !loading && (
          <footer className="flex-none p-4 bg-surface-container-highest/70 backdrop-blur-md border-t border-outline-variant/10 flex items-center justify-between gap-3">
            {detail.is_preview ? (
              <>
                <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-tertiary/10 text-tertiary border border-tertiary/15">
                  Preview · not installed
                </span>
                <div className="flex items-center gap-2">
                  {detail.origin === "user" && detail.id && (
                    <button
                      type="button"
                      onClick={() => onEdit(detail.id!)}
                      className="flex items-center gap-2 px-4 py-2 bg-tertiary/15 text-tertiary hover:bg-tertiary/25 border border-tertiary/30 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">edit</span>
                      Edit
                    </button>
                  )}
                  {/* SP-4 — versioned how_to_use editor for system
                      (bundle) sources. Creates an operator override; the
                      original is preserved as version 1. */}
                  {detail.origin !== "user" && (
                    <button
                      type="button"
                      onClick={() => onHistory(detail)}
                      className="flex items-center gap-2 px-4 py-2 bg-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container border border-outline-variant/40 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">history</span>
                      History
                    </button>
                  )}
                  {detail.origin !== "user" && (
                    <button
                      type="button"
                      onClick={() => onEditSystem(detail)}
                      className="flex items-center gap-2 px-4 py-2 bg-secondary/15 text-secondary hover:bg-secondary/25 border border-secondary/30 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">edit_note</span>
                      Edit guidance
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onInstall(detail)}
                    disabled={installing}
                    /* Pill-shaped filled button, same shape as
                       the PackRow Install button. Solid `bg-primary
                       text-on-primary` for WCAG AAA contrast in both
                       themes. */
                    className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary hover:bg-primary-dim rounded-full transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                  >
                    <span className="material-symbols-outlined text-sm">{installing ? "hourglass_top" : "download"}</span>
                    {installing ? "Installing…" : "Install data source"}
                  </button>
                </div>
              </>
            ) : (
              <>
                {detail.origin === "user" && detail.id ? (
                  <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-tertiary/15 text-tertiary border border-tertiary/25">
                    User upload
                  </span>
                ) : (
                  <span />
                )}
                <div className="flex items-center gap-2">
                  {detail.origin === "user" && detail.id && (
                    <button
                      type="button"
                      onClick={() => onEdit(detail.id!)}
                      className="flex items-center gap-2 px-4 py-2 bg-tertiary/15 text-tertiary hover:bg-tertiary/25 border border-tertiary/30 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">edit</span>
                      Edit
                    </button>
                  )}
                  {/* SP-4 — versioned how_to_use editor for system
                      (bundle) sources. Creates an operator override; the
                      original is preserved as version 1. No delete. */}
                  {detail.origin !== "user" && (
                    <button
                      type="button"
                      onClick={() => onHistory(detail)}
                      className="flex items-center gap-2 px-4 py-2 bg-transparent text-on-surface-variant hover:text-on-surface hover:bg-surface-container border border-outline-variant/40 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">history</span>
                      History
                    </button>
                  )}
                  {detail.origin !== "user" && (
                    <button
                      type="button"
                      onClick={() => onEditSystem(detail)}
                      className="flex items-center gap-2 px-4 py-2 bg-secondary/15 text-secondary hover:bg-secondary/25 border border-secondary/30 rounded-full transition-colors text-sm font-medium"
                    >
                      <span className="material-symbols-outlined text-sm">edit_note</span>
                      Edit guidance
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onUninstall(detail)}
                    /* Matching pill-shape for the destructive
                       action, but stays low-opacity to keep visual weight
                       asymmetric (uninstall should look less like the
                       primary action). */
                    className="flex items-center gap-2 px-4 py-2 bg-error/15 text-error hover:bg-error/25 border border-error/30 rounded-full transition-colors text-sm font-medium"
                  >
                    <span className="material-symbols-outlined text-sm">delete</span>
                    Uninstall
                  </button>
                </div>
              </>
            )}
          </footer>
        )}
      </aside>
    </div>
  );
}

function StatTile({
  label,
  value,
  tone,
  pinned,
}: {
  label: string;
  value: string;
  tone?: "secondary" | "tertiary";
  pinned?: boolean;
}) {
  // Default tone uses `text-on-surface` rather than
  // `text-primary` (which is blue-on-blue in dark theme, making the count
  // numbers essentially invisible). The
  // secondary/tertiary tones are deliberate accent colors and stay.
  const toneClass =
    tone === "secondary"
      ? "text-secondary"
      : tone === "tertiary"
        ? "text-tertiary"
        : "text-on-surface";
  return (
    <div className="bg-surface-container-low/60 rounded-lg p-2.5 ghost-border flex flex-col items-center text-center relative">
      <span
        className={`font-mono ${value.length > 6 ? "text-sm" : "text-lg"} ${toneClass} mb-0.5 truncate w-full`}
        title={value}
      >
        {value}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </span>
      {pinned && (
        <div
          className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-primary ring-2 ring-surface-container"
          title="Pinned"
        />
      )}
    </div>
  );
}

function FieldRow({
  field,
  tag,
}: {
  field: DataSourceField;
  tag: "meta" | "vendor";
}) {
  const typeColor =
    field.type === "datetime"
      ? "text-secondary"
      : field.type === "json"
        ? "text-primary-dim"
        : "text-tertiary";
  const description = (field.description ?? "").trim();
  const example = (field.example ?? "").trim();
  return (
    <div className="grid grid-cols-12 gap-2 items-center px-2 py-1 hover:bg-surface-container/40 rounded transition-colors">
      <div
        className={`col-span-3 font-mono text-[11px] truncate ${tag === "vendor" ? "text-on-surface" : "text-on-surface-variant"}`}
        title={field.name}
      >
        {field.name}
        {field.is_array && (
          <span className="text-on-surface-variant ml-0.5">[]</span>
        )}
      </div>
      <div className={`col-span-2 text-center font-mono text-[10px] ${typeColor}`}>
        {field.type ?? "—"}
      </div>
      <div
        className="col-span-4 text-[11px] text-on-surface-variant truncate"
        title={description || undefined}
      >
        {description ? (
          <span className="text-on-surface/80">{description}</span>
        ) : (
          <span className="text-on-surface-variant/40 italic">—</span>
        )}
      </div>
      {/* Example column. Monospace token; truncate with
          hover tooltip showing the full value (JSON composites in
          particular can be long). Empty shows em-dash. */}
      <div
        className="col-span-3 font-mono text-[11px] text-tertiary/80 truncate"
        title={example || undefined}
      >
        {example ? (
          example
        ) : (
          <span className="text-on-surface-variant/40 italic">—</span>
        )}
      </div>
    </div>
  );
}

// ── SP-4 — versioned how_to_use editor ───────────────────────
//
// Edits a data source's `how_to_use` simulation guidance. Each save is a
// version-store snapshot served as an overlay; the file on disk is never
// touched and the original is preserved as version 1. For SYSTEM (bundle)
// sources a warning explains the override semantics. There is NO delete.
//
// Scope note: schema-FIELD editing is intentionally not in this modal yet.
// The /schema endpoint renders a lossy field shape (it omits enum_values /
// regex_pattern / observable_override), so a UI fields editor built on it
// would fail schema validation for enum/regex fields. Field editing is
// available today via the API/agent path (data_sources_edit) and via the
// Export-YAML → re-upload flow; a full-fidelity UI fields editor is a
// tracked follow-up once the schema endpoint round-trips those keys.

function EditDataSourceModal({
  source,
  onClose,
  onSaved,
}: {
  source: DataSourceWithSchema;
  onClose: () => void;
  onSaved: (newVersion: number) => void | Promise<void>;
}) {
  const [howToUse, setHowToUse] = useState(source.how_to_use ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSystem = source.origin !== "user";
  const original = source.how_to_use ?? "";
  const dirty = howToUse !== original;

  async function handleSave() {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      const path = [
        encodeURIComponent(source.pack_name),
        encodeURIComponent(source.rule_name),
        encodeURIComponent(source.dataset_name),
        "edit",
      ].join("/");
      const resp = await fetch(`/api/agent/data-sources/${path}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          how_to_use: howToUse,
          note: note.trim() || undefined,
        }),
      });
      const body = (await resp.json().catch(() => null)) as {
        ok?: boolean;
        version?: number;
        error?: string;
      } | null;
      if (!resp.ok || !body?.ok) {
        throw new Error(body?.error ?? `HTTP ${resp.status}`);
      }
      await onSaved(body.version ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-surface-container-lowest/80 backdrop-blur-sm"
        onClick={saving ? undefined : onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-2xl">
        <div className="glass-panel atmospheric-shadow border border-outline-variant/15 rounded-xl overflow-hidden flex flex-col max-h-[85vh]">
          {/* Header */}
          <div className="bg-surface-container-high/50 p-5 flex items-start gap-3 border-b border-outline-variant/10">
            <span className="material-symbols-outlined text-secondary text-2xl flex-shrink-0 mt-0.5">
              edit_note
            </span>
            <div className="min-w-0">
              <h2 className="font-headline text-lg font-bold text-on-surface tracking-tight">
                Edit guidance —{" "}
                <span className="text-secondary">{source.pack_name}</span>
              </h2>
              <div className="text-[11px] font-mono text-on-surface-variant mt-0.5 truncate">
                {source.rule_name} / {source.dataset_name}
              </div>
            </div>
          </div>

          {/* Body */}
          <div className="p-5 bg-surface-container-low/40 overflow-y-auto custom-scrollbar space-y-4">
            {/* System-source override warning */}
            {isSystem && (
              <div className="flex items-start gap-2.5 p-3 rounded-lg bg-tertiary/10 border border-tertiary/25 text-sm text-on-surface-variant leading-relaxed">
                <span
                  className="material-symbols-outlined text-tertiary text-lg flex-shrink-0 mt-0.5"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  info
                </span>
                <span>
                  This is a <strong className="text-on-surface">system data source</strong>.
                  Saving creates an operator override — the original is preserved
                  as <strong className="text-on-surface">version 1</strong> and you
                  can roll back to it later. The shipped file on disk is never
                  modified.
                </span>
              </div>
            )}

            {/* how_to_use editor */}
            <div className="space-y-1.5">
              <label
                htmlFor="edit-how-to-use"
                className="block text-xs font-mono uppercase tracking-wider text-on-surface-variant"
              >
                How to simulate this data source
              </label>
              <textarea
                id="edit-how-to-use"
                value={howToUse}
                onChange={(e) => setHowToUse(e.target.value)}
                rows={14}
                placeholder="Markdown guidance: wire format, MR-firing quirks, multi-dataset handling, filter requirements…"
                className="w-full bg-surface-container-lowest text-on-surface text-sm font-mono leading-relaxed rounded-lg py-3 px-3.5 ghost-border focus:outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant/40 resize-y"
              />
              <p className="text-[11px] text-on-surface-variant/70">
                Markdown is supported. This text renders in the drawer&apos;s
                &ldquo;How to simulate&rdquo; section and guides the agent when it
                streams this vendor&apos;s logs.
              </p>
            </div>

            {/* Optional changelog note */}
            <div className="space-y-1.5">
              <label
                htmlFor="edit-note"
                className="block text-xs font-mono uppercase tracking-wider text-on-surface-variant"
              >
                Change note <span className="opacity-50">(optional)</span>
              </label>
              <input
                id="edit-note"
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. clarified broker setup"
                className="w-full bg-surface-container-lowest text-on-surface text-sm rounded-lg py-2 px-3 ghost-border focus:outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant/40"
              />
            </div>

            {/* Schema-field editing scope note */}
            <p className="text-[11px] text-on-surface-variant/60 border-t border-outline-variant/10 pt-3">
              Editing the <strong>{source.field_count}-field schema</strong> from
              the UI is coming soon. For schema changes today, use Export → edit
              the YAML → re-upload.
            </p>

            {error && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-error/10 border border-error/25 text-sm text-error">
                <span className="material-symbols-outlined text-base flex-shrink-0 mt-0.5">
                  error
                </span>
                <span className="break-words">{error}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-4 bg-surface-container-high/30 flex items-center justify-end gap-3 border-t border-outline-variant/10">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-4 py-2 text-sm font-semibold text-on-surface bg-transparent border border-outline-variant/40 rounded hover:bg-surface-variant hover:border-outline-variant transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !dirty}
              className="px-5 py-2 text-sm font-bold text-on-secondary bg-secondary rounded hover:bg-secondary/80 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              <span className="material-symbols-outlined text-sm">
                {saving ? "hourglass_top" : "save"}
              </span>
              {saving ? "Saving…" : "Save new version"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── SP-5 — version history + rollback panel ──────────────────
//
// Lists a data source's version history (newest first), lets the operator
// view any version's snapshot read-only, and roll back to a prior version.
// Rollback is non-destructive: the target is copied forward as a new current
// version (the server handles this); history is preserved. There is no
// delete. Version 1 (author "bundle-baseline") is the pristine original on
// any edited system source.

interface VersionMeta {
  version: number;
  author: string;
  note: string | null;
  created_at: string;
  is_current: boolean;
}

function VersionHistoryModal({
  source,
  onClose,
  onChanged,
}: {
  source: DataSourceWithSchema;
  onClose: () => void;
  onChanged: (newVersion: number) => void | Promise<void>;
}) {
  const [versions, setVersions] = useState<VersionMeta[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [viewContent, setViewContent] = useState<string>("");
  const [rollingBack, setRollingBack] = useState<number | null>(null);

  const basePath = [
    encodeURIComponent(source.pack_name),
    encodeURIComponent(source.rule_name),
    encodeURIComponent(source.dataset_name),
  ].join("/");

  const loadVersions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/api/agent/data-sources/${basePath}/versions`, {
        cache: "no-store",
      });
      const body = (await resp.json().catch(() => null)) as {
        ok?: boolean;
        versions?: VersionMeta[];
        error?: string;
      } | null;
      if (!resp.ok || !body?.ok) throw new Error(body?.error ?? `HTTP ${resp.status}`);
      // newest first for display
      setVersions([...(body.versions ?? [])].sort((a, b) => b.version - a.version));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [basePath]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  async function handleView(version: number) {
    if (viewing === version) {
      setViewing(null);
      return;
    }
    setViewing(version);
    setViewContent("Loading…");
    try {
      const resp = await fetch(`/api/agent/data-sources/${basePath}/versions/${version}`, {
        cache: "no-store",
      });
      const body = (await resp.json().catch(() => null)) as {
        ok?: boolean;
        version?: { yaml_snapshot?: string };
        error?: string;
      } | null;
      if (!resp.ok || !body?.ok) throw new Error(body?.error ?? `HTTP ${resp.status}`);
      setViewContent(body.version?.yaml_snapshot ?? "(empty)");
    } catch (e) {
      setViewContent(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleRollback(version: number) {
    setRollingBack(version);
    setError(null);
    try {
      const resp = await fetch(`/api/agent/data-sources/${basePath}/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version }),
      });
      const body = (await resp.json().catch(() => null)) as {
        ok?: boolean;
        version?: number;
        error?: string;
      } | null;
      if (!resp.ok || !body?.ok) throw new Error(body?.error ?? `HTTP ${resp.status}`);
      await onChanged(body.version ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRollingBack(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-surface-container-lowest/80 backdrop-blur-sm"
        onClick={rollingBack !== null ? undefined : onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-2xl">
        <div className="glass-panel atmospheric-shadow border border-outline-variant/15 rounded-xl overflow-hidden flex flex-col max-h-[85vh]">
          {/* Header */}
          <div className="bg-surface-container-high/50 p-5 flex items-start gap-3 border-b border-outline-variant/10">
            <span className="material-symbols-outlined text-on-surface-variant text-2xl flex-shrink-0 mt-0.5">
              history
            </span>
            <div className="min-w-0">
              <h2 className="font-headline text-lg font-bold text-on-surface tracking-tight">
                Version history —{" "}
                <span className="text-secondary">{source.pack_name}</span>
              </h2>
              <div className="text-[11px] font-mono text-on-surface-variant mt-0.5 truncate">
                {source.rule_name} / {source.dataset_name}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="ml-auto text-on-surface-variant hover:text-on-surface p-1 rounded hover:bg-surface-container transition-colors flex-shrink-0"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          {/* Body */}
          <div className="p-5 bg-surface-container-low/40 overflow-y-auto custom-scrollbar space-y-3">
            {loading ? (
              <div className="flex items-center justify-center py-8 text-on-surface-variant">
                <span className="material-symbols-outlined animate-spin text-xl mr-2">
                  progress_activity
                </span>
                Loading history…
              </div>
            ) : error && !versions ? (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-error/10 border border-error/25 text-sm text-error">
                <span className="material-symbols-outlined text-base flex-shrink-0 mt-0.5">error</span>
                <span className="break-words">{error}</span>
              </div>
            ) : !versions || versions.length === 0 ? (
              <p className="text-sm text-on-surface-variant italic text-center py-8">
                No versions yet — this data source hasn&apos;t been edited. Use{" "}
                <strong className="not-italic text-on-surface">Edit guidance</strong> to
                make a change; the original is preserved as version 1.
              </p>
            ) : (
              <>
                {error && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-error/10 border border-error/25 text-sm text-error">
                    <span className="material-symbols-outlined text-base flex-shrink-0 mt-0.5">error</span>
                    <span className="break-words">{error}</span>
                  </div>
                )}
                <ul className="space-y-2">
                  {versions.map((v) => (
                    <li
                      key={v.version}
                      className="rounded-lg ghost-border bg-surface-container/40 overflow-hidden"
                    >
                      <div className="flex items-center gap-3 px-3 py-2.5">
                        <div className="flex flex-col min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm text-on-surface">v{v.version}</span>
                            {v.is_current && (
                              <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary/15 text-primary border border-primary/30">
                                Current
                              </span>
                            )}
                            <span className="text-[11px] font-mono text-on-surface-variant">
                              {v.author}
                            </span>
                          </div>
                          {v.note && (
                            <span className="text-xs text-on-surface-variant truncate mt-0.5">
                              {v.note}
                            </span>
                          )}
                          <span className="text-[10px] text-on-surface-variant/60 mt-0.5">
                            {v.created_at}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleView(v.version)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-on-surface-variant hover:text-on-surface bg-transparent border border-outline-variant/40 rounded-full hover:bg-surface-container transition-colors flex-shrink-0"
                        >
                          <span className="material-symbols-outlined text-sm">
                            {viewing === v.version ? "visibility_off" : "visibility"}
                          </span>
                          {viewing === v.version ? "Hide" : "View"}
                        </button>
                        {/* SP-6 — export this specific version's YAML. */}
                        <a
                          href={`/api/agent/data-sources/${basePath}/export?version=${v.version}`}
                          download
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-on-surface-variant hover:text-on-surface bg-transparent border border-outline-variant/40 rounded-full hover:bg-surface-container transition-colors flex-shrink-0"
                        >
                          <span className="material-symbols-outlined text-sm">download</span>
                          Export
                        </a>
                        {!v.is_current && (
                          <button
                            type="button"
                            onClick={() => void handleRollback(v.version)}
                            disabled={rollingBack !== null}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-secondary hover:bg-secondary/25 bg-secondary/15 border border-secondary/30 rounded-full transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <span className="material-symbols-outlined text-sm">
                              {rollingBack === v.version ? "hourglass_top" : "restore"}
                            </span>
                            {rollingBack === v.version ? "Rolling back…" : "Roll back"}
                          </button>
                        )}
                      </div>
                      {viewing === v.version && (
                        <pre className="text-[11px] font-mono leading-relaxed text-on-surface-variant bg-surface-container-lowest/70 border-t border-outline-variant/15 px-3 py-2.5 max-h-64 overflow-auto whitespace-pre-wrap break-words">
                          {viewContent}
                        </pre>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="text-[11px] text-on-surface-variant/60 border-t border-outline-variant/10 pt-3">
                  Rollback is non-destructive — it copies the chosen version forward as a
                  new current version. Earlier and later versions stay in history, so you
                  can always roll forward again.
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Uninstall confirm modal ─────────────────────────────────────────

function UninstallModal({
  row,
  uninstalling,
  onCancel,
  onConfirm,
}: {
  row: DataSource;
  uninstalling: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-surface-container-lowest/80 backdrop-blur-sm"
        onClick={uninstalling ? undefined : onCancel}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-lg">
        <div className="glass-panel atmospheric-shadow border border-outline-variant/15 rounded-xl overflow-hidden flex flex-col">
          {/* Header */}
          <div className="bg-surface-container-high/50 p-5 flex items-start gap-3 border-b border-outline-variant/10">
            <span
              className="material-symbols-outlined text-error text-2xl flex-shrink-0 mt-0.5"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              warning
            </span>
            <h2 className="font-headline text-lg font-bold text-on-surface tracking-tight">
              Uninstall{" "}
              <span className="text-error">{row.pack_name}</span>/
              <span className="text-error">{row.rule_name}</span>/
              <span className="text-error">{row.dataset_name}</span>?
            </h2>
          </div>

          {/* Body */}
          <div className="p-5 text-on-surface-variant bg-surface-container-low/40">
            <ul className="space-y-2.5 list-disc list-outside ml-5 text-sm leading-relaxed">
              <li>
                This removes the{" "}
                <span className="font-mono text-xs bg-surface-container/60 px-1.5 py-0.5 rounded text-on-surface">
                  {row.field_count}-field schema
                </span>{" "}
                from Phantom.
              </li>
              <li>
                Future log simulations for this vendor fall back to a generic
                schema until a Data Source is installed again.
              </li>
              <li>
                Settings, secrets, and other connector data are unaffected. Only
                this Data Source is removed.
              </li>
            </ul>
          </div>

          {/* Footer */}
          <div className="p-4 bg-surface-container-high/30 flex items-center justify-end gap-3 border-t border-outline-variant/10">
            <button
              type="button"
              onClick={onCancel}
              disabled={uninstalling}
              className="px-4 py-2 text-sm font-semibold text-on-surface bg-transparent border border-outline-variant/40 rounded hover:bg-surface-variant hover:border-outline-variant transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={uninstalling}
              className="px-5 py-2 text-sm font-bold text-on-error bg-error rounded hover:bg-error-dim transition-colors flex items-center gap-2 disabled:opacity-50 shadow-[0_0_15px_rgba(255,113,108,0.25)]"
            >
              {uninstalling ? (
                <>
                  <span className="material-symbols-outlined text-base animate-spin">
                    progress_activity
                  </span>
                  Uninstalling…
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-base">
                    delete_forever
                  </span>
                  Uninstall
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
