"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { notify, useNotificationsStore } from "@/lib/stores/notifications";
import {
  instanceStatusFromState,
  saveOutcome,
  testOutcome,
  toolNote,
  type InstanceStatus,
  type TestOutcome,
} from "@/lib/instance-status";
import {
  buildCreatePayload,
  buildEditPayload,
  invalidNumbers,
  isUndeclaredSecret,
  missingRequired,
  seedEditValues,
} from "@/lib/connector-form";
import { ConfigFormFields, type ConfigParam } from "@/components/connector-config-form";
import { confirmAction } from "@/lib/stores/confirm";
import Link from "next/link";
import {
  listMarketplaceConnectors,
  installConnector,
  uninstallConnector,
  deleteUploadedConnector,
  listInstalledConnectors,
  listInstances,
  createInstance,
  deleteInstance,
  updateInstance,
  assignWorkspace,
  testInstance,
  type MarketplaceConnector,
  type ConnectorInstance,
} from "@/lib/api/marketplace";

// ─── Types ───────────────────────────────────────────────────────────────────

type InstallStatus = "installed" | "update_available" | "not_installed";
type Category = "All" | "Communication" | "DevTools" | "Services" | "Search" | "Devices" | "Productivity" | "Finance" | "Analytics" | "Storage";
type SortOption = "popularity" | "recent" | "alphabetical";
type TabId = "marketplace" | "instances" | "workspace";

interface ToolArg {
  name: string;
  type: string;
  description: string;
  required: boolean;
  defaultValue?: string;
}

interface ToolDef {
  name: string;
  method: "GET" | "POST" | "PUT" | "DELETE" | "ACTION";
  description: string;
  args: ToolArg[];
  outputPath?: string;
}


interface VersionEntry {
  version: string;
  date: string;
  changes: string[];
}

interface InstanceDef {
  id: string;
  name: string;
  connectorId: string;
  connectorName: string;
  connectorIcon: string;
  connectorIconBg: string;
  status: InstanceStatus;
  /** The server's connector state (connected | failed | needs-auth | pending | disabled). */
  connState: string;
  /** The last failure recorded for the connector, if any. */
  lastError: string | null;
  enabled: boolean;
  is_channel: boolean;
  config: Record<string, string>;
  // Server-redacted secret slots for the connector (e.g.
  // {caldera_api_key: "***"}). Surfaced in the edit dialog so
  // operators can SEE which credentials are configured (rotate via
  // the setup form). Always strings — backend never returns plaintext.
  secrets: Record<string, string>;
  configKeys: string[];
  metric: { label: string; value: string };
  createdAt: string;
  workspaces: WsEntry[];
  topAgents: { name: string; color: string }[];
  ingestionEnabled: boolean;
  // Tools disabled at this instance — empty = all
  // tools enabled (opt-out). Drives the Tools panel toggle state.
  disabledTools: string[];
}

type ConnectorType = "all" | "channels" | "tools" | "services" | "search" | "devices";
type SdkLanguage = "all" | "go" | "typescript" | "python";

interface ConnectorDefinition {
  id: string;
  name: string;
  type: string;
  version: string;
  latestVersion?: string;
  publisher: string;
  description: string;
  longDescription: string;
  category: Category;
  tags: string[];
  icon: string;
  iconColor: string;
  iconBg: string;
  toolCount: number;
  installs: string;
  installCount: number;
  status: InstallStatus;
  /** "user" for a connector the operator uploaded; deletable from its detail panel. */
  origin?: "bundle" | "user";
  reliability: string;
  authType: string;
  tools: ToolDef[];
  config: ConfigParam[];
  versions: VersionEntry[];
  setupGuide: string;
  dockerImage: string;
  runtime: string;
  sdkLanguage: string;
  ingestion: { enabled: boolean; mode: string; description: string };
  topAgents: { name: string; color: string }[];
}

interface WsEntry {
  name: string;
  slug: string;
  icon: string;
  enabled: boolean;
}

const DEFAULT_WORKSPACES: WsEntry[] = [
  { name: "Playground", slug: "playground", icon: "science", enabled: true },
];

// ─── Data ────────────────────────────────────────────────────────────────────

// Name overrides for connectors until upstream YAML is fixed
const CONNECTOR_NAME_OVERRIDES: Record<string, string> = {
  magellan: "Magellan",
};

function mapToConnectorDef(mc: MarketplaceConnector): ConnectorDefinition {
  return {
    id: mc.id,
    name: CONNECTOR_NAME_OVERRIDES[mc.id] ?? mc.name,
    type: mc.type ?? "",
    version: mc.version,
    publisher: mc.publisher,
    description: mc.description,
    longDescription: mc.longDescription || mc.description,
    category: mc.category as Category,
    tags: mc.tags,
    icon: mc.icon,
    iconColor: mc.iconColor,
    iconBg: mc.iconBg,
    toolCount: mc.toolCount,
    installs: mc.installs,
    installCount: mc.installCount,
    status: mc.status as InstallStatus,
    origin: mc.origin,
    reliability: mc.reliability,
    authType: mc.authType,
    tools: mc.tools as ToolDef[],
    config: mc.config as ConfigParam[],
    versions: mc.versions,
    setupGuide: mc.setupGuide,
    dockerImage: mc.dockerImage,
    runtime: mc.runtime,
    sdkLanguage: mc.sdkLanguage ?? "",
    ingestion: mc.ingestion ?? { enabled: false, mode: "", description: "" },
    topAgents: mc.topAgents,
  };
}

// ─── Instance Mapping ───────────────────────────────────────────────────────

/** Map a ConnectorInstance from the API to the UI-local InstanceDef shape. */
function mapApiInstance(
  inst: ConnectorInstance,
  allConnectors: ConnectorDefinition[],
): InstanceDef {
  const connector = allConnectors.find((c) => c.id === inst.connector_id);
  return {
    id: inst.id,
    name: inst.name,
    connectorId: inst.connector_id,
    connectorName: connector?.name ?? inst.connector_id,
    connectorIcon: connector?.icon ?? "settings_input_component",
    connectorIconBg: connector?.iconBg ?? "rgba(140, 145, 157, 0.1)",
    // The server reports connection health as `state` (connector_state.db);
    // it survives a reload, unlike the per-session result of a Test click.
    status: instanceStatusFromState(inst.state),
    connState: inst.state ?? "pending",
    lastError: inst.last_error ?? null,
    enabled: inst.enabled,
    is_channel: inst.is_channel,
    config: inst.config,
    secrets: inst.secrets ?? {},
    configKeys: Object.keys(inst.config),
    metric: {
      label: "Status",
      value: inst.enabled ? "Active" : "Disabled",
    },
    createdAt: inst.created_at?.slice(0, 10) ?? "",
    workspaces: (inst.workspace_ids ?? []).map((wid) => ({
      name: wid,
      slug: wid,
      icon: "workspaces",
      enabled: true,
    })),
    topAgents: connector?.topAgents ?? [],
    ingestionEnabled: connector?.ingestion?.enabled ?? false,
    // Surface disabled_tools to the UI for the
    // per-instance Tools toggle panel
    disabledTools: inst.disabled_tools ?? [],
  };
}

// ─── Workspace Access Data ──────────────────────────────────────────────────

type AccessLevel = "full" | "selective" | "none";

interface WorkspaceConnectorChip {
  name: string;
  icon: string;
  iconColor: string;
}

interface WorkspaceAccessDef {
  id: string;
  name: string;
  slug: string;
  initial: string;
  members: number;
  accessLevel: AccessLevel;
  connectors: WorkspaceConnectorChip[];
}

const WORKSPACE_ACCESS: WorkspaceAccessDef[] = [
  {
    id: "ws-playground",
    name: "Playground",
    slug: "playground",
    initial: "P",
    members: 1,
    accessLevel: "full",
    connectors: [
      { name: "Magellan", icon: "science", iconColor: "#fbbc30" },
    ],
  },
];

const CATEGORIES: Category[] = ["All", "Communication", "DevTools", "Services", "Search", "Devices", "Productivity", "Finance", "Analytics", "Storage"];

const TYPE_FILTERS: { label: string; value: ConnectorType }[] = [
  { label: "All Types", value: "all" },
  { label: "Channels", value: "channels" },
  { label: "Tools", value: "tools" },
  { label: "Services", value: "services" },
  { label: "Search", value: "search" },
  { label: "Devices", value: "devices" },
];

const SDK_FILTERS: { label: string; value: SdkLanguage }[] = [
  { label: "All", value: "all" },
  { label: "Go", value: "go" },
  { label: "TypeScript", value: "typescript" },
  { label: "Python", value: "python" },
];

// ─── Glass helpers ───────────────────────────────────────────────────────────

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

function Toggle({ enabled }: { enabled: boolean }) {
  return (
    <button
      type="button"
      className="w-11 h-6 rounded-full relative p-1 cursor-pointer transition-colors"
      style={{ background: enabled ? "rgba(3, 115, 33, 0.3)" : "var(--glass-border)" }}
      aria-label={enabled ? "Enabled" : "Disabled"}
    >
      <div
        className="w-4 h-4 rounded-full transition-all"
        style={{
          background: enabled ? "white" : "rgba(140, 145, 157, 0.4)",
          transform: enabled ? "translateX(20px)" : "translateX(0)",
        }}
      />
    </button>
  );
}

// ─── Status Badge ────────────────────────────────────────────────────────────

function StatusBadge({ status, latestVersion }: { status: InstallStatus; latestVersion?: string }) {
  switch (status) {
    case "installed":
      return (
        <span
          className="text-secondary text-[10px] font-label uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1"
          style={{
            background: "rgba(3, 115, 33, 0.3)",
            border: "0.5px solid rgba(123, 220, 123, 0.2)",
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-secondary" style={{ boxShadow: "0 0 8px #7bdc7b" }} />
          Installed
        </span>
      );
    case "update_available":
      return (
        <span
          className="text-tertiary text-[10px] font-label uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1"
          style={{
            background: "rgba(129, 92, 0, 0.3)",
            border: "0.5px solid rgba(251, 188, 48, 0.2)",
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-tertiary" style={{ boxShadow: "0 0 8px #fbbc30" }} />
          Update {latestVersion}
        </span>
      );
    case "not_installed":
      // Theme-aware muted badge: text-on-surface-variant on the
      // surface-container-low token (light-blue tint in light theme,
      // soft dark in dark theme). Replaces hardcoded
      // rgba(52, 51, 64, 0.6) + dim text which had near-zero contrast
      // on the pale-azure light surface.
      return (
        <span className="bg-surface-container-low text-on-surface-variant text-[10px] font-label uppercase tracking-wider px-2.5 py-1 rounded-full border border-outline/30">
          Not Installed
        </span>
      );
  }
}

// ─── Connector Card ──────────────────────────────────────────────────────────

function ConnectorCard({
  connector,
  onSelect,
  onInstall,
}: {
  connector: ConnectorDefinition;
  onSelect: (c: ConnectorDefinition) => void;
  onInstall: (connectorId: string, version: string) => void;
}) {
  return (
    <div
      className="rounded-2xl p-6 group transition-all duration-300 hover:translate-y-[-4px] cursor-pointer"
      style={glassStyle}
      onClick={() => onSelect(connector)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(connector);
        }
      }}
    >
      {/* Icon + Status */}
      <div className="flex justify-between items-start mb-4">
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center"
          style={{ background: connector.iconBg }}
        >
          <span
            className="material-symbols-outlined text-4xl"
            style={{ color: connector.iconColor }}
          >
            {connector.icon}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={connector.status} latestVersion={connector.latestVersion} />
          {connector.status === "installed" && (
            <span
              className="relative flex items-center gap-1 text-[10px] text-secondary font-label"
              title="Healthy"
            >
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary" />
              </span>
            </span>
          )}
        </div>
      </div>

      {/* Name + version + publisher */}
      <h3 className="text-xl font-bold font-headline mb-1 text-on-surface">
        {connector.name}
      </h3>
      <div className="flex items-center gap-2 text-xs text-on-surface-variant mb-4">
        <span className={`font-bold ${connector.status === "update_available" ? "text-tertiary" : ""}`}>
          {connector.status === "update_available" ? connector.latestVersion : connector.version}
        </span>
        <span className="w-1 h-1 rounded-full bg-outline-variant" />
        <span>{connector.publisher}</span>
      </div>

      {/* Description */}
      <p className="text-sm text-on-surface/70 line-clamp-2 mb-6">
        {connector.description}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between pt-4 border-t border-white/5">
        <div className="flex gap-4">
          <div className="flex flex-col">
            <span className="text-[10px] font-label uppercase text-on-surface-variant">Tools</span>
            <span className="text-sm font-bold text-on-surface">{connector.toolCount}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-label uppercase text-on-surface-variant">Installs</span>
            <span className="text-sm font-bold text-on-surface">{connector.installs}</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Download button on every marketplace card.
              Streams the connector.yaml back via /api/agent/marketplace/<id>/download.
              The browser handles save-as via the Content-Disposition header. */}
          <a
            href={`/api/agent/marketplace/${encodeURIComponent(connector.id)}/download`}
            onClick={(e) => e.stopPropagation()}
            className="p-2 rounded-xl text-on-surface-variant hover:text-on-surface transition-colors flex items-center justify-center"
            style={{
              background: "rgba(52, 51, 64, 0.6)",
              border: "0.5px solid var(--glass-border)",
            }}
            title="Download connector.yaml"
            aria-label="Download connector.yaml"
            download={`${connector.id}.yaml`}
          >
            <span className="material-symbols-outlined text-sm">download</span>
          </a>

          {connector.status === "installed" && (
            <button
              type="button"
              className="p-2 rounded-xl text-secondary transition-colors hover:bg-secondary/10"
              style={{
                background: "rgba(52, 51, 64, 0.6)",
                border: "0.5px solid rgba(123, 220, 123, 0.2)",
              }}
              onClick={(e) => e.stopPropagation()}
              aria-label="Installed"
            >
              <span className="material-symbols-outlined">check_circle</span>
            </button>
          )}

          {connector.status === "update_available" && (
            <button
              type="button"
              className="px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all hover:brightness-110"
              style={{
                background: "rgba(129, 92, 0, 0.5)",
                color: "#ffda99",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <span className="material-symbols-outlined text-sm">upgrade</span>
              Update
            </button>
          )}

          {connector.status === "not_installed" && (
            <button
              type="button"
              className="bg-primary-container text-on-surface px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all hover:shadow-[0_0_15px_rgba(25,99,179,0.3)]"
              onClick={(e) => {
                e.stopPropagation();
                onInstall(connector.id, connector.version);
              }}
            >
              <span className="material-symbols-outlined text-sm">add</span>
              Install
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Upload Connector Panel ──────────────────────────────────────────────────
//
// Upload form:
//   1. Real <input type="file" accept=".yaml,.yml"> with FileReader.
//   2. Client-side YAML parse via js-yaml — preview the spec before submit.
//   3. Optional logo upload (image/svg+xml | png | jpeg | gif | webp,
//      ≤200 KB raw → ~260 KB base64). Read as data URI, injected into
//      the YAML as `logo: data:...;base64,...` before submission so it
//      round-trips on download.
//   4. POST to /api/agent/marketplace/upload as multipart with
//      connector_yaml field. Server validates against
//      bundles/spark/connectors/connector.schema.json + collision rules.
//   5. Inline error display when the server rejects the YAML.

// Logo size caps. Raw bytes BEFORE base64 — base64 expansion is ~33%.
// Server enforces 350000 chars maxLength on the encoded data URI; we
// cap raw at 200 KB so the base64 stays under that ceiling.
const LOGO_MAX_RAW_BYTES = 200 * 1024;
const LOGO_ALLOWED_MIME = new Set([
  "image/svg+xml",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
]);

interface ParsedConnectorSpec {
  id?: string;
  version?: string;
  displayName?: string;
  description?: string;
  tags?: string[];
  image?: string;
  logo?: string;
  source?: { language?: string; entrypoint?: string };
  runtimeMapping?: { style?: string; functionPrefix?: string };
  configSchema?: { type?: string; required?: string[]; properties?: Record<string, { type?: string; description?: string; default?: unknown }> };
  secretSlots?: Array<{ name?: string; description?: string; required?: boolean }>;
  spec?: { tools?: Array<{ name?: string; description?: string }> };
}

function UploadConnectorPanel({
  onClose,
  onInstalled,
}: {
  onClose: () => void;
  onInstalled?: () => void;
}) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [showFormatGuide, setShowFormatGuide] = useState(false);

  // Real file state: raw YAML text + parsed spec + filename + size.
  const [yamlFile, setYamlFile] = useState<{
    name: string;
    sizeBytes: number;
    rawText: string;
    parsed: ParsedConnectorSpec;
  } | null>(null);
  // Operator-supplied logo (overrides anything in the YAML). Stored as a
  // data URI so it embeds cleanly when we serialize back to YAML.
  const [logoDataUri, setLogoDataUri] = useState<string | null>(null);
  const [logoFilename, setLogoFilename] = useState<string | null>(null);

  // Submission state
  const [parseError, setParseError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitOk, setSubmitOk] = useState(false);

  const yamlInputRef = useRef<HTMLInputElement | null>(null);
  const logoInputRef = useRef<HTMLInputElement | null>(null);

  const resetFile = useCallback(() => {
    setYamlFile(null);
    setLogoDataUri(null);
    setLogoFilename(null);
    setParseError(null);
    setSubmitError(null);
    setSubmitOk(false);
    if (yamlInputRef.current) yamlInputRef.current.value = "";
    if (logoInputRef.current) logoInputRef.current.value = "";
  }, []);

  // Pick + parse the connector.yaml.
  const handleYamlFile = useCallback(async (file: File) => {
    setParseError(null);
    setSubmitError(null);
    setSubmitOk(false);
    const text = await file.text();
    // Client-side parse for preview; server's jsonschema validation
    // is the source of truth + runs on Upload.
    try {
      const yaml = await import("js-yaml");
      const parsed = yaml.load(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setParseError("YAML must be a top-level object.");
        return;
      }
      setYamlFile({
        name: file.name,
        sizeBytes: file.size,
        rawText: text,
        parsed: parsed as ParsedConnectorSpec,
      });
      // If the YAML carries a logo already, reflect it in the UI so
      // the operator can see what'll round-trip.
      const existingLogo = (parsed as ParsedConnectorSpec).logo;
      if (typeof existingLogo === "string" && existingLogo.startsWith("data:image/")) {
        setLogoDataUri(existingLogo);
        setLogoFilename("(embedded in YAML)");
      }
    } catch (err) {
      setParseError(
        `YAML parse failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }, []);

  // Pick + base64-encode the logo as a data URI.
  const handleLogoFile = useCallback(async (file: File) => {
    setSubmitError(null);
    if (!LOGO_ALLOWED_MIME.has(file.type)) {
      setSubmitError(
        `Unsupported logo MIME type ${file.type || "(unknown)"}. ` +
          `Use SVG, PNG, JPEG, GIF, or WebP.`,
      );
      return;
    }
    if (file.size > LOGO_MAX_RAW_BYTES) {
      setSubmitError(
        `Logo too large (${(file.size / 1024).toFixed(1)} KB). ` +
          `Max ${LOGO_MAX_RAW_BYTES / 1024} KB raw — SVG compresses well.`,
      );
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string" || !result.startsWith("data:image/")) {
        setSubmitError("Logo read failed — not a data URI.");
        return;
      }
      setLogoDataUri(result);
      setLogoFilename(file.name);
    };
    reader.onerror = () => {
      setSubmitError("Logo file read failed.");
    };
    reader.readAsDataURL(file);
  }, []);

  // Build the final YAML text (with operator-uploaded logo merged in,
  // if any) and POST as multipart.
  const handleSubmit = useCallback(async () => {
    if (!yamlFile) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitOk(false);
    try {
      const yaml = await import("js-yaml");
      // If the operator picked a logo separate from what's in the
      // YAML, merge it in. We DUMP the parsed object back to YAML so
      // the merge survives — appending `logo:` to raw text is fragile
      // (depends on existing indentation, doesn't replace a prior
      // logo field cleanly).
      let yamlText = yamlFile.rawText;
      if (logoDataUri && logoDataUri !== yamlFile.parsed.logo) {
        const merged = { ...yamlFile.parsed, logo: logoDataUri };
        yamlText = yaml.dump(merged, {
          // Long base64 strings would be word-wrapped by default;
          // turn that off so the data URI stays on one line and the
          // server's pattern check (^data:image/...) doesn't have to
          // handle multi-line values.
          lineWidth: -1,
          noRefs: true,
        });
      }
      const formData = new FormData();
      // Blob keeps the YAML as bytes — FormData would otherwise
      // round-trip strings as plain form fields, which the server's
      // form.get("connector_yaml") path also accepts but the file-
      // shape is cleaner for the audit trail (server logs filename).
      const blob = new Blob([yamlText], { type: "application/yaml" });
      formData.append(
        "connector_yaml",
        blob,
        yamlFile.name || "connector.yaml",
      );

      const resp = await fetch("/api/agent/marketplace/upload", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setSubmitError(
          data?.error ||
            `Upload failed (HTTP ${resp.status}). Server didn't return a parseable error.`,
        );
        return;
      }
      setSubmitOk(true);
      onInstalled?.();
    } catch (err) {
      setSubmitError(
        `Upload failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSubmitting(false);
    }
  }, [yamlFile, logoDataUri, onInstalled]);

  const handleFileSelect = useCallback(() => {
    yamlInputRef.current?.click();
  }, []);

  const panelStyle = {
    background: "rgba(18, 18, 30, 0.85)",
    backdropFilter: "blur(24px)",
    boxShadow: "-20px 0 40px rgba(0, 0, 0, 0.5)",
  } as const;

  const ghostBorder = {
    border: "0.5px solid var(--glass-border)",
  } as const;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed right-0 top-0 h-full z-50 flex flex-col overflow-hidden"
        style={{
          width: "50%",
          ...panelStyle,
          animation: "slideInRight 0.3s ease-out",
        }}
      >
        {/* Sticky Header */}
        <header
          className="px-6 py-5 flex items-center justify-between border-b border-white/5 shrink-0"
          style={{ background: "rgba(18, 18, 30, 0.8)", backdropFilter: "blur(12px)" }}
        >
          <div className="flex items-center gap-4">
            <span className="material-symbols-outlined text-primary text-2xl">cloud_upload</span>
            <h1 className="font-headline text-2xl font-bold tracking-tight text-on-surface">
              Install Connector
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-on-surface-variant hover:text-on-surface font-medium transition-colors text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold transition-all ${
                yamlFile && !submitting
                  ? "text-white shadow-[0_10px_20px_rgba(25,99,179,0.3)] hover:brightness-110 active:scale-95"
                  : "text-on-surface-variant/30 cursor-not-allowed"
              }`}
              style={{
                background:
                  yamlFile && !submitting
                    ? "linear-gradient(135deg, #1963b3, #2d8df0)"
                    : "rgba(52, 51, 64, 1)",
              }}
              disabled={!yamlFile || submitting}
            >
              <span className="material-symbols-outlined text-[20px]">cloud_upload</span>
              {submitting ? "Uploading…" : submitOk ? "Uploaded" : "Upload"}
            </button>
          </div>
        </header>

        {/* Hidden file inputs — clicked via the visible drop zone / logo card. */}
        <input
          ref={yamlInputRef}
          type="file"
          accept=".yaml,.yml,application/yaml,application/x-yaml,text/yaml"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleYamlFile(f);
          }}
          className="hidden"
        />
        <input
          ref={logoInputRef}
          type="file"
          accept="image/svg+xml,image/png,image/jpeg,image/gif,image/webp"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleLogoFile(f);
          }}
          className="hidden"
        />

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-8 space-y-10">
          {/* Inline errors / success banners */}
          {parseError && (
            <div className="rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error">
              {parseError}
            </div>
          )}
          {submitError && (
            <div className="rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error whitespace-pre-wrap">
              {submitError}
            </div>
          )}
          {submitOk && (
            <div className="rounded-xl border border-secondary/40 bg-secondary/10 p-3 text-xs text-secondary">
              ✓ Connector uploaded. It is now on the Marketplace tab: open its
              card and click Install, then create an instance on the
              Instances tab. Close this panel when you are done.
            </div>
          )}

          {!yamlFile ? (
            <>
              {/* Drop Zone */}
              <section>
                <div
                  className={`h-48 rounded-2xl flex flex-col items-center justify-center cursor-pointer transition-all ${
                    isDragOver
                      ? "border-primary/50 bg-primary/[0.03]"
                      : "border-outline-variant/30 hover:border-primary/30"
                  }`}
                  style={{ border: "2px dashed" }}
                  onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragOver(false);
                    const f = e.dataTransfer.files?.[0];
                    if (f) void handleYamlFile(f);
                  }}
                  onClick={handleFileSelect}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") handleFileSelect(); }}
                >
                  <span className={`material-symbols-outlined text-5xl ${isDragOver ? "text-primary" : "text-primary/40"}`}>
                    cloud_upload
                  </span>
                  <p className="text-sm text-on-surface/60 mt-3">
                    Drop your connector YAML file here
                  </p>
                  <p className="text-[11px] text-on-surface-variant/30 mt-1">or</p>
                  <p className="text-sm text-primary font-medium mt-1 hover:text-primary/80">
                    Browse Files
                  </p>
                  <p className="text-[10px] text-on-surface-variant/30 mt-3">
                    Accepted formats: .yaml, .yml
                  </p>
                </div>
              </section>

              {/* Format Guide */}
              <section>
                <button
                  type="button"
                  onClick={() => setShowFormatGuide(!showFormatGuide)}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-xl transition-colors hover:bg-white/[0.02]"
                  style={ghostBorder}
                >
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm text-primary">menu_book</span>
                    <span className="text-xs font-label font-semibold text-on-surface-variant/50 uppercase tracking-wider">
                      YAML Format Reference
                    </span>
                  </div>
                  <span className="material-symbols-outlined text-on-surface-variant/40 text-sm">
                    {showFormatGuide ? "expand_less" : "expand_more"}
                  </span>
                </button>

                {showFormatGuide && (
                  <div className="mt-2 rounded-xl p-4 bg-surface-container" style={ghostBorder}>
                    <pre className="text-[11px] font-mono leading-relaxed overflow-x-auto">
                      <span className="text-primary/70">display</span><span className="text-on-surface/70">: Connector Name</span>{"\n"}
                      <span className="text-primary/70">name</span><span className="text-on-surface/70">: connector-id</span>{"\n"}
                      <span className="text-primary/70">description</span><span className="text-on-surface/70">: What this connector does</span>{"\n"}
                      <span className="text-primary/70">category</span><span className="text-on-surface/70">: Communication</span>{"\n"}
                      <span className="text-primary/70">configuration</span><span className="text-on-surface/70">:</span>{"\n"}
                      <span className="text-on-surface/70">  - </span><span className="text-primary/70">display</span><span className="text-on-surface/70">: API Key</span>{"\n"}
                      <span className="text-on-surface/70">    </span><span className="text-primary/70">name</span><span className="text-on-surface/70">: api_key</span>{"\n"}
                      <span className="text-on-surface/70">    </span><span className="text-primary/70">type</span><span className="text-on-surface/70">: 4</span><span className="text-on-surface-variant/30">          # 0=text, 4=secret, 8=bool, 15=select</span>{"\n"}
                      <span className="text-on-surface/70">    </span><span className="text-primary/70">required</span><span className="text-on-surface/70">: true</span>{"\n"}
                      <span className="text-primary/70">script</span><span className="text-on-surface/70">:</span>{"\n"}
                      <span className="text-on-surface/70">  </span><span className="text-primary/70">commands</span><span className="text-on-surface/70">:</span>{"\n"}
                      <span className="text-on-surface/70">    - </span><span className="text-primary/70">name</span><span className="text-on-surface/70">: command-name</span>{"\n"}
                      <span className="text-on-surface/70">      </span><span className="text-primary/70">description</span><span className="text-on-surface/70">: What this command does</span>{"\n"}
                      <span className="text-on-surface/70">  </span><span className="text-primary/70">dockerimage</span><span className="text-on-surface/70">: image:tag</span>{"\n"}
                      <span className="text-on-surface/70">  </span><span className="text-primary/70">type</span><span className="text-on-surface/70">: python</span>
                    </pre>
                  </div>
                )}
              </section>
            </>
          ) : (
            <>
              {/* File Indicator — REAL filename + size from the picked file. */}
              <section>
                <div
                  className="flex items-center justify-between p-4 rounded-xl"
                  style={{ background: "var(--glass-bg)", ...ghostBorder }}
                >
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-secondary text-2xl">description</span>
                    <div>
                      <p className="font-medium text-on-surface text-sm">{yamlFile.name}</p>
                      <p className="text-xs text-on-surface-variant uppercase tracking-widest">
                        {(yamlFile.sizeBytes / 1024).toFixed(1)} KB · YAML parsed
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div
                      className="flex items-center gap-2 text-secondary px-3 py-1.5 rounded-full"
                      style={{ background: "rgba(3, 115, 33, 0.2)", border: "0.5px solid rgba(123, 220, 123, 0.2)" }}
                    >
                      <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>
                        check_circle
                      </span>
                      <span className="text-xs font-bold uppercase tracking-wider">Client Parse OK</span>
                    </div>
                    <button
                      type="button"
                      onClick={resetFile}
                      className="text-on-surface-variant/40 hover:text-error transition-colors"
                      aria-label="Remove file"
                    >
                      <span className="material-symbols-outlined text-sm">close</span>
                    </button>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-on-surface-variant/60 ml-1">
                  Server-side schema validation (jsonschema against
                  bundles/spark/connectors/connector.schema.json) runs on
                  Upload. Any drift will appear inline above the
                  drop zone with the violating field path.
                </p>
              </section>

              {/* Connector Details — populated from the actually-parsed YAML. */}
              <section className="space-y-6">
                <SectionHeader title="Connector Details (read-only — edit the YAML to change)" />

                <div className="grid grid-cols-12 gap-6">
                  {/* Logo — operator-uploadable. Saved into the YAML at submit time. */}
                  <div className="col-span-4">
                    <label className="block mb-2 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                      Connector Logo
                    </label>
                    <div
                      onClick={() => logoInputRef.current?.click()}
                      className="aspect-square rounded-xl border-2 border-dashed border-outline-variant bg-surface-container flex flex-col items-center justify-center cursor-pointer hover:border-primary/50 transition-colors group overflow-hidden"
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") logoInputRef.current?.click(); }}
                      aria-label="Upload connector logo"
                    >
                      {logoDataUri ? (
                        <>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={logoDataUri}
                            alt="Connector logo preview"
                            className="w-full h-full object-contain p-3"
                          />
                        </>
                      ) : (
                        <>
                          <span className="material-symbols-outlined text-outline-variant group-hover:text-primary transition-colors text-3xl">
                            add_photo_alternate
                          </span>
                          <span className="text-[10px] text-outline mt-2 uppercase">
                            Upload logo
                          </span>
                          <span className="text-[9px] text-outline-variant/60 mt-1">
                            SVG/PNG/JPEG · max 200 KB
                          </span>
                        </>
                      )}
                    </div>
                    {logoFilename && (
                      <p className="mt-2 text-[10px] text-on-surface-variant/70 font-mono truncate">
                        {logoFilename}
                      </p>
                    )}
                  </div>

                  {/* Display name, ID, Version (read-only) */}
                  <div className="col-span-8 space-y-4">
                    <div>
                      <label className="block mb-1.5 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Display name
                      </label>
                      <input
                        type="text"
                        value={yamlFile.parsed.displayName || yamlFile.parsed.id || "(unset)"}
                        readOnly
                        className="w-full bg-surface-container border-none rounded-xl text-on-surface/80 px-4 py-3 outline-none text-sm"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block mb-1.5 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                          Connector ID
                        </label>
                        <input
                          type="text"
                          value={yamlFile.parsed.id || ""}
                          className="w-full bg-surface-container border-none rounded-xl text-on-surface/60 px-4 py-3 cursor-not-allowed outline-none text-sm font-mono"
                          readOnly
                        />
                      </div>
                      <div>
                        <label className="block mb-1.5 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                          Version
                        </label>
                        <input
                          type="text"
                          value={yamlFile.parsed.version || ""}
                          className="w-full bg-surface-container border-none rounded-xl text-on-surface/60 px-4 py-3 outline-none text-sm font-mono"
                          readOnly
                        />
                      </div>
                    </div>
                  </div>

                  <div className="col-span-12 space-y-4">
                    <div>
                      <label className="block mb-1.5 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Description
                      </label>
                      <textarea
                        value={yamlFile.parsed.description || ""}
                        rows={2}
                        readOnly
                        className="w-full bg-surface-container border-none rounded-xl text-on-surface/80 px-4 py-3 outline-none text-sm resize-none"
                      />
                    </div>
                    {yamlFile.parsed.tags && yamlFile.parsed.tags.length > 0 && (
                      <div>
                        <label className="block mb-1.5 text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                          Tags
                        </label>
                        <div className="flex flex-wrap gap-2">
                          {yamlFile.parsed.tags.map((t) => (
                            <span
                              key={t}
                              className="px-2 py-0.5 text-[10px] font-mono rounded bg-secondary/15 text-secondary"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </section>

              {/* Configuration Schema — derived from the REAL parsed YAML. */}
              <section className="space-y-4">
                <SectionHeader title="Configuration Schema" />
                {yamlFile.parsed.configSchema?.properties &&
                Object.keys(yamlFile.parsed.configSchema.properties).length > 0 ? (
                  <div className="bg-surface-container-low rounded-xl overflow-hidden" style={ghostBorder}>
                    <table className="w-full text-left">
                      <thead className="bg-surface-container-high/50 text-xs uppercase tracking-widest text-on-surface-variant">
                        <tr>
                          <th className="px-6 py-3 font-bold">Parameter</th>
                          <th className="px-6 py-3 font-bold">Type</th>
                          <th className="px-6 py-3 font-bold text-right">Required</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {Object.entries(yamlFile.parsed.configSchema.properties).map(
                          ([key, def]) => {
                            const required =
                              yamlFile.parsed.configSchema?.required?.includes(key) ?? false;
                            return (
                              <tr key={key} className="hover:bg-white/5 transition-colors">
                                <td className="px-6 py-4 font-mono text-sm text-on-surface">
                                  {key}
                                  {def?.description && (
                                    <p className="text-[11px] text-on-surface-variant/60 mt-0.5">
                                      {def.description}
                                    </p>
                                  )}
                                </td>
                                <td className="px-6 py-4 text-sm text-on-surface-variant">
                                  {def?.type || "any"}
                                </td>
                                <td className="px-6 py-4 text-right">
                                  {required && (
                                    <span className="text-secondary material-symbols-outlined text-sm">
                                      check_circle
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          },
                        )}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-xs text-on-surface-variant/60 italic">
                    No configSchema.properties declared. Connector takes no
                    operator-supplied config (rare but allowed).
                  </p>
                )}
                {yamlFile.parsed.secretSlots && yamlFile.parsed.secretSlots.length > 0 && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mt-4 mb-2">
                      Secret slots ({yamlFile.parsed.secretSlots.length})
                    </p>
                    <div className="space-y-2">
                      {yamlFile.parsed.secretSlots.map((slot) => (
                        <div
                          key={slot.name}
                          className="rounded-lg p-3 bg-surface-container-low text-xs flex items-start gap-3"
                          style={ghostBorder}
                        >
                          <span className="material-symbols-outlined text-primary text-sm mt-0.5">
                            lock
                          </span>
                          <div className="flex-1">
                            <div className="font-mono text-on-surface">{slot.name}</div>
                            {slot.description && (
                              <div className="text-on-surface-variant/70 mt-0.5">
                                {slot.description}
                              </div>
                            )}
                          </div>
                          {slot.required && (
                            <span className="text-[10px] font-bold uppercase text-secondary">
                              required
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>

              {/* Detected Tools — from spec.tools */}
              {yamlFile.parsed.spec?.tools && yamlFile.parsed.spec.tools.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center justify-between">
                    <SectionHeader title="Declared Tools" />
                    <span className="bg-primary/10 text-primary text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-tighter">
                      {yamlFile.parsed.spec.tools.length} found
                    </span>
                  </div>

                  <div className="max-h-60 overflow-y-auto grid grid-cols-2 gap-3 pr-2 custom-scrollbar">
                    {yamlFile.parsed.spec.tools.map((tool, idx) => (
                      <div
                        key={tool.name ?? idx}
                        className="p-3 bg-surface-container rounded-xl flex flex-col gap-1"
                        style={ghostBorder}
                      >
                        <span className="font-mono text-xs text-on-surface">
                          {tool.name || "(unnamed)"}
                        </span>
                        {tool.description && (
                          <span className="text-[10px] text-on-surface-variant/70">
                            {tool.description}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Runtime Details — from source + runtimeMapping + image */}
              <section className="space-y-4 pb-4">
                <SectionHeader title="Runtime Details" />
                <div className="space-y-3">
                  {yamlFile.parsed.image && (
                    <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                      <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Image (required for user connectors)
                      </span>
                      <span className="font-mono text-sm text-primary truncate ml-4">
                        {yamlFile.parsed.image}
                      </span>
                    </div>
                  )}
                  {yamlFile.parsed.source?.language && (
                    <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                      <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Source language
                      </span>
                      <span className="text-sm text-on-surface font-mono">
                        {yamlFile.parsed.source.language}
                      </span>
                    </div>
                  )}
                  {yamlFile.parsed.source?.entrypoint && (
                    <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                      <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Entrypoint
                      </span>
                      <span className="text-sm text-on-surface font-mono">
                        {yamlFile.parsed.source.entrypoint}
                      </span>
                    </div>
                  )}
                  {yamlFile.parsed.runtimeMapping?.style && (
                    <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                      <span className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
                        Runtime style
                      </span>
                      <span className="text-sm text-on-surface font-mono">
                        {yamlFile.parsed.runtimeMapping.style}
                      </span>
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
        </div>

        {/* Sticky Footer */}
        <footer className="px-6 py-5 border-t border-white/5 space-y-4 shrink-0 bg-surface-container-high/80 backdrop-blur-md">
          <div className="flex items-start gap-3 text-on-surface-variant">
            <span className="material-symbols-outlined text-tertiary text-lg shrink-0">info</span>
            <p className="text-xs leading-tight">
              This connector will be marked as <span className="text-tertiary font-bold">Custom</span>.
              It will be available for your platform but will not receive automatic updates from the Spark Registry.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 rounded-xl bg-surface-container-highest text-on-surface font-bold hover:bg-white/10 transition-colors text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              className={`flex-[2] flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-bold transition-all text-sm ${
                yamlFile && !submitting
                  ? "text-white shadow-[0_10px_20px_rgba(25,99,179,0.3)] hover:brightness-110 active:scale-95"
                  : "text-on-surface-variant/30 cursor-not-allowed"
              }`}
              style={{
                background:
                  yamlFile && !submitting
                    ? "linear-gradient(135deg, #1963b3, #2d8df0)"
                    : "rgba(52, 51, 64, 1)",
              }}
              disabled={!yamlFile || submitting}
            >
              <span className="material-symbols-outlined text-[20px]">cloud_upload</span>
              {submitting ? "Uploading…" : submitOk ? "Uploaded" : "Upload"}
            </button>
          </div>
        </footer>
      </div>
    </>
  );
}

// ─── Section Header Helper ───────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-1 w-8 rounded-full" style={{ background: "linear-gradient(135deg, #1963b3, #2d8df0)" }} />
      <h2 className="font-headline text-lg font-semibold uppercase tracking-widest text-primary">
        {title}
      </h2>
    </div>
  );
}

// ─── Method Badge ────────────────────────────────────────────────────────────

function MethodBadge({ method }: { method: ToolDef["method"] }) {
  const colors: Record<string, string> = {
    GET: "bg-primary/20 text-primary",
    POST: "bg-secondary/20 text-secondary",
    PUT: "bg-tertiary/20 text-tertiary",
    DELETE: "bg-error/20 text-error",
    ACTION: "bg-primary/20 text-primary",
  };
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded font-mono ${colors[method] ?? "bg-white/10 text-on-surface-variant"}`}>
      {method}
    </span>
  );
}

// ─── Connector Detail Panel ──────────────────────────────────────────────────

function ConnectorDetailPanel({
  connector,
  onClose,
  onInstall,
  onUninstall,
  onDelete,
  pendingAction,
}: {
  connector: ConnectorDefinition;
  onClose: () => void;
  onInstall: (connectorId: string, version: string) => void;
  onUninstall: (connectorId: string) => void;
  /** Remove an uploaded connector from the marketplace (origin "user" only). */
  onDelete: (connectorId: string) => void;
  /** "install" or "uninstall" while the corresponding API call is in
   *  flight; null otherwise. Drives the loading spinner + disabled
   *  state on the install/uninstall button so the operator gets
   *  immediate visual feedback that the click registered. Without it
   *  the button looked unresponsive while the POST/DELETE completed. */
  pendingAction: "install" | "uninstall" | "delete" | null;
}) {
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [showAllTools, setShowAllTools] = useState(false);

  const currentVersion = connector.status === "update_available"
    ? connector.latestVersion ?? connector.version
    : connector.version;
  const installedVersion = connector.status === "update_available"
    ? connector.version
    : null;

  const visibleTools = showAllTools ? connector.tools : connector.tools.slice(0, 5);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 backdrop-blur-sm"
        style={{ background: "rgba(18, 18, 30, 0.6)" }}
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed right-0 top-0 h-full z-50 overflow-y-auto custom-scrollbar"
        style={{
          width: "55%",
          background: "var(--m3-surface-container-lowest)",
          borderLeft: "0.5px solid rgba(66, 71, 81, 0.1)",
          animation: "slideInRight 0.3s ease-out",
        }}
      >
        {/* Sticky Header */}
        <header
          className="sticky top-0 z-10 px-10 py-8 flex items-center justify-between"
          style={glassStyle}
        >
          <div className="flex items-center gap-6">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center shadow-inner"
              style={{ background: "rgba(52, 51, 64, 1)" }}
            >
              <span
                className="material-symbols-outlined text-4xl"
                style={{ color: connector.iconColor, fontVariationSettings: "'FILL' 1" }}
              >
                {connector.icon}
              </span>
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-headline font-bold text-on-surface">
                  {connector.name}
                </h1>
                <span className="bg-surface-container-highest text-on-surface-variant text-xs font-mono px-2 py-1 rounded">
                  {currentVersion}
                </span>
              </div>
              <p className="text-on-surface-variant/70 mt-1 font-medium text-sm">
                {connector.description}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4 shrink-0">
            {connector.status === "not_installed" && (
              <button
                type="button"
                className="bg-primary-container hover:brightness-110 text-on-primary-container px-6 py-3 rounded-xl font-semibold flex items-center gap-2 transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
                onClick={() => onInstall(connector.id, connector.version)}
                disabled={pendingAction !== null}
              >
                {pendingAction === "install" ? (
                  <>
                    <span className="material-symbols-outlined text-[20px] animate-spin">progress_activity</span>
                    Installing…
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined text-[20px]">download</span>
                    Install Connector
                  </>
                )}
              </button>
            )}
            {connector.status === "installed" && (
              <>
                {/* Status badge — purely informational, NOT clickable.
                    A non-interactive badge, separate from the
                    clearly-labeled Uninstall button. */}
                <span
                  className="px-3 py-2 rounded-lg font-medium flex items-center gap-2 text-secondary text-sm"
                  style={{
                    background: "rgba(3, 115, 33, 0.15)",
                    border: "0.5px solid rgba(123, 220, 123, 0.2)",
                  }}
                >
                  <span className="material-symbols-outlined text-[18px]">check_circle</span>
                  Installed
                </span>
                <button
                  type="button"
                  className="px-6 py-3 rounded-xl font-semibold flex items-center gap-2 text-error transition-all active:scale-95 hover:bg-error/10 disabled:opacity-60 disabled:cursor-not-allowed"
                  style={{ border: "0.5px solid rgba(244, 87, 87, 0.3)" }}
                  onClick={() => onUninstall(connector.id)}
                  disabled={pendingAction !== null}
                >
                  {pendingAction === "uninstall" ? (
                    <>
                      <span className="material-symbols-outlined text-[20px] animate-spin">progress_activity</span>
                      Uninstalling…
                    </>
                  ) : (
                    <>
                      <span className="material-symbols-outlined text-[20px]">delete</span>
                      Uninstall
                    </>
                  )}
                </button>
              </>
            )}
            {connector.status === "update_available" && (
              <button
                type="button"
                className="px-6 py-3 rounded-xl font-semibold flex items-center gap-2 transition-all active:scale-95 hover:brightness-110"
                style={{ background: "rgba(129, 92, 0, 0.5)", color: "#ffda99" }}
              >
                <span className="material-symbols-outlined text-[20px]">upgrade</span>
                Update to {connector.latestVersion}
              </button>
            )}
            {connector.origin === "user" && (
              <button
                type="button"
                className="px-6 py-3 rounded-xl font-semibold flex items-center gap-2 text-error transition-all active:scale-95 hover:bg-error/10 disabled:opacity-60 disabled:cursor-not-allowed"
                style={{ border: "0.5px solid rgba(244, 87, 87, 0.3)" }}
                onClick={() => onDelete(connector.id)}
                disabled={pendingAction !== null}
                title="Remove this uploaded connector from the marketplace"
              >
                {pendingAction === "delete" ? (
                  <>
                    <span className="material-symbols-outlined text-[20px] animate-spin">progress_activity</span>
                    Deleting…
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined text-[20px]">delete_forever</span>
                    Delete connector
                  </>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-3 text-on-surface-variant hover:text-on-surface transition-colors"
              aria-label="Close"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </header>

        {/* Content */}
        <div className="p-10 space-y-12 pb-24">
          {/* Stats Grid */}
          <section>
            <div className="grid grid-cols-4 gap-4 mb-8">
              {[
                { label: "Tools", value: String(connector.toolCount), color: "text-primary" },
                { label: "Installs", value: connector.installs, color: "text-secondary" },
                { label: "Reliability", value: connector.reliability, color: "text-tertiary" },
                { label: "Auth", value: connector.authType, color: "text-on-surface" },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="bg-surface-container p-5 rounded-xl text-center"
                  style={{ border: "0.5px solid rgba(66, 71, 81, 0.1)" }}
                >
                  <span className="text-on-surface-variant/60 font-headline uppercase text-[10px] tracking-widest block mb-1">
                    {stat.label}
                  </span>
                  <span className={`text-2xl font-headline font-bold ${stat.color}`}>
                    {stat.value}
                  </span>
                </div>
              ))}
            </div>

            {/* Description */}
            <p className="text-lg text-on-surface-variant leading-relaxed mb-6">
              {connector.longDescription}
            </p>

            {/* Tags */}
            <div className="flex gap-2">
              {connector.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-3 py-1 bg-surface-container-highest rounded-full text-xs text-on-surface-variant font-medium"
                >
                  {tag}
                </span>
              ))}
            </div>
          </section>

          {/* Available Tools */}
          <section>
            <h2 className="text-xl font-headline font-bold text-on-surface mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">terminal</span>
              Available Tools
            </h2>

            <div className="space-y-3">
              {visibleTools.map((tool) => {
                const isExpanded = expandedTool === tool.name;
                return (
                  <div
                    key={tool.name}
                    className="bg-surface-container-low rounded-xl overflow-hidden"
                    style={{ border: "0.5px solid rgba(66, 71, 81, 0.1)" }}
                  >
                    <button
                      type="button"
                      onClick={() => setExpandedTool(isExpanded ? null : tool.name)}
                      className={`w-full flex items-center justify-between p-4 transition-colors ${isExpanded ? "bg-white/5" : "hover:bg-white/5"}`}
                    >
                      <div className="flex items-center gap-4">
                        <MethodBadge method={tool.method} />
                        <span className="font-mono text-sm text-on-surface">{tool.name}</span>
                      </div>
                      <span className="material-symbols-outlined text-on-surface-variant">
                        {isExpanded ? "expand_less" : "expand_more"}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="px-6 pb-6">
                        <p className="text-sm text-on-surface-variant mb-4">{tool.description}</p>

                        {tool.args.length > 0 && (
                          <div className="mb-4">
                            <span className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant/50 mb-2 block">
                              Arguments
                            </span>
                            <table className="w-full text-left text-sm font-body">
                              <thead>
                                <tr className="text-on-surface-variant/60 border-b border-outline-variant/10">
                                  <th className="pb-2 font-medium">Name</th>
                                  <th className="pb-2 font-medium">Type</th>
                                  <th className="pb-2 font-medium">Description</th>
                                  <th className="pb-2 font-medium text-right">Required</th>
                                </tr>
                              </thead>
                              <tbody className="text-on-surface-variant">
                                {tool.args.map((arg, ai) => (
                                  <tr
                                    key={arg.name}
                                    className={ai < tool.args.length - 1 ? "border-b border-outline-variant/10" : ""}
                                  >
                                    <td className="py-3 font-mono text-primary text-xs">{arg.name}</td>
                                    <td className="py-3 text-xs">{arg.type}</td>
                                    <td className="py-3 text-xs">
                                      {arg.description}
                                      {arg.defaultValue && (
                                        <span className="text-on-surface-variant/40 ml-1">
                                          (default: {arg.defaultValue})
                                        </span>
                                      )}
                                    </td>
                                    <td className="py-3 text-right">
                                      {arg.required ? (
                                        <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-error/10 text-error">Required</span>
                                      ) : (
                                        <span className="text-[10px] text-on-surface-variant/30">Optional</span>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}

                        {tool.outputPath && (
                          <div>
                            <span className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant/50 mb-2 block">
                              Output Path
                            </span>
                            <div className="bg-surface-container-highest/50 p-3 rounded-lg font-mono text-xs text-secondary-fixed">
                              {tool.outputPath}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {connector.tools.length > 5 && !showAllTools && (
                <button
                  type="button"
                  onClick={() => setShowAllTools(true)}
                  className="text-sm text-primary hover:text-primary/80 font-medium transition-colors py-2"
                >
                  Show all {connector.tools.length} tools →
                </button>
              )}

              {connector.tools.length === 0 && (
                <p className="text-sm text-on-surface-variant/50 py-4">
                  {connector.toolCount} tools available — detailed tool list will be shown after installation.
                </p>
              )}
            </div>
          </section>

          {/* Configuration Parameters */}
          <section>
            <h2 className="text-xl font-headline font-bold text-on-surface mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary">settings</span>
              Configuration Parameters
            </h2>

            <div className="space-y-3">
              {connector.config.map((param) => (
                <div
                  key={param.name}
                  className="p-4 rounded-xl"
                  style={{
                    background: "var(--glass-bg)",
                    border: "0.5px solid rgba(140, 145, 157, 0.1)",
                  }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-headline font-bold text-on-surface">{param.display}</span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-white/5 text-on-surface-variant/70 border border-white/5">
                      {param.type}
                    </span>
                  </div>
                  {param.options && param.options.length > 0 && (
                    <p className="text-xs text-on-surface-variant/50 mb-1">
                      Options: {param.options.join(", ")}
                    </p>
                  )}
                  <div className="flex items-center gap-3 mt-2">
                    {param.required && (
                      <span className="text-[10px] font-bold text-error/80">Required</span>
                    )}
                    {!param.required && (
                      <span className="text-[10px] text-on-surface-variant/40">Optional</span>
                    )}
                    {param.defaultValue && (
                      <span className="text-[10px] text-on-surface-variant/50">
                        Default: <code className="font-mono text-on-surface-variant/70">{param.defaultValue}</code>
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Agent Usage */}
          {connector.topAgents.length > 0 && (
            <section>
              <h2 className="text-xl font-headline font-bold text-on-surface mb-6 flex items-center gap-2">
                <span className="material-symbols-outlined text-on-surface-variant">smart_toy</span>
                Agent Usage
              </h2>
              <div className="flex flex-wrap gap-2">
                {connector.topAgents.map((agent) => (
                  <span
                    key={agent.name}
                    className="px-2.5 py-1 bg-surface-container-highest border border-white/5 rounded-lg text-[10px] font-medium flex items-center gap-1.5"
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: agent.color, boxShadow: `0 0 6px ${agent.color}` }}
                    />
                    {agent.name}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Setup Guide */}
          <section
            className="p-8 bg-surface-container-low rounded-2xl"
            style={{ border: "0.5px solid rgba(66, 71, 81, 0.1)" }}
          >
            <h2 className="text-2xl font-headline font-bold text-on-surface mb-6">
              Getting Started
            </h2>
            <div className="space-y-3 text-on-surface-variant">
              {connector.setupGuide.split("\n").filter(Boolean).map((line, i) => {
                if (line.startsWith("Note:") || line.startsWith("note:")) {
                  return (
                    <div
                      key={i}
                      className="mt-6 p-4 bg-primary/10 border-l-4 border-primary rounded-r-lg"
                    >
                      <p className="text-sm font-medium text-primary">{line}</p>
                    </div>
                  );
                }
                return (
                  <p key={i} className="text-sm leading-relaxed">
                    {line}
                  </p>
                );
              })}
            </div>
          </section>

          {/* Version History */}
          <section>
            <h2 className="text-xl font-headline font-bold text-on-surface mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined text-on-surface-variant">history</span>
              Version History
            </h2>

            <div className="space-y-6">
              {connector.versions.map((ver, vi) => {
                const isCurrent =
                  (connector.status === "update_available" && ver.version === connector.version) ||
                  (connector.status !== "update_available" && vi === 0 && connector.status === "installed");
                const isLatest = vi === 0;

                return (
                  <div
                    key={ver.version}
                    className={`relative pl-8 border-l border-outline-variant/20 ${vi > 0 && !isCurrent ? "opacity-60" : ""}`}
                  >
                    <div
                      className="absolute left-[-5px] top-0 w-2.5 h-2.5 rounded-full"
                      style={{
                        background: isLatest ? "#a7c8ff" : "rgba(66, 71, 81, 1)",
                        boxShadow: isLatest ? "0 0 8px rgba(25, 99, 179, 0.5)" : "none",
                      }}
                    />
                    <div className="mb-1 flex items-center gap-3">
                      <span className="text-on-surface font-bold">{ver.version}</span>
                      <span className="text-[10px] font-medium text-on-surface-variant/40 uppercase">
                        {ver.date}
                      </span>
                      {isCurrent && (
                        <span className="text-[10px] px-2 py-0.5 rounded-md text-secondary bg-secondary/10">
                          Current
                        </span>
                      )}
                    </div>
                    <ul className="text-sm text-on-surface-variant space-y-1 list-disc pl-4">
                      {ver.changes.map((change, ci) => (
                        <li key={ci}>{change}</li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Technical Manifest */}
          <section>
            <div
              className="bg-surface-container-low rounded-xl p-6"
              style={{ border: "0.5px solid rgba(66, 71, 81, 0.1)" }}
            >
              <h2 className="text-xs font-headline uppercase tracking-widest text-on-surface-variant/40 mb-4">
                Technical Manifest
              </h2>
              <div className="space-y-0">
                {[
                  ["Docker Image", connector.dockerImage],
                  ["Runtime", connector.runtime],
                  ["Connector ID", connector.id],
                  ["Source", connector.origin === "user" ? "Uploaded" : connector.status === "installed" ? "System" : "Marketplace"],
                  ["Auth Type", connector.authType],
                ].map(([label, value], i, arr) => (
                  <div
                    key={label}
                    className={`flex justify-between items-center py-3 ${i < arr.length - 1 ? "border-b border-outline-variant/10" : ""}`}
                  >
                    <span className="text-sm text-on-surface-variant">{label}</span>
                    <span className="text-sm font-mono text-on-surface">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

// ─── Instances Tab ──────────────────────────────────────────────────────────

/**
 * Tools toggle panel.
 *
 * Renders inside an expanded instance row. Each tool the connector
 * ships gets a checkbox; toggling it updates `disabled_tools` on
 * the instance via PATCH. The agent's tool catalog rebuilds when
 * the connector_loader re-registers (next tool call or instance
 * config change picks up the change without restart).
 *
 * The panel uses local optimistic state with snapback on PATCH
 * failure — the operator sees the checkbox flip immediately, and
 * a subtle "saving..." indicator fades in/out per tool.
 *
 * The "Enable all" / "Disable all" mass actions write a single
 * PATCH covering every tool the connector ships.
 */
function ToolsTogglePanel({
  instance,
  tools,
  onRefresh,
}: {
  instance: InstanceDef;
  tools: ToolDef[];
  onRefresh: () => void;
}) {
  const [disabled, setDisabled] = useState<Set<string>>(
    new Set(instance.disabledTools),
  );
  const [savingTools, setSavingTools] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  // Keep local state in sync if the parent re-fetches the instance
  // (e.g. after Refresh or a sibling toggle landed via socket).
  useEffect(() => {
    setDisabled(new Set(instance.disabledTools));
  }, [instance.disabledTools]);

  const enabledCount = tools.length - disabled.size;

  const patch = useCallback(
    async (next: Set<string>, touchedTools: string[]) => {
      setError(null);
      setSavingTools((prev) => {
        const ns = new Set(prev);
        touchedTools.forEach((t) => ns.add(t));
        return ns;
      });
      try {
        const resp = await fetch(`/api/agent/instances/${instance.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ disabled_tools: Array.from(next) }),
        });
        if (!resp.ok) {
          const text = await resp.text().catch(() => "");
          throw new Error(text || `HTTP ${resp.status}`);
        }
        // No need to re-fetch; we already updated optimistic state.
        onRefresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        // Snapback — revert the optimistic change
        setDisabled(new Set(instance.disabledTools));
      } finally {
        setSavingTools((prev) => {
          const ns = new Set(prev);
          touchedTools.forEach((t) => ns.delete(t));
          return ns;
        });
      }
    },
    [instance.id, instance.disabledTools, onRefresh],
  );

  const toggleOne = useCallback(
    (toolName: string) => {
      const next = new Set(disabled);
      if (next.has(toolName)) next.delete(toolName);
      else next.add(toolName);
      setDisabled(next);
      patch(next, [toolName]);
    },
    [disabled, patch],
  );

  const enableAll = useCallback(() => {
    const next = new Set<string>();
    const touched = tools
      .filter((t) => disabled.has(t.name))
      .map((t) => t.name);
    setDisabled(next);
    patch(next, touched);
  }, [tools, disabled, patch]);

  const disableAll = useCallback(() => {
    const next = new Set(tools.map((t) => t.name));
    const touched = tools
      .filter((t) => !disabled.has(t.name))
      .map((t) => t.name);
    setDisabled(next);
    patch(next, touched);
  }, [tools, disabled, patch]);

  return (
    <div className="mt-2 pb-2 space-y-3">
      {/* Header: count + mass actions */}
      <div className="flex items-center justify-between px-1">
        <div className="text-xs text-on-surface-variant">
          <span className="font-mono font-bold text-on-surface">
            {enabledCount}
          </span>
          /{tools.length} tool{tools.length === 1 ? "" : "s"} enabled for the agent
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={enableAll}
            disabled={enabledCount === tools.length}
            className="text-[11px] font-mono uppercase tracking-wider text-primary/70 hover:text-primary disabled:opacity-30 transition-colors"
          >
            Enable all
          </button>
          <span className="text-on-surface-variant/30">·</span>
          <button
            type="button"
            onClick={disableAll}
            disabled={enabledCount === 0}
            className="text-[11px] font-mono uppercase tracking-wider text-on-surface-variant/70 hover:text-error disabled:opacity-30 transition-colors"
          >
            Disable all
          </button>
        </div>
      </div>

      {error && (
        <div
          className="text-[11px] px-3 py-2 rounded mx-1"
          style={{ background: "rgba(239, 68, 68, 0.1)", border: "0.5px solid rgba(239, 68, 68, 0.3)", color: "#fca5a5" }}
        >
          ⚠ {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        {tools.map((tool) => {
          const isDisabled = disabled.has(tool.name);
          const isSaving = savingTools.has(tool.name);
          return (
            <label
              key={tool.name}
              className="p-3 rounded-xl flex items-start gap-3 cursor-pointer transition-colors"
              style={{
                background: isDisabled
                  ? "rgba(52, 51, 64, 0.2)"
                  : "rgba(52, 51, 64, 0.4)",
                border: isDisabled
                  ? "0.5px solid rgba(140, 145, 157, 0.05)"
                  : "0.5px solid rgba(140, 145, 157, 0.12)",
                opacity: isDisabled ? 0.55 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={!isDisabled}
                onChange={() => toggleOne(tool.name)}
                disabled={isSaving}
                className="mt-1 cursor-pointer"
                aria-label={`${isDisabled ? "Enable" : "Disable"} tool ${tool.name}`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded font-mono ${
                      tool.method === "GET"
                        ? "bg-primary/20 text-primary"
                        : tool.method === "POST"
                          ? "bg-secondary/20 text-secondary"
                          : tool.method === "PUT"
                            ? "bg-tertiary/20 text-tertiary"
                            : tool.method === "DELETE"
                              ? "bg-error/20 text-error"
                              : "bg-primary/20 text-primary"
                    }`}
                  >
                    {tool.method}
                  </span>
                  <span className="font-mono text-[11px] text-on-surface truncate">
                    {tool.name}
                  </span>
                  {isSaving && (
                    <span className="material-symbols-outlined animate-spin text-[10px] text-on-surface-variant">
                      progress_activity
                    </span>
                  )}
                </div>
                {tool.description && (
                  <p className="text-[10px] text-on-surface-variant/60 line-clamp-2 mt-1">
                    {tool.description}
                  </p>
                )}
              </div>
            </label>
          );
        })}
      </div>

      <p className="text-[10px] text-on-surface-variant/60 px-1 italic">
        Disabled tools won&apos;t appear in the agent&apos;s catalog. Toggles
        persist per-instance and take effect on the next tool call without
        restarting the connector.
      </p>
    </div>
  );
}


function InstancesTab({
  onCreateInstance,
  allConnectors,
  instances,
  onTestInstance,
  onRefreshData,
}: {
  onCreateInstance: () => void;
  allConnectors: ConnectorDefinition[];
  instances: InstanceDef[];
  /** Resolves to what the test meant, or null when the request itself failed. */
  onTestInstance: (instanceId: string) => Promise<TestOutcome | null>;
  onRefreshData: () => void;
}) {
  // Edit instance state
  const [editingInstance, setEditingInstance] = useState<InstanceDef | null>(null);
  const [editName, setEditName] = useState("");
  const [editConfig, setEditConfig] = useState<Record<string, string>>({});
  const [editSaving, setEditSaving] = useState(false);
  const [editFeedback, setEditFeedback] = useState<{ type: "success" | "error" | "info"; message: string } | null>(null);
  const [editTestStatus, setEditTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");

  // Test button visual feedback state
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; kind: TestOutcome["kind"] } | null>(null);
  const runTest = useCallback(
    async (instanceId: string) => {
      setTestingId(instanceId);
      let kind: TestOutcome["kind"] = "failed";
      try {
        const outcome = await onTestInstance(instanceId);
        if (outcome) kind = outcome.kind;
      } catch {
        // the toast raised by the handler already says why
      } finally {
        setTestingId(null);
        setTestResult({ id: instanceId, kind });
        setTimeout(() => setTestResult(null), 2000);
      }
    },
    [onTestInstance],
  );

  // Delete instance state (two-click pattern)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Show tools state
  const [showToolsInstanceId, setShowToolsInstanceId] = useState<string | null>(null);

  // Assign workspace dialog state
  const [assigningInstanceId, setAssigningInstanceId] = useState<string | null>(null);

  // The connector card declares every field and secret slot of the form.
  // Edit renders from it, so a field left empty when the instance was
  // created can be filled in later; a connector with no declared fields
  // (one that was uploaded without a config schema) falls back to the keys
  // the instance already has.
  const editParams = useMemo<ConfigParam[]>(
    () =>
      editingInstance
        ? (allConnectors.find((c) => c.id === editingInstance.connectorId)?.config ?? [])
        : [],
    [editingInstance, allConnectors],
  );
  const editConnectorName = editingInstance?.connectorName ?? "";
  const editSetSecrets = useMemo(
    () => Object.keys(editingInstance?.secrets ?? {}),
    [editingInstance],
  );
  // The visible required fields still empty. A hidden field is never
  // required, and a secret the server already holds counts as filled.
  const editMissing = useMemo(
    () => missingRequired(editParams, editConfig, editSetSecrets),
    [editParams, editConfig, editSetSecrets],
  );
  // A number field holding text such as "30s" would make the connector fail
  // when it reads it, so Save waits until it is a number or empty.
  const editBadNumbers = useMemo(
    () => invalidNumbers(editParams, editConfig),
    [editParams, editConfig],
  );
  // Saved keys the card does not declare; they keep the plain key-list inputs.
  const editExtraKeys = useMemo(() => {
    const declared = new Set(editParams.map((p) => p.name));
    return Object.keys(editConfig).filter((k) => !declared.has(k));
  }, [editParams, editConfig]);

  const startEdit = useCallback(
    (inst: InstanceDef) => {
      const params = allConnectors.find((c) => c.id === inst.connectorId)?.config ?? [];
      setEditingInstance(inst);
      setEditName(inst.name);
      // Every declared field and secret slot, then what the instance saved.
      // Stored secrets arrive redacted ("***"): the dialog shows a placeholder
      // and sends the sentinel back unless the operator types a new value.
      setEditConfig(
        seedEditValues(inst.connectorId, params, { config: inst.config, secrets: inst.secrets }),
      );
      setEditFeedback(null);
    },
    [allConnectors],
  );

  // What Save and the dry-run Test Connection both send, so a test probes
  // exactly what Save would store (the destination mode's hidden side
  // included). The server replaces `config` wholesale and merges `secrets`
  // per slot, with "***" meaning keep.
  const editPayload = useCallback(() => {
    if (!editingInstance) return { config: {}, secrets: {} };
    return buildEditPayload(editParams, editConfig, {
      config: editingInstance.config,
      secrets: editingInstance.secrets ?? {},
    });
  }, [editingInstance, editParams, editConfig]);

  const handleEditSave = useCallback(async () => {
    if (!editingInstance) return;
    setEditSaving(true);
    setEditFeedback(null);
    try {
      const { config: splitConfig, secrets: splitSecrets } = editPayload();

      const result = await updateInstance(editingInstance.id, {
        name: editName,
        config: splitConfig,
        // ConnectorInstance.secrets is typed but updateInstance's body
        // type omits it — cast through to send. Backend accepts
        // {secrets: {...}} for rotation.
        ...({ secrets: splitSecrets } as Partial<{
          name: string;
          config: Record<string, unknown>;
          enabled: boolean;
          is_channel: boolean;
        }>),
      });
      if (result.ok) {
        // A save that changed the settings restarts the connector's container
        // (it reads them once, at start); say how that went.
        const outcome = saveOutcome(result.data.restart, editingInstance.connectorId);
        setEditFeedback(outcome);
        onRefreshData();
        // Leave the dialog open long enough to read a restart message, and keep
        // it open on a failed restart, whose text tells the operator what to do.
        if (outcome.type !== "error") {
          setTimeout(() => setEditingInstance(null), result.data.restart ? 2500 : 800);
        }
      } else {
        setEditFeedback({ type: "error", message: "Failed to update instance." });
      }
    } catch {
      setEditFeedback({ type: "error", message: "An error occurred while saving." });
    } finally {
      setEditSaving(false);
    }
  }, [editingInstance, editName, editPayload, onRefreshData]);

  // Delete handler
  const handleDelete = useCallback(async (instanceId: string) => {
    try {
      const result = await deleteInstance(instanceId);
      if (result.ok) {
        onRefreshData();
      }
    } catch {
      // silent fail
    }
    setConfirmDeleteId(null);
  }, [onRefreshData]);

  // Toggle conflict feedback — when enabling fails because another
  // instance for the same connector is already active, the backend
  // returns 409 with an explanatory message. Surface it instead of
  // silently snapping the toggle back.
  const [toggleError, setToggleError] = useState<string | null>(null);

  // Enable/disable toggle handler
  const handleToggleEnabled = useCallback(async (inst: InstanceDef) => {
    setToggleError(null);
    try {
      const result = await updateInstance(inst.id, { enabled: !inst.enabled });
      if (!result.ok) {
        // 409 from "active-instance-per-connector" enforcement, or any
        // other server-side validation failure. Show the upstream
        // message verbatim — it's already operator-friendly.
        setToggleError(result.error.message ?? "Could not toggle instance.");
        setTimeout(() => setToggleError(null), 6000);
      } else if (result.data.restart) {
        // Enabling an instance restarts its connector so it loads the settings
        // saved while it was off; say how that went.
        const outcome = saveOutcome(result.data.restart, inst.connectorId);
        notify(outcome.type, inst.name, outcome.message);
      }
      onRefreshData();
    } catch (err) {
      setToggleError(
        err instanceof Error ? err.message : "Could not toggle instance.",
      );
      setTimeout(() => setToggleError(null), 6000);
      onRefreshData();
    }
  }, [onRefreshData]);

  // Assign workspace handler
  const handleAssignWorkspace = useCallback(async (instanceId: string, workspaceId: string) => {
    try {
      const result = await assignWorkspace(instanceId, workspaceId);
      if (result.ok) {
        onRefreshData();
      }
    } catch {
      // silent fail
    }
    setAssigningInstanceId(null);
  }, [onRefreshData]);

  // Export instance config
  const handleExportInstance = useCallback((inst: InstanceDef) => {
    const exportData = {
      name: inst.name,
      connector_id: inst.connectorId,
      config: Object.fromEntries(
        Object.entries(inst.config || {}).map(([k, v]) => [
          k,
          /key|token|secret|password/i.test(k) ? "****" : v,
        ]),
      ),
      workspace_ids: inst.workspaces.map((w) => w.slug),
      is_channel: inst.is_channel,
      enabled: inst.enabled,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `instance-${inst.name.toLowerCase().replace(/\s+/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, []);

  // Channel toggle handler
  const handleToggleChannel = useCallback(async (inst: InstanceDef) => {
    try {
      await updateInstance(inst.id, { is_channel: !inst.is_channel });
      onRefreshData();
    } catch {
      onRefreshData();
    }
  }, [onRefreshData]);

  const grouped = useMemo(() => {
    const groups: Record<string, InstanceDef[]> = {};
    for (const inst of instances) {
      const key = inst.connectorName;
      if (!groups[key]) groups[key] = [];
      groups[key].push(inst);
    }
    return Object.entries(groups);
  }, [instances]);

  const totalInstances = instances.length;
  const connectedCount = instances.filter((i) => i.status === "connected").length;
  const errorCount = instances.filter((i) => i.status === "error").length;
  const installedConnectors = new Set(instances.map((i) => i.connectorId));
  const totalInstalledConnectors = allConnectors.filter((c) => c.status !== "not_installed").length;

  function statusDot(status: InstanceStatus) {
    switch (status) {
      case "connected":
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full" style={{ background: "rgba(3, 115, 33, 0.15)", border: "0.5px solid rgba(123, 220, 123, 0.2)" }}>
            <div className="w-1.5 h-1.5 rounded-full bg-secondary" style={{ boxShadow: "0 0 8px #7bdc7b" }} />
            <span className="text-xs font-medium text-secondary">Connected</span>
          </div>
        );
      case "error":
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full" style={{ background: "rgba(147, 0, 10, 0.15)", border: "0.5px solid rgba(255, 180, 171, 0.2)" }}>
            <div className="w-1.5 h-1.5 rounded-full bg-error" />
            <span className="text-xs font-medium text-error">Error</span>
          </div>
        );
      case "not_tested":
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full" style={{ background: "rgba(129, 92, 0, 0.15)", border: "0.5px solid rgba(251, 188, 48, 0.2)" }}>
            <div className="w-1.5 h-1.5 rounded-full bg-tertiary" style={{ boxShadow: "0 0 8px #fbbc30" }} />
            <span className="text-xs font-medium text-tertiary">Not Tested</span>
          </div>
        );
    }
  }

  return (
    <div className="rounded-3xl p-8 relative overflow-hidden" style={{ background: "var(--m3-surface-container-low)" }}>
      {/* Decorative glow */}
      <div className="absolute -top-24 -right-24 w-96 h-96 bg-primary/5 blur-[100px] rounded-full pointer-events-none" />

      {/* Section header */}
      <div className="flex justify-between items-center mb-8">
        <h3 className="text-xl font-headline font-semibold text-on-surface">Connector Instances</h3>
        <button
          type="button"
          onClick={onCreateInstance}
          className="text-white px-6 py-2.5 rounded-xl font-headline font-bold text-sm flex items-center gap-2 shadow-lg active:scale-95 transition-all"
          style={{ background: "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)" }}
        >
          <span className="material-symbols-outlined text-lg">add</span>
          Create Instance
        </button>
      </div>

      {/* Toggle conflict / error banner — auto-clears after 6s. */}
      {toggleError && (
        <div
          className="mb-4 rounded-xl px-4 py-3 text-sm flex items-start gap-2"
          style={{
            background: "rgba(147, 0, 10, 0.12)",
            border: "0.5px solid rgba(255, 180, 171, 0.25)",
            color: "#ffb4ab",
          }}
        >
          <span className="material-symbols-outlined text-base mt-0.5">error</span>
          <span>{toggleError}</span>
        </div>
      )}

      {/* Summary strip — bento cards */}
      <div className="grid grid-cols-4 gap-4 mb-10">
        <div className="p-5 rounded-2xl" style={{ ...glassStyle, background: "var(--m3-surface-container)" }}>
          <p className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label mb-1">Total Instances</p>
          <p className="text-3xl font-headline font-bold text-on-surface">{totalInstances}</p>
        </div>
        <div className="p-5 rounded-2xl" style={{ ...glassStyle, background: "var(--m3-surface-container)" }}>
          <div className="flex justify-between items-start">
            <p className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label mb-1">Connected</p>
            <div className="w-2 h-2 rounded-full bg-secondary" style={{ boxShadow: "0 0 12px rgba(123, 220, 123, 0.4)" }} />
          </div>
          <p className="text-3xl font-headline font-bold text-secondary">{connectedCount}</p>
        </div>
        <div className="p-5 rounded-2xl" style={{ ...glassStyle, background: "var(--m3-surface-container)" }}>
          <p className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label mb-1">Errors</p>
          <p className={`text-3xl font-headline font-bold ${errorCount > 0 ? "text-error" : "text-on-surface/40"}`}>{errorCount}</p>
        </div>
        <div className="p-5 rounded-2xl" style={{ ...glassStyle, background: "var(--m3-surface-container)" }}>
          <p className="text-[10px] uppercase tracking-wider text-on-surface-variant font-label mb-1">Connectors Used</p>
          <div className="flex items-baseline gap-1">
            <span className="text-3xl font-headline font-bold text-on-surface">{installedConnectors.size}</span>
            <span className="text-sm text-on-surface-variant">/ {totalInstalledConnectors} available</span>
          </div>
        </div>
      </div>

      {/* Grouped instance rows */}
      <div className="space-y-10">
        {grouped.map(([connectorName, instances]) => {
          const first = instances[0];
          return (
            <section key={connectorName}>
              <div className="flex items-center gap-3 mb-4">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ background: first.connectorIconBg }}
                >
                  <span className="material-symbols-outlined text-lg text-on-surface">{first.connectorIcon}</span>
                </div>
                <h4 className="text-xs font-label font-bold tracking-widest text-on-surface-variant uppercase">
                  {connectorName}
                  <span className="ml-2 font-normal lowercase opacity-50">({instances.length} instance{instances.length !== 1 ? "s" : ""})</span>
                </h4>
              </div>

              <div className="grid grid-cols-1 gap-3">
                {instances.map((inst) => {
                  const connectorForTools = allConnectors.find((c) => c.id === inst.connectorId);
                  const toolsExpanded = showToolsInstanceId === inst.id;
                  return (
                  <div
                    key={inst.id}
                    className="group rounded-2xl transition-all"
                    style={{
                      background: "var(--glass-bg)",
                      border: "0.5px solid rgba(140, 145, 157, 0.1)",
                    }}
                  >
                  <div
                    className="p-4 flex items-center justify-between cursor-pointer"
                    onClick={(e) => {
                      // Only open edit if the click target is not inside a button or interactive element
                      const target = e.target as HTMLElement;
                      if (target.closest("button") || target.closest("[role='button']")) return;
                      startEdit(inst);
                    }}
                  >
                    <div className="flex items-center gap-6">
                      {/* Enable/disable toggle */}
                      <button
                        type="button"
                        onClick={() => handleToggleEnabled(inst)}
                        className="w-11 h-6 rounded-full relative p-1 cursor-pointer transition-colors shrink-0"
                        style={{ background: inst.enabled ? "rgba(3, 115, 33, 0.3)" : "var(--glass-border)" }}
                        aria-label={inst.enabled ? "Disable instance" : "Enable instance"}
                      >
                        <div
                          className="w-4 h-4 rounded-full transition-all"
                          style={{
                            background: inst.enabled ? "white" : "rgba(140, 145, 157, 0.4)",
                            transform: inst.enabled ? "translateX(20px)" : "translateX(0)",
                          }}
                        />
                      </button>

                      <div className="flex flex-col">
                        <div className="flex items-center gap-2">
                          <span className="text-on-surface font-headline font-semibold">{inst.name}</span>
                          {/* Channel badge */}
                          {inst.is_channel && (
                            <span
                              className="text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"
                              style={{ background: "rgba(167, 200, 255, 0.1)", border: "0.5px solid rgba(167, 200, 255, 0.2)", color: "#a7c8ff" }}
                            >
                              <span className="material-symbols-outlined text-xs">chat_bubble</span>
                              Channel
                            </span>
                          )}
                          {/* Workspace badges */}
                          {inst.workspaces.map((ws) => (
                            <span
                              key={ws.slug}
                              className="text-[10px] font-label px-2 py-0.5 rounded-full text-on-surface-variant"
                              style={{ background: "rgba(52, 51, 64, 0.6)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
                            >
                              {ws.name}
                            </span>
                          ))}
                        </div>
                        <div className="flex gap-2 mt-1">
                          {inst.configKeys.map((key) => (
                            <span
                              key={key}
                              className="px-2 py-0.5 rounded-md text-[10px] font-label text-primary"
                              style={{
                                background: "rgba(52, 51, 64, 1)",
                                border: "0.5px solid rgba(167, 200, 255, 0.2)",
                              }}
                            >
                              {key}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex flex-col items-center border-l border-outline-variant/30 pl-6">
                        <span className="text-[10px] font-label text-on-surface-variant uppercase">{inst.metric.label}</span>
                        <span className={`text-xs font-bold ${inst.status === "not_tested" ? "text-on-surface/50 italic" : "text-on-surface"}`}>
                          {inst.metric.value}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      {statusDot(inst.status)}

                      {/* Agent availability indicator: the agent can use an
                          instance's tools whenever it is enabled. The connector
                          state only says whether the connection is known good,
                          untested or failing (see lib/instance-status.ts). */}
                      {(() => {
                        const note = toolNote({ enabled: inst.enabled, state: inst.connState, lastError: inst.lastError });
                        const style =
                          note.tone === "ok"
                            ? { background: "rgba(3, 115, 33, 0.1)", border: "0.5px solid rgba(123, 220, 123, 0.15)" }
                            : note.tone === "warn"
                              ? { background: "rgba(129, 92, 0, 0.12)", border: "0.5px solid rgba(251, 188, 48, 0.2)" }
                              : { background: "rgba(140, 145, 157, 0.08)", border: "0.5px solid rgba(140, 145, 157, 0.12)" };
                        const tint =
                          note.tone === "ok"
                            ? "text-secondary"
                            : note.tone === "warn"
                              ? "text-tertiary"
                              : note.tone === "neutral"
                                ? "text-on-surface-variant"
                                : "text-on-surface-variant/50";
                        return (
                          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={style} title={note.title}>
                            <span className={`material-symbols-outlined text-xs ${tint}`}>smart_toy</span>
                            <span className={`text-[10px] font-medium ${tint}`}>{note.label}</span>
                          </div>
                        );
                      })()}

                      {/* Channel toggle (only for connectors with ingestion enabled) */}
                      {inst.ingestionEnabled && (
                        <button
                          type="button"
                          onClick={() => handleToggleChannel(inst)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-label transition-all ${
                            inst.is_channel
                              ? "text-primary"
                              : "text-on-surface-variant hover:text-primary"
                          }`}
                          style={
                            inst.is_channel
                              ? { background: "rgba(167, 200, 255, 0.1)", border: "0.5px solid rgba(167, 200, 255, 0.2)" }
                              : { background: "rgba(52, 51, 64, 0.4)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }
                          }
                          aria-label={inst.is_channel ? "Disable channel mode" : "Enable channel mode"}
                        >
                          <span className="material-symbols-outlined text-sm">chat_bubble</span>
                          {inst.is_channel ? "Channel" : "Use as Channel"}
                        </button>
                      )}

                      <div className={`flex gap-2 ${inst.status === "not_tested" ? "opacity-100" : "opacity-0 group-hover:opacity-100"} transition-opacity`}>
                        {inst.status === "not_tested" && (
                          <button
                            type="button"
                            className="text-primary px-4 py-1.5 rounded-lg text-xs font-headline font-bold transition-all flex items-center gap-1.5"
                            style={{ background: "rgba(167, 200, 255, 0.1)", border: "0.5px solid rgba(167, 200, 255, 0.2)" }}
                            title="Test Connection"
                            disabled={testingId === inst.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void runTest(inst.id);
                            }}
                          >
                            {testingId === inst.id ? (
                              <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
                            ) : testResult?.id === inst.id && testResult.kind === "passed" ? (
                              <span className="material-symbols-outlined text-sm text-secondary">check_circle</span>
                            ) : testResult?.id === inst.id && testResult.kind === "failed" ? (
                              <span className="material-symbols-outlined text-sm text-error">error</span>
                            ) : testResult?.id === inst.id && testResult.kind === "no_test" ? (
                              <span className="material-symbols-outlined text-sm text-on-surface-variant">info</span>
                            ) : null}
                            {testingId === inst.id ? "Testing..." : "Test Connection"}
                          </button>
                        )}
                        {inst.status !== "not_tested" && (
                          <button
                            type="button"
                            className="p-2 hover:bg-surface-bright rounded-lg text-on-surface-variant hover:text-primary transition-colors"
                            aria-label="Test Connection"
                            title="Test Connection"
                            disabled={testingId === inst.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void runTest(inst.id);
                            }}
                          >
                            <span
                              className={`material-symbols-outlined text-xl ${
                                testingId === inst.id
                                  ? "animate-spin"
                                  : testResult?.id === inst.id && testResult.kind === "passed"
                                    ? "text-secondary"
                                    : testResult?.id === inst.id && testResult.kind === "failed"
                                      ? "text-error"
                                      : ""
                              }`}
                            >
                              {testingId === inst.id
                                ? "progress_activity"
                                : testResult?.id === inst.id && testResult.kind === "passed"
                                  ? "check_circle"
                                  : testResult?.id === inst.id && testResult.kind === "failed"
                                    ? "error"
                                    : testResult?.id === inst.id && testResult.kind === "no_test"
                                      ? "info"
                                      : "play_circle"}
                            </span>
                          </button>
                        )}

                        {/* Edit button */}
                        <button
                          type="button"
                          className="p-2 hover:bg-surface-bright rounded-lg text-on-surface-variant hover:text-primary transition-colors"
                          aria-label="Edit Instance"
                          title="Edit Instance"
                          onClick={() => startEdit(inst)}
                        >
                          <span className="material-symbols-outlined text-xl">edit</span>
                        </button>

                        {/* Export instance config */}
                        <button
                          type="button"
                          className="p-2 hover:bg-surface-bright rounded-lg text-on-surface-variant hover:text-primary transition-colors"
                          aria-label="Export Instance Config"
                          title="Export Instance Config"
                          onClick={() => handleExportInstance(inst)}
                        >
                          <span className="material-symbols-outlined text-xl">download</span>
                        </button>

                        {/* Delete button (two-click pattern) */}
                        {confirmDeleteId === inst.id ? (
                          <button
                            type="button"
                            className="px-3 py-1.5 rounded-lg text-xs font-bold text-error transition-all"
                            style={{ background: "rgba(147, 0, 10, 0.2)", border: "0.5px solid rgba(255, 180, 171, 0.3)" }}
                            onClick={() => handleDelete(inst.id)}
                            onBlur={() => setTimeout(() => setConfirmDeleteId(null), 200)}
                          >
                            Confirm?
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="p-2 hover:bg-surface-bright rounded-lg text-on-surface-variant hover:text-error transition-colors"
                            aria-label="Delete Instance"
                            title="Delete Instance"
                            onClick={() => setConfirmDeleteId(inst.id)}
                          >
                            <span className="material-symbols-outlined text-xl">delete</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Tools toggle row, a prominent chip so the operator
                      notices it on dense connector pages (XSIAM has 59
                      tools, XDR has 50 — operators want to know how many
                      are exposed). The chip shows ENABLED-COUNT / TOTAL and a state hint
                      (all enabled vs. N disabled vs. all disabled). */}
                  {connectorForTools && connectorForTools.tools.length > 0 && (() => {
                    const total = connectorForTools.tools.length;
                    const disabledCount = (inst.disabledTools ?? []).length;
                    const enabledCount = total - disabledCount;
                    const allEnabled = disabledCount === 0;
                    const allDisabled = enabledCount === 0;
                    const chipColor = allEnabled
                      ? "rgba(123, 220, 123, 0.18)"
                      : allDisabled
                        ? "rgba(255, 180, 171, 0.18)"
                        : "rgba(167, 200, 255, 0.18)";
                    const chipBorder = allEnabled
                      ? "rgba(123, 220, 123, 0.35)"
                      : allDisabled
                        ? "rgba(255, 180, 171, 0.35)"
                        : "rgba(167, 200, 255, 0.35)";
                    const chipText = allEnabled
                      ? "var(--m3-secondary)"
                      : allDisabled
                        ? "var(--m3-error)"
                        : "var(--m3-primary)";
                    return (
                      <div className="px-4 pb-3 border-t border-white/5 pt-3">
                        <button
                          type="button"
                          onClick={() => setShowToolsInstanceId(toolsExpanded ? null : inst.id)}
                          className="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors hover:bg-white/5 w-full"
                          aria-expanded={toolsExpanded}
                          aria-controls={`tools-panel-${inst.id}`}
                        >
                          <span
                            className="material-symbols-outlined text-base"
                            style={{ color: chipText }}
                          >
                            tune
                          </span>
                          <span className="text-xs font-headline font-bold text-on-surface">
                            Tools available to agent
                          </span>
                          <span
                            className="text-[11px] font-mono font-bold px-2 py-0.5 rounded-full ml-1"
                            style={{
                              background: chipColor,
                              border: `0.5px solid ${chipBorder}`,
                              color: chipText,
                            }}
                          >
                            {enabledCount}/{total} enabled
                          </span>
                          {disabledCount > 0 && (
                            <span className="text-[10px] text-on-surface-variant/60 italic">
                              · {disabledCount} disabled
                            </span>
                          )}
                          <span className="flex-1" />
                          <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                            {toolsExpanded ? "Hide" : "Configure"}
                          </span>
                          <span className="material-symbols-outlined text-sm text-on-surface-variant">
                            {toolsExpanded ? "expand_less" : "expand_more"}
                          </span>
                        </button>
                        {toolsExpanded && (
                          <div id={`tools-panel-${inst.id}`}>
                            <ToolsTogglePanel
                              instance={inst}
                              tools={connectorForTools.tools}
                              onRefresh={onRefreshData}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })()}
                  </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      {/* Empty state */}
      {instances.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">
            settings_input_component
          </span>
          <h3 className="text-lg font-headline font-semibold text-on-surface/60 mb-1">
            No instances yet
          </h3>
          <p className="text-sm text-on-surface-variant/40 mb-6">
            Create your first connector instance to start integrating.
          </p>
          <button
            type="button"
            onClick={onCreateInstance}
            className="text-white px-6 py-2.5 rounded-xl font-headline font-bold text-sm flex items-center gap-2"
            style={{ background: "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)" }}
          >
            <span className="material-symbols-outlined text-lg">add</span>
            Create Instance
          </button>
        </div>
      )}

      {/* Edit Instance Modal */}
      {editingInstance && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setEditingInstance(null)}
          />
          <div
            className="fixed right-0 top-0 h-full z-50 flex flex-col overflow-hidden"
            style={{
              width: "40%",
              minWidth: "420px",
              maxWidth: "600px",
              background: "var(--glass-bg-elev)",
              backdropFilter: "blur(24px)",
              borderLeft: "0.5px solid var(--glass-border)",
              animation: "slideInRight 0.3s ease-out",
            }}
          >
            <header className="px-6 py-5 flex items-center justify-between border-b border-white/5 shrink-0">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-primary text-2xl">edit</span>
                <h2 className="font-headline text-xl font-bold text-on-surface">Edit Instance</h2>
              </div>
              <button
                type="button"
                onClick={() => setEditingInstance(null)}
                className="p-2 rounded-full hover:bg-surface-variant/40 text-on-surface-variant transition-colors"
                aria-label="Close edit panel"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </header>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
              {editFeedback && (
                <div
                  className={`p-3 rounded-lg text-sm ${
                    editFeedback.type === "success"
                      ? "bg-secondary/10 text-secondary border border-secondary/20"
                      : editFeedback.type === "info"
                        ? "bg-surface-container text-on-surface-variant border border-outline-variant/30"
                        : "bg-error/10 text-error border border-error/20"
                  }`}
                >
                  {editFeedback.message}
                </div>
              )}

              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                  Instance Name
                </label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
                  style={{ border: "0.5px solid var(--glass-border)" }}
                />
              </div>

              <div className="space-y-4">
                <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">Configuration</h3>
                {/* Secret rotation hint — the dialog supports rotation
                    directly: type a new value over the masked "***" and
                    Save. Secrets you don't touch round-trip the redaction
                    sentinel and the backend treats that as "leave that
                    slot alone." */}
                {editSetSecrets.length > 0 && (
                  <div
                    className="flex items-start gap-2 rounded-xl px-3 py-2.5 text-[11px] text-on-surface-variant"
                    style={{
                      background: "rgba(167, 200, 255, 0.06)",
                      border: "0.5px solid rgba(167, 200, 255, 0.18)",
                    }}
                  >
                    <span className="material-symbols-outlined text-[14px] text-primary mt-0.5">info</span>
                    <span>
                      Saved secrets are never shown. To replace one, type the
                      new value over the placeholder and Save. Secrets you
                      don&apos;t edit keep their value.
                    </span>
                  </div>
                )}
                {editParams.length > 0 && (
                  <ConfigFormFields
                    params={editParams}
                    values={editConfig}
                    onChange={(name, value) => setEditConfig((prev) => ({ ...prev, [name]: value }))}
                    connectorName={editConnectorName}
                    setSecrets={editSetSecrets}
                  />
                )}
                {editExtraKeys.map((key) => {
                  const value = editConfig[key] ?? "";
                  const isSecret = isUndeclaredSecret(key, editingInstance.secrets ?? {});
                  const isMasked = isSecret && (value === "****" || value === "***");
                  return (
                    <div key={key} className="space-y-1">
                      <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                        {key}
                        {isSecret && (
                          <span className="ml-2 text-primary/60">
                            <span className="material-symbols-outlined text-xs align-middle">lock</span>
                          </span>
                        )}
                      </label>
                      <input
                        type={isSecret ? "password" : "text"}
                        value={isMasked ? "" : value}
                        placeholder={isMasked ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : undefined}
                        onChange={(e) => setEditConfig((prev) => ({ ...prev, [key]: e.target.value }))}
                        className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
                        style={{ border: "0.5px solid var(--glass-border)" }}
                      />
                    </div>
                  );
                })}
                {editMissing.length > 0 && (
                  <p className="text-[11px] text-error px-1">
                    Fill in {editMissing.map((p) => p.display).join(", ")} to save.
                  </p>
                )}
                {editBadNumbers.length > 0 && (
                  <p className="text-[11px] text-error px-1">
                    {editBadNumbers.map((p) => p.display).join(", ")}{" "}
                    {editBadNumbers.length === 1 ? "must be a number" : "must be numbers"} to save.
                  </p>
                )}
              </div>
            </div>

            {/* Footer-adjacent feedback strip.
                The primary editFeedback banner is at the TOP of the
                scrollable body (line ~2562). When the operator is at
                the bottom of the form (where the Test button lives)
                they never see the banner without scrolling up. This
                duplicate render lives ABOVE the footer so the message
                is always within sight after clicking Test. Same
                editFeedback state drives both — they stay in sync. */}
            {editFeedback && (
              <div
                className={`mx-6 mb-2 p-3 rounded-lg text-sm shrink-0 ${
                  editFeedback.type === "success"
                    ? "bg-secondary/10 text-secondary border border-secondary/20"
                    : editFeedback.type === "info"
                      ? "bg-surface-container text-on-surface-variant border border-outline-variant/30"
                      : "bg-error/10 text-error border border-error/20"
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="material-symbols-outlined text-base mt-0.5">
                    {editFeedback.type === "success" ? "check_circle" : editFeedback.type === "info" ? "info" : "error"}
                  </span>
                  <span className="flex-1">{editFeedback.message}</span>
                  <button
                    type="button"
                    onClick={() => setEditFeedback(null)}
                    aria-label="Dismiss"
                    className="opacity-60 hover:opacity-100"
                  >
                    <span className="material-symbols-outlined text-base">close</span>
                  </button>
                </div>
              </div>
            )}

            <footer className="px-6 py-4 border-t border-white/5 flex items-center justify-between shrink-0">
              <button
                type="button"
                disabled={editTestStatus === "testing"}
                onClick={async () => {
                  // Test Connection inside the edit dialog
                  // sends the CURRENT FORM VALUES as overrides so the
                  // operator can probe candidate config without saving
                  // first. Dry-run mode by default — the probe result
                  // doesn't write to connector_state, so a failed
                  // dry-run doesn't pollute the saved state's history.
                  // The card-level onTestInstance would probe PERSISTED
                  // config (env vars only), ignore everything in the
                  // form, and return "success" even when the operator
                  // broke the URL, so the dialog calls testInstance with
                  // the form values instead.
                  setEditTestStatus("testing");
                  try {
                    const { config: splitConfig, secrets: splitSecrets } = editPayload();
                    const result = await testInstance(editingInstance.id, {
                      config: splitConfig,
                      secrets: splitSecrets,
                      // explicit dry_run=true is also the default when
                      // overrides are present, but spelled out for
                      // operator-facing audit-log clarity
                      dry_run: true,
                    });
                    // Every branch sets feedback. editTestStatus alone is
                    // reflected by the button for 3 seconds then resets to
                    // idle; operators sitting at the bottom of the edit
                    // dialog (where the Test button lives) would otherwise
                    // see the button flash "Failed" or "Connected" and go
                    // back to the neutral "Test Connection" label with no
                    // explanation ("silent failure"). The feedback message also renders
                    // in a footer-adjacent strip (see editFeedbackInline
                    // render below) so the message is visible without
                    // scrolling to the top of the dialog body.
                    if (!result.ok) {
                      setEditTestStatus("error");
                      setEditFeedback({
                        type: "error",
                        message: `Could not reach the test endpoint: ${result.error?.message ?? result.error?.code ?? "unknown error"}`,
                      });
                    } else {
                      // One outcome for the card and the dialog (lib/instance-status.ts).
                      // A pass says what it proved; for the sender connectors that is
                      // reachability only, so it never claims the credentials are valid.
                      const outcome = testOutcome(result.data);
                      if (outcome.kind === "no_test") {
                        setEditTestStatus("idle");
                        setEditFeedback({ type: "info", message: outcome.message });
                      } else if (outcome.kind === "passed") {
                        setEditTestStatus("success");
                        setEditFeedback({
                          type: "success",
                          message: `${outcome.message} (Dry run: nothing was saved. Click Save to persist.)`,
                        });
                      } else {
                        setEditTestStatus("error");
                        setEditFeedback({ type: "error", message: outcome.message });
                      }
                    }
                  } catch (e) {
                    setEditTestStatus("error");
                    setEditFeedback({
                      type: "error",
                      message: `Test threw an exception: ${e instanceof Error ? e.message : String(e)}`,
                    });
                  }
                  setTimeout(() => setEditTestStatus("idle"), 3000);
                }}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-50 ${
                  editTestStatus === "success"
                    ? "text-[#7bdc7b]"
                    : editTestStatus === "error"
                      ? "text-[#ffb4ab]"
                      : "text-primary hover:bg-primary/10"
                }`}
                style={{
                  border: editTestStatus === "success"
                    ? "0.5px solid rgba(123, 220, 123, 0.3)"
                    : editTestStatus === "error"
                      ? "0.5px solid rgba(255, 180, 171, 0.3)"
                      : "0.5px solid rgba(167, 200, 255, 0.2)",
                }}
                title="Test Connection"
              >
                {editTestStatus === "testing" ? (
                  <>
                    <span className="material-symbols-outlined text-lg animate-spin">progress_activity</span>
                    Testing...
                  </>
                ) : editTestStatus === "success" ? (
                  <>
                    <span className="material-symbols-outlined text-lg">check_circle</span>
                    Connected
                  </>
                ) : editTestStatus === "error" ? (
                  <>
                    <span className="material-symbols-outlined text-lg">error</span>
                    Failed
                  </>
                ) : (
                  <>
                    <span className="material-symbols-outlined text-lg">play_circle</span>
                    Test Connection
                  </>
                )}
              </button>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setEditingInstance(null)}
                  className="px-5 py-2.5 rounded-xl text-on-surface-variant font-medium hover:bg-surface-variant/50 transition-all text-sm"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleEditSave}
                  disabled={editSaving || !editName.trim() || editMissing.length > 0 || editBadNumbers.length > 0}
                  className="px-6 py-2.5 rounded-xl font-bold text-sm transition-all disabled:opacity-40"
                  style={{
                    background: "linear-gradient(to right, #1963b3, #2D8DF0)",
                    color: "white",
                  }}
                >
                  {editSaving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </footer>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Create Instance Panel ──────────────────────────────────────────────────

function CreateInstancePanel({ onClose, allConnectors, onCreated }: { onClose: () => void; allConnectors: ConnectorDefinition[]; onCreated: () => void }) {
  const [instanceName, setInstanceName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedConnectorId, setSelectedConnectorId] = useState<string | null>(null);
  const [showConnectorDropdown, setShowConnectorDropdown] = useState(false);
  const [connectorSearch, setConnectorSearch] = useState("");
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  // Per-instance tool selection at create time.
  // Default = empty set = all tools enabled. Operator can untick tools
  // they don't want exposed to the agent for this instance. Resets when
  // the operator switches connectors, since the tool list is connector-
  // specific. Matches the existing-instance ToolsTogglePanel UX so the
  // operator's mental model is the same in both places.
  const [disabledToolsSet, setDisabledToolsSet] = useState<Set<string>>(new Set());
  const [showToolsSection, setShowToolsSection] = useState(true);
  // There is no in-modal Test Connection affordance. The modal
  // closes on successful create; the operator tests from the
  // instance card on /connectors (where the per-instance Test
  // Connection button lives).
  //
  // There is no showAdvanced state: every field renders in one unified
  // Configuration section. Any future "advanced" grouping needs a
  // schema-level flag, not a positional slice.

  const installedConnectors = useMemo(
    () => allConnectors.filter((c) => c.status !== "not_installed"),
    [allConnectors],
  );

  const filteredDropdown = useMemo(() => {
    if (!connectorSearch.trim()) return installedConnectors;
    const q = connectorSearch.toLowerCase();
    return installedConnectors.filter(
      (c) => c.name.toLowerCase().includes(q) || c.category.toLowerCase().includes(q),
    );
  }, [connectorSearch, installedConnectors]);

  const selectedConnector = useMemo(
    () => (selectedConnectorId ? allConnectors.find((c) => c.id === selectedConnectorId) ?? null : null),
    [selectedConnectorId, allConnectors],
  );

  // Seed configValues with each param's defaultValue when the connector
  // changes. Without this, the input fields DISPLAY the default (via
  // `value = configValues[name] ?? param.defaultValue`) but the React
  // state for `configValues` stays {}; allRequiredFilled then thinks
  // every required field is empty even though the user can see the
  // default value in the field, and the Create Instance button stays
  // disabled. The defaults also need to land in `configValues` so the
  // POST body to /api/v1/instances actually carries them — otherwise
  // the MCP rejects with "missing required field cdp_url" even though
  // the UI clearly showed a value.
  //
  // We only seed keys that don't already have a user-typed value, so
  // re-renders from connector list reload don't clobber edits in flight.
  useEffect(() => {
    if (!selectedConnector) return;
    setConfigValues((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const p of selectedConnector.config) {
        if (p.defaultValue !== undefined && next[p.name] === undefined) {
          next[p.name] = String(p.defaultValue);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [selectedConnector]);

  // The form shows the fields whose showWhen rule holds for the current
  // values (ConfigFormFields applies it), and only those can be required.
  // There is no schema signal to drive "advanced" classification; a real
  // Advanced section would need a schema-level flag, not slice positions.

  const allRequiredFilled = useMemo(() => {
    if (!instanceName.trim() || !selectedConnector) return false;
    // A default counts as a value (the form shows it), which also covers any
    // race where the useEffect above hasn't yet seeded configValues.
    return (
      missingRequired(selectedConnector.config, configValues).length === 0 &&
      invalidNumbers(selectedConnector.config, configValues).length === 0
    );
  }, [instanceName, selectedConnector, configValues]);

  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!selectedConnector || !instanceName.trim()) return;
    setSaving(true);
    try {
      // Secrets go to the SecretStore bucket, everything else to config (the
      // schema's param.type decides, not the key name). Only the fields that
      // show are sent; a hidden destination mode's fields never reach the server.
      const { config: configBucket, secrets: secretsBucket } = buildCreatePayload(
        selectedConnector.config,
        configValues,
      );

      const result = await createInstance({
        name: instanceName.trim(),
        connector_id: selectedConnector.id,
        config: configBucket,
        secrets: secretsBucket,
        // Empty array is fine (all tools enabled by default).
        // Backend dedup + string-coerce in InstanceStore.create.
        disabled_tools: Array.from(disabledToolsSet),
      });
      if (result.ok) {
        // Close on success. There is no in-modal Test Connection panel:
        // the connector container is still starting right after create (its
        // image may need pulling), so a test here would report it as
        // unreachable even though the create itself succeeded. Test
        // Connection runs from the instance card on /connectors.
        onCreated();
        onClose();
      }
    } finally {
      setSaving(false);
    }
  }, [selectedConnector, instanceName, configValues, disabledToolsSet, onCreated, onClose]);

  const handleConfigChange = useCallback((name: string, value: string) => {
    setConfigValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  // Blue bar section heading matching the HTML design
  function PanelSection({ title }: { title: string }) {
    return (
      <div className="flex items-center gap-2">
        <div className="w-1 h-4 bg-primary rounded-full" />
        <h2 className="font-headline font-semibold text-lg text-on-surface">{title}</h2>
      </div>
    );
  }


  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 backdrop-blur-sm"
        style={{ background: "rgba(18, 18, 30, 0.6)" }}
        onClick={onClose}
      />

      {/* Slide-over panel */}
      <div
        className="fixed right-0 top-0 h-full z-50 flex flex-col shadow-[0px_0px_60px_rgba(25,99,179,0.2)]"
        style={{
          width: "55%",
          minWidth: "540px",
          maxWidth: "800px",
          animation: "slideInRight 0.3s ease-out",
          background: "var(--glass-bg-strong)",
          borderLeft: "0.5px solid var(--glass-border)",
          backdropFilter: "blur(12px)",
        }}
      >
        {/* ── Header ──────────────────────────────────────────── */}
        <div className="flex items-start justify-between px-8 pt-8 pb-6">
          <div>
            <h2 className="text-3xl font-headline font-bold tracking-tight text-on-surface">
              Create Instance
            </h2>
            <p className="text-sm text-on-surface-variant mt-1">
              Configure a new connection to an external service
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full hover:bg-surface-variant/40 text-on-surface-variant transition-colors"
            aria-label="Close panel"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* ── Scrollable body ─────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto custom-scrollbar px-8 pb-32 space-y-10">
          {/* Instance Identity */}
          <section className="space-y-6">
            <PanelSection title="Instance Identity" />
            <div className="grid gap-6">
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                  Instance Name
                </label>
                <input
                  type="text"
                  value={instanceName}
                  onChange={(e) => setInstanceName(e.target.value)}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
                  style={{ border: "0.5px solid var(--glass-border)" }}
                  placeholder="e.g., Marketing-Gmail-Sync"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline resize-none"
                  style={{ border: "0.5px solid var(--glass-border)" }}
                  placeholder="Briefly describe the purpose of this connection..."
                />
              </div>
            </div>
          </section>

          {/* Connector Selector */}
          <section className="space-y-6">
            <PanelSection title="Connector Selector" />
            <div className="space-y-4">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowConnectorDropdown(!showConnectorDropdown)}
                  className="w-full flex items-center justify-between appearance-none rounded-xl px-4 py-3 pr-10 text-sm transition-all text-left"
                  style={{
                    background: "rgba(52, 51, 64, 1)",
                    border: "0.5px solid var(--glass-border)",
                  }}
                >
                  {selectedConnector ? (
                    <div className="flex items-center gap-3">
                      <div
                        className="w-6 h-6 rounded-md flex items-center justify-center"
                        style={{ background: selectedConnector.iconBg }}
                      >
                        <span className="material-symbols-outlined text-sm" style={{ color: selectedConnector.iconColor }}>
                          {selectedConnector.icon}
                        </span>
                      </div>
                      <span className="text-on-surface font-medium">{selectedConnector.name}</span>
                    </div>
                  ) : (
                    <span className="text-outline">Choose an installed connector…</span>
                  )}
                  <span className="material-symbols-outlined absolute right-3 top-3.5 pointer-events-none text-on-surface-variant">
                    expand_more
                  </span>
                </button>

                {showConnectorDropdown && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setShowConnectorDropdown(false)} />
                    <div
                      className="absolute left-0 right-0 top-full mt-1 rounded-xl z-20 max-h-64 overflow-y-auto custom-scrollbar"
                      style={{
                        background: "var(--m3-surface-container)",
                        border: "0.5px solid var(--glass-border)",
                        backdropFilter: "blur(20px)",
                      }}
                    >
                      <div className="p-2 border-b border-white/5">
                        <input
                          type="text"
                          value={connectorSearch}
                          onChange={(e) => setConnectorSearch(e.target.value)}
                          className="w-full bg-surface-container-highest border-none rounded-lg px-3 py-2 text-xs focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
                          placeholder="Search connectors…"
                          autoFocus
                        />
                      </div>
                      <div className="p-1">
                        {filteredDropdown.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => {
                              setSelectedConnectorId(c.id);
                              setShowConnectorDropdown(false);
                              setConnectorSearch("");
                              setConfigValues({});
                              // Reset tool selection when the operator
                              // switches connector. Each connector ships its own
                              // tool list; carrying over a Set keyed by the
                              // previous connector's names would silently disable
                              // nothing on the new one.
                              setDisabledToolsSet(new Set());
                            }}
                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-left ${
                              selectedConnectorId === c.id
                                ? "bg-primary/10 text-primary"
                                : "text-on-surface hover:bg-white/5"
                            }`}
                          >
                            <div
                              className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                              style={{ background: c.iconBg }}
                            >
                              <span className="material-symbols-outlined text-sm" style={{ color: c.iconColor }}>
                                {c.icon}
                              </span>
                            </div>
                            <span className="flex-1">{c.name}</span>
                            <span
                              className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full text-on-surface-variant/60"
                              style={{ background: "rgba(52, 51, 64, 0.6)" }}
                            >
                              {c.category}
                            </span>
                          </button>
                        ))}
                        {filteredDropdown.length === 0 && (
                          <p className="px-3 py-4 text-xs text-on-surface-variant/40 text-center">No connectors match your search</p>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Selected connector info card */}
              {selectedConnector && (
                <div
                  className="flex items-center gap-4 p-4 rounded-xl"
                  style={{ background: "var(--glass-bg)", border: "0.5px solid var(--glass-border)" }}
                >
                  <div
                    className="w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: selectedConnector.iconBg }}
                  >
                    <span className="material-symbols-outlined text-2xl" style={{ color: selectedConnector.iconColor }}>
                      {selectedConnector.icon}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-bold text-on-surface">{selectedConnector.name}</span>
                      <span
                        className="text-[10px] px-2 py-0.5 rounded-full font-label text-primary"
                        style={{ background: "rgba(167, 200, 255, 0.2)" }}
                      >
                        {selectedConnector.version}
                      </span>
                    </div>
                    <p className="text-xs text-on-surface-variant mt-0.5 truncate">{selectedConnector.description}</p>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Dynamic Configuration Form */}
          {/* One unified Configuration section: every field that shows
              renders in declaration order (no positional "advanced" split,
              which would hide required fields such as cortex-xdr's api_id).
              The widgets, the footnotes and the showWhen rule live in
              components/connector-config-form.tsx, shared with Edit. */}
          {selectedConnector && (
            <section className="space-y-6">
              <PanelSection title="Configuration" />

              <ConfigFormFields
                params={selectedConnector.config}
                values={configValues}
                onChange={handleConfigChange}
                connectorName={selectedConnector.name}
              />
            </section>
          )}

          {/* Tools selection. The operator picks
              which tools the agent can call on THIS instance from the
              moment it's created. Default: all tools enabled. The list
              comes from the connector's spec.tools[] (loaded live via
              /api/marketplace/connectors) so it always matches what the
              instance will actually advertise. Symmetry with the
              existing ToolsTogglePanel on the instance row (same model,
              same affordances), so the operator builds the right
              mental model in both places. */}
          {selectedConnector && selectedConnector.tools.length > 0 && (
            <section className="space-y-4">
              <button
                type="button"
                onClick={() => setShowToolsSection((s) => !s)}
                className="w-full flex items-center gap-3 group"
                aria-expanded={showToolsSection}
                aria-controls="create-tools-section"
              >
                <div className="w-1 h-4 bg-primary rounded-full" />
                <h2 className="font-headline font-semibold text-lg text-on-surface">
                  Tools available to agent
                </h2>
                <span
                  className="text-[11px] font-mono font-bold px-2 py-0.5 rounded-full"
                  style={{
                    background: "rgba(167, 200, 255, 0.18)",
                    border: "0.5px solid rgba(167, 200, 255, 0.35)",
                    color: "var(--m3-primary)",
                  }}
                >
                  {selectedConnector.tools.length - disabledToolsSet.size}/
                  {selectedConnector.tools.length} enabled
                </span>
                <span className="flex-1" />
                <span className="material-symbols-outlined text-base text-on-surface-variant group-hover:text-primary transition-colors">
                  {showToolsSection ? "expand_less" : "expand_more"}
                </span>
              </button>

              {showToolsSection && (
                <div id="create-tools-section" className="space-y-3">
                  <p className="text-[11px] text-on-surface-variant px-1 leading-relaxed">
                    Uncheck any tool the agent should NOT be able to
                    call on this instance. You can change this any time
                    from the instance row.
                  </p>

                  {/* Mass actions */}
                  <div className="flex items-center gap-3 px-1">
                    <button
                      type="button"
                      onClick={() => setDisabledToolsSet(new Set())}
                      disabled={disabledToolsSet.size === 0}
                      className="text-[11px] font-mono uppercase tracking-wider text-primary/70 hover:text-primary disabled:opacity-30 transition-colors"
                    >
                      Enable all
                    </button>
                    <span className="text-on-surface-variant/30">·</span>
                    <button
                      type="button"
                      onClick={() =>
                        setDisabledToolsSet(
                          new Set(selectedConnector.tools.map((t) => t.name)),
                        )
                      }
                      disabled={
                        disabledToolsSet.size === selectedConnector.tools.length
                      }
                      className="text-[11px] font-mono uppercase tracking-wider text-on-surface-variant/70 hover:text-error disabled:opacity-30 transition-colors"
                    >
                      Disable all
                    </button>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    {selectedConnector.tools.map((tool) => {
                      const isDisabled = disabledToolsSet.has(tool.name);
                      return (
                        <label
                          key={tool.name}
                          className="p-3 rounded-xl flex items-start gap-3 cursor-pointer transition-colors"
                          style={{
                            background: isDisabled
                              ? "rgba(52, 51, 64, 0.2)"
                              : "rgba(52, 51, 64, 0.4)",
                            border: isDisabled
                              ? "0.5px solid rgba(140, 145, 157, 0.05)"
                              : "0.5px solid rgba(140, 145, 157, 0.12)",
                            opacity: isDisabled ? 0.55 : 1,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={!isDisabled}
                            onChange={() => {
                              setDisabledToolsSet((prev) => {
                                const next = new Set(prev);
                                if (next.has(tool.name)) next.delete(tool.name);
                                else next.add(tool.name);
                                return next;
                              });
                            }}
                            className="mt-1 cursor-pointer"
                            aria-label={`${isDisabled ? "Enable" : "Disable"} tool ${tool.name}`}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span
                                className={`text-[9px] font-bold px-1.5 py-0.5 rounded font-mono ${
                                  tool.method === "GET"
                                    ? "bg-primary/20 text-primary"
                                    : tool.method === "POST"
                                      ? "bg-secondary/20 text-secondary"
                                      : tool.method === "PUT"
                                        ? "bg-tertiary/20 text-tertiary"
                                        : tool.method === "DELETE"
                                          ? "bg-error/20 text-error"
                                          : "bg-primary/20 text-primary"
                                }`}
                              >
                                {tool.method}
                              </span>
                              <span className="font-mono text-[11px] text-on-surface truncate">
                                {tool.name}
                              </span>
                            </div>
                            {tool.description && (
                              <p className="text-[10px] text-on-surface-variant/60 line-clamp-2 mt-1">
                                {tool.description}
                              </p>
                            )}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Workspace Assignment removed for phantom standalone — single
              tenant, no workspace concept. The per-instance config panel
              above is now the only place credentials live. */}

          {/* Test Connection lives on the per-instance card, not in
              the modal. The modal closes immediately on successful
              Create Instance; the operator clicks the per-instance Test
              Connection button on /connectors after the new instance
              card renders. This avoids a dual-action flow and a
              misleading "unreachable" result while the new connector
              container is still starting. */}
        </div>

        {/* ── Sticky Footer ───────────────────────────────────── */}
        <div
          className="absolute bottom-0 left-0 right-0 px-8 py-6 flex items-center justify-between"
          style={{
            background: "var(--glass-bg-strong)",
            backdropFilter: "blur(12px)",
            borderTop: "0.5px solid var(--glass-border)",
          }}
        >
          <div className="flex items-center gap-2 text-on-surface-variant">
            <span className="material-symbols-outlined text-xl">info</span>
            <span className="text-xs">Platform instance</span>
          </div>
          <div className="flex gap-4">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 rounded-xl text-on-surface font-medium hover:bg-surface-variant/50 transition-all"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!allRequiredFilled || saving}
              onClick={handleSave}
              className="px-8 py-3 rounded-xl font-headline font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: allRequiredFilled
                  ? "linear-gradient(to right, #1963b3, #2D8DF0)"
                  : "rgba(52, 51, 64, 0.6)",
                color: allRequiredFilled ? "white" : "rgba(255, 255, 255, 0.3)",
                boxShadow: allRequiredFilled
                  ? "0px 0px 20px rgba(25, 99, 179, 0.3)"
                  : "none",
              }}
            >
              Create Instance
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ─── Workspace Access Tab ───────────────────────────────────────────────────

function WorkspaceAccessTab({ onUninstall }: { onUninstall: (connectorId: string) => void }) {
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const totalWorkspaces = WORKSPACE_ACCESS.length;
  const uniqueConnectors = new Set(WORKSPACE_ACCESS.flatMap((ws) => ws.connectors.map((c) => c.name)));
  const fullAccessCount = WORKSPACE_ACCESS.filter((ws) => ws.accessLevel === "full").length;

  function accessBadge(level: AccessLevel) {
    switch (level) {
      case "full":
        return (
          <span
            className="text-secondary text-[10px] px-2 py-0.5 rounded uppercase font-bold tracking-wider"
            style={{ background: "rgba(3, 115, 33, 0.1)", border: "0.5px solid rgba(123, 220, 123, 0.2)" }}
          >
            Full Access
          </span>
        );
      case "selective":
        return (
          <span
            className="text-primary text-[10px] px-2 py-0.5 rounded uppercase font-bold tracking-wider"
            style={{ background: "rgba(167, 200, 255, 0.1)", border: "0.5px solid rgba(167, 200, 255, 0.2)" }}
          >
            Selective
          </span>
        );
      case "none":
        return (
          <span
            className="text-on-surface-variant text-[10px] px-2 py-0.5 rounded uppercase font-bold tracking-wider"
            style={{ background: "rgba(52, 51, 64, 0.6)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
          >
            No Access
          </span>
        );
    }
  }

  function borderColor(level: AccessLevel): string {
    return level === "full" ? "#7bdc7b" : level === "selective" ? "#a7c8ff" : "#424751";
  }

  function avatarStyle(level: AccessLevel) {
    return level === "full"
      ? { background: "rgba(3, 115, 33, 0.2)", color: "#7bdc7b", border: "0.5px solid rgba(123, 220, 123, 0.2)" }
      : { background: "rgba(25, 99, 179, 0.2)", color: "#a7c8ff", border: "0.5px solid rgba(167, 200, 255, 0.2)" };
  }

  return (
    <div className="rounded-3xl p-8 relative overflow-hidden shadow-[0px_40px_80px_rgba(0,0,0,0.5)]" style={{ background: "var(--m3-surface-container-low)" }}>
      {/* Decorative glow */}
      <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 blur-[60px] rounded-full -translate-y-1/2 translate-x-1/2 pointer-events-none" />

      {/* Header */}
      <div className="flex justify-between items-start mb-10 relative z-10">
        <div>
          <h1 className="font-headline text-3xl font-bold text-on-surface tracking-tight">
            Connector Access by Workspace
          </h1>
          <p className="text-on-surface-variant/70 mt-1 max-w-xl">
            Configure and audit which organizational departments have authorization to utilize installed integration connectors.
          </p>
        </div>
        <button
          type="button"
          className="text-on-surface font-bold py-3 px-8 rounded-xl flex items-center gap-2 transition-all hover:shadow-[0px_0px_30px_rgba(25,99,179,0.3)]"
          style={{ background: "linear-gradient(to right, #1963B3, #2D8DF0)" }}
        >
          <span className="material-symbols-outlined text-xl">admin_panel_settings</span>
          Manage Access
        </button>
      </div>

      {/* Summary strip — bento cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10 relative z-10">
        <div
          className="p-6 rounded-2xl flex flex-col justify-between hover:bg-surface-container transition-colors"
          style={{ background: "var(--glass-bg)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
        >
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-4">Total Workspaces</span>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-headline font-bold text-on-surface">{totalWorkspaces}</span>
            <span className="text-primary/60 text-sm">Active Depts</span>
          </div>
        </div>
        <div
          className="p-6 rounded-2xl flex flex-col justify-between hover:bg-surface-container transition-colors"
          style={{ background: "var(--glass-bg)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
        >
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-4">Connectors Shared</span>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-headline font-bold text-on-surface">{uniqueConnectors.size}</span>
            <span className="text-secondary/60 text-sm">Validated</span>
          </div>
        </div>
        <div
          className="p-6 rounded-2xl flex flex-col justify-between hover:bg-surface-container transition-colors"
          style={{ background: "var(--glass-bg)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
        >
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-4">Full Access</span>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-headline font-bold text-on-surface">{fullAccessCount}</span>
            <span className="text-tertiary/60 text-sm">Administrator</span>
          </div>
        </div>
      </div>

      {/* Workspace access card-rows */}
      <div className="space-y-4 relative z-10">
        {WORKSPACE_ACCESS.map((ws) => (
          <div
            key={ws.id}
            className="relative p-5 rounded-2xl flex items-center justify-between group hover:bg-surface-container-high transition-all"
            style={{
              background: "var(--m3-surface-container)",
              borderLeft: `4px solid ${borderColor(ws.accessLevel)}`,
            }}
          >
            {/* Clickable area — navigates to workspace */}
            <Link
              href={`/w/${ws.slug}`}
              className="flex items-center gap-5 flex-1 min-w-0 cursor-pointer"
            >
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center font-bold text-xl font-headline shrink-0"
                style={{
                  ...avatarStyle(ws.accessLevel),
                  boxShadow: ws.accessLevel === "full"
                    ? "0 0 15px rgba(3, 115, 33, 0.1)"
                    : "none",
                }}
              >
                {ws.initial}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-bold text-on-surface">{ws.name}</h3>
                  {accessBadge(ws.accessLevel)}
                </div>
                <p className="text-on-surface-variant text-sm mt-0.5">
                  {ws.members} members · {ws.accessLevel === "full" ? "Full access granted" : "Selective access limited"}
                </p>
              </div>
            </Link>

            {/* Right side: connector chips + menu (NOT inside the Link) */}
            <div className="flex items-center gap-4 shrink-0 ml-4">
              <div className="flex gap-2">
                {ws.connectors.map((chip) => (
                  <div
                    key={chip.name}
                    className="px-3 py-1.5 rounded-lg flex items-center gap-2 text-xs text-on-surface-variant"
                    style={{ background: "var(--glass-bg)", border: "0.5px solid rgba(255, 255, 255, 0.05)" }}
                  >
                    <span className="material-symbols-outlined text-sm" style={{ color: chip.iconColor }}>
                      {chip.icon}
                    </span>
                    {chip.name}
                  </div>
                ))}
              </div>
              <div className="relative">
                <button
                  type="button"
                  className="w-8 h-8 flex items-center justify-center rounded-lg text-outline hover:text-primary hover:bg-white/5 transition-colors"
                  aria-label={`More options for ${ws.name}`}
                  onClick={() => setMenuOpen(menuOpen === ws.id ? null : ws.id)}
                >
                  <span className="material-symbols-outlined text-xl">more_vert</span>
                </button>
                {menuOpen === ws.id && (
                  <div
                    className="absolute right-0 top-full mt-1 w-52 rounded-xl py-1.5 shadow-2xl z-50"
                    style={{ background: "rgba(40, 39, 55, 1)", border: "1px solid rgba(255, 255, 255, 0.12)", backdropFilter: "none" }}
                  >
                    <button
                      type="button"
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-on-surface/80 hover:bg-white/5 transition-colors"
                      onClick={() => setMenuOpen(null)}
                    >
                      <span className="material-symbols-outlined text-base">cable</span>
                      Assign to Workspace
                    </button>
                    <button
                      type="button"
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-on-surface/80 hover:bg-white/5 transition-colors"
                      onClick={() => setMenuOpen(null)}
                    >
                      <span className="material-symbols-outlined text-base">description</span>
                      View Documentation
                    </button>
                    <button
                      type="button"
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-on-surface/80 hover:bg-white/5 transition-colors"
                      onClick={() => setMenuOpen(null)}
                    >
                      <span className="material-symbols-outlined text-base">settings</span>
                      Configure Instance
                    </button>
                    <div className="my-1 border-t border-white/5" />
                    <button
                      type="button"
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-error/80 hover:bg-white/5 transition-colors"
                      onClick={() => {
                        setMenuOpen(null);
                        const connectorName = ws.connectors[0]?.name;
                        if (connectorName) onUninstall(connectorName);
                      }}
                    >
                      <span className="material-symbols-outlined text-base">delete</span>
                      Uninstall
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Legend footer */}
      <footer className="mt-10 pt-6 border-t border-white/5 flex items-center justify-between relative z-10">
        <div className="flex items-center gap-8">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-secondary" style={{ boxShadow: "0 0 8px rgba(123, 220, 123, 0.5)" }} />
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant">Full Department Permission</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-primary" style={{ boxShadow: "0 0 8px rgba(167, 200, 255, 0.5)" }} />
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant">Restricted Role Access</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-on-surface-variant">
          <span className="material-symbols-outlined text-sm">info</span>
          <span>Last audited: Today at 09:42 AM</span>
        </div>
      </footer>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ConnectorsPage() {
  const [activeTab, setActiveTab] = useState<TabId>("marketplace");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<Category>("All");
  const [typeFilter, setTypeFilter] = useState<ConnectorType>("all");
  const [sdkFilter, setSdkFilter] = useState<SdkLanguage>("all");
  const [sortBy, setSortBy] = useState<SortOption>("popularity");
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const [selectedConnector, setSelectedConnector] = useState<ConnectorDefinition | null>(null);
  const [showUploadPanel, setShowUploadPanel] = useState(false);
  const [showCreateInstance, setShowCreateInstance] = useState(false);
  const [connectors, setConnectors] = useState<ConnectorDefinition[]>([]);
  const [instances, setInstances] = useState<InstanceDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [wsFilterOpen, setWsFilterOpen] = useState(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>("all");

  const refreshData = useCallback(async () => {
    const [marketplaceData, installedData, instancesData] = await Promise.allSettled([
      listMarketplaceConnectors(),
      listInstalledConnectors(),
      listInstances(),
    ]);

    const marketplace =
      marketplaceData.status === "fulfilled" ? marketplaceData.value : [];
    const installed =
      installedData.status === "fulfilled" && installedData.value.ok
        ? installedData.value.data
        : [];
    const installedArray = Array.isArray(installed) ? installed : [];
    const installedMap = new Map(
      installedArray.map((i: { connector_id: string; version: string }) => [i.connector_id, i.version]),
    );

    // Pull instances data first so we can use it as a secondary
    // signal for "installed" status. Operator caught a bug where the
    // /marketplace/installed endpoint was missing connectors that
    // clearly had running instances. Source-of-truth fallback: if
    // at least one instance exists for a connector, it must be
    // installed — even if the installed-connectors API doesn't
    // list it. This makes the UI robust to backend inconsistencies.
    const rawInstances =
      instancesData.status === "fulfilled" && instancesData.value.ok
        ? instancesData.value.data
        : [];
    const instancesArr = Array.isArray(rawInstances) ? rawInstances : [];
    const connectorIdsWithInstances = new Set(
      instancesArr.map((i: { connector_id: string }) => i.connector_id),
    );

    const mappedConnectors = marketplace.map((mc) => {
      const def = mapToConnectorDef(mc);
      const installedVersion = installedMap.get(mc.id);
      const hasInstance = connectorIdsWithInstances.has(mc.id);

      // Not in installedMap AND no instances → genuinely not installed.
      if (!installedVersion && !hasInstance) {
        return { ...def, status: "not_installed" as const };
      }
      // The "bundled" sentinel comes from the agent's marketplace/installed
      // proxy — bundle-shipped connectors don't carry a separate install
      // version (they ARE whatever the bundle says they are). Treat it
      // as "matches whatever marketplace reports" so we never falsely
      // flag a bundled connector as having an update.
      const isBundledSentinel = installedVersion === "bundled";

      // Version comparison — if installed version differs from marketplace, show update available
      if (
        installedVersion &&
        !isBundledSentinel &&
        installedVersion !== mc.version
      ) {
        return {
          ...def,
          status: "update_available" as const,
          version: installedVersion,
          latestVersion: mc.version,
        };
      }
      // Either installedMap says yes, or instances exist (fallback).
      return { ...def, status: "installed" as const };
    });

    setConnectors(mappedConnectors);

    // Map instances using the connectors we just built
    setInstances(
      instancesArr.map((ri) => mapApiInstance(ri, mappedConnectors)),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refreshData();
      } catch {
        // keep empty on error
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [refreshData]);

  // ── Action handlers ──────────────────────────────────────────────────
  // pendingActions tracks which connector(s) currently have an
  // install/uninstall API call in flight. The detail panel reads this
  // to render a spinner + disabled state on the action button so the
  // operator sees the click registered. Map keyed by connector_id so
  // future bulk actions (install multiple) just compose naturally.
  const [pendingActions, setPendingActions] = useState<
    Record<string, "install" | "uninstall" | "delete">
  >({});
  const addToast = useNotificationsStore((s) => s.addToast);

  const handleInstall = useCallback(
    async (connectorId: string, version: string) => {
      setPendingActions((prev) => ({ ...prev, [connectorId]: "install" }));
      try {
        const result = await installConnector(connectorId, version);
        if (result.ok) {
          setConnectors((prev) =>
            prev.map((c) =>
              c.id === connectorId ? { ...c, status: "installed" as const } : c,
            ),
          );
          // Refresh in case the backend auto-provisions an instance.
          await refreshData();
          addToast({
            variant: "success",
            title: `${connectorId} installed`,
            description: "Open the Instances tab to create an instance.",
          });
        } else {
          addToast({
            variant: "error",
            title: `Could not install ${connectorId}`,
            description: result.error.message,
          });
        }
      } finally {
        setPendingActions((prev) => {
          const { [connectorId]: _, ...rest } = prev;
          return rest;
        });
      }
    },
    [refreshData, addToast],
  );

  const handleUninstall = useCallback(
    async (connectorId: string) => {
      setPendingActions((prev) => ({ ...prev, [connectorId]: "uninstall" }));
      try {
        const result = await uninstallConnector(connectorId);
        if (result.ok) {
          setConnectors((prev) =>
            prev.map((c) =>
              c.id === connectorId
                ? { ...c, status: "not_installed" as const }
                : c,
            ),
          );
          await refreshData();
          addToast({
            variant: "success",
            title: `${connectorId} uninstalled`,
          });
        } else {
          // 409 case: agent refused because instances exist. The error
          // message from the backend already says "delete N instances
          // first via the Instances tab" — surface it as-is so the
          // operator knows exactly what to do next. parseError in
          // lib/api/client.ts now extracts our {error: "..."}
          // envelope into the message field.
          addToast({
            variant: "error",
            title: `Could not uninstall ${connectorId}`,
            description: result.error.message,
          });
        }
      } finally {
        setPendingActions((prev) => {
          const { [connectorId]: _, ...rest } = prev;
          return rest;
        });
      }
    },
    [refreshData, addToast],
  );

  // Delete an uploaded connector (origin "user"): removes its install marker
  // and its connector.yaml. The MCP refuses while instances exist (409), and
  // its message says how many; surface it as-is.
  const handleDelete = useCallback(
    async (connectorId: string) => {
      const accepted = await confirmAction({
        title: `Delete ${connectorId}?`,
        message:
          "This removes the uploaded connector from the marketplace. Upload its connector.yaml again to bring it back. A connector that still has instances cannot be deleted.",
        confirmLabel: "Delete connector",
        tone: "danger",
      });
      if (!accepted) return;
      setPendingActions((prev) => ({ ...prev, [connectorId]: "delete" }));
      try {
        const result = await deleteUploadedConnector(connectorId);
        if (result.ok) {
          setSelectedConnector(null);
          await refreshData();
          addToast({ variant: "success", title: `${connectorId} deleted` });
        } else {
          addToast({
            variant: "error",
            title: `Could not delete ${connectorId}`,
            description: result.error.message,
          });
        }
      } finally {
        setPendingActions((prev) => {
          const { [connectorId]: _, ...rest } = prev;
          return rest;
        });
      }
    },
    [refreshData, addToast],
  );

  const handleTestInstance = useCallback(
    async (instanceId: string): Promise<TestOutcome | null> => {
      // Backend response is {instance, probe_implemented, ok, error,
      // is_auth_error, message, connector_state}. The test endpoint already
      // wrote connector_state server-side (record_success / record_failure),
      // so the badge follows the outcome without a refetch.
      const result = await testInstance(instanceId);
      if (!result.ok) {
        addToast({
          variant: "error",
          title: "Could not run the test",
          description: result.error?.message ?? result.error?.code ?? "The test endpoint did not answer.",
        });
        return null;
      }

      const outcome = testOutcome(result.data);
      const cs = result.data.connector_state;
      addToast({
        variant: outcome.kind === "passed" ? "success" : outcome.kind === "failed" ? "error" : "info",
        title: outcome.kind === "passed" ? "Connection test passed" : outcome.kind === "failed" ? "Connection test failed" : "No built-in test",
        description: outcome.message,
      });
      setInstances((prev) =>
        prev.map((inst) =>
          inst.id === instanceId
            ? {
                ...inst,
                status: outcome.status,
                connState: cs?.state ?? inst.connState,
                lastError: outcome.kind === "failed" ? (result.data.error ?? null) : outcome.kind === "passed" ? null : inst.lastError,
                enabled: cs ? cs.state !== "disabled" : inst.enabled,
              }
            : inst,
        ),
      );
      return outcome;
    },
    [addToast],
  );

  // Phantom is single-tenant standalone — there are no workspaces to
  // assign connectors to. The Workspaces tab from Spark is dropped;
  // the Workspace Assignment panel inside an instance's detail view is
  // also dropped (see PanelSection below).
  const TABS: { id: TabId; label: string; count: number }[] = [
    { id: "marketplace", label: "Marketplace", count: connectors.length },
    { id: "instances", label: "Instances", count: instances.length },
  ];

  const sortLabel = sortBy === "popularity" ? "Popularity" : sortBy === "recent" ? "Recent" : "A–Z";

  // Filter and sort connectors
  const filteredConnectors = useMemo(() => {
    let result = [...connectors];

    // Search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          c.description.toLowerCase().includes(q) ||
          c.publisher.toLowerCase().includes(q) ||
          c.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }

    // Category
    if (activeCategory !== "All") {
      result = result.filter((c) => c.category === activeCategory);
    }

    // Type filter
    if (typeFilter !== "all") {
      result = result.filter((c) => {
        const ct = c.type.toLowerCase();
        const ft = typeFilter.replace(/s$/, ""); // "channels" -> "channel"
        return ct === ft || ct === typeFilter;
      });
    }

    // SDK language filter
    if (sdkFilter !== "all") {
      result = result.filter((c) => {
        const lang = (c.sdkLanguage || c.runtime || "").toLowerCase();
        return lang.includes(sdkFilter);
      });
    }

    // Sort
    switch (sortBy) {
      case "popularity":
        result.sort((a, b) => b.installCount - a.installCount);
        break;
      case "recent":
        // For now, keep original order (newest first)
        break;
      case "alphabetical":
        result.sort((a, b) => a.name.localeCompare(b.name));
        break;
    }

    return result;
  }, [connectors, searchQuery, activeCategory, typeFilter, sdkFilter, sortBy]);

  const handleSelectConnector = useCallback((c: ConnectorDefinition) => {
    setSelectedConnector(c);
  }, []);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8">
        {/* ── Header ──────────────────────────────────────────────────── */}
        {/* Page Header — jobs-style. Drops the colored icon-box for
            a flat icon-in-primary, matching the rest of the app. */}
        <div className="flex items-start justify-between gap-4 flex-wrap mb-8">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                cable
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Connectors
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Discover and manage data gateways for your AI agents.
            </p>
          </div>

          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setShowUploadPanel(true)}
              className="text-white px-6 py-3 rounded-xl font-semibold flex items-center gap-2 transition-all hover:shadow-[0_0_20px_rgba(25,99,179,0.3)]"
              style={{
                background: "linear-gradient(to right, #1963B3, #2D8DF0)",
              }}
            >
              <span className="material-symbols-outlined">upload</span>
              Upload Connector
            </button>
          </div>
        </div>

        {/* ── Tab Bar + Filters ────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
          {/* Tabs */}
          <div
            className="flex items-center p-1 rounded-xl"
            style={{ background: "var(--m3-surface-container-low)" }}
          >
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                // Active state aligned with the rest of the app's
                // active-affordance: secondary-container green tint
                // with text-secondary, mirroring the sidebar's active
                // link. Replaces the previous hardcoded
                // rgba(52, 51, 64, 1) which was a near-black surface
                // — fine on dark theme but unreadable on the
                // pale-azure light bg (op: "dark bg when clicked").
                className={`px-5 py-2 rounded-lg font-semibold text-sm flex items-center gap-2 transition-all ${
                  activeTab === tab.id
                    ? "bg-secondary-container/30 text-secondary"
                    : "text-on-surface-variant hover:text-on-surface"
                }`}
              >
                {tab.label}
                {tab.count > 0 && (
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      activeTab === tab.id
                        ? "bg-secondary/20 text-secondary"
                        : "bg-white/5 text-on-surface-variant/50"
                    }`}
                  >
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Sort */}
          <div className="flex items-center gap-3">
            {/* Sort dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSortDropdown(!showSortDropdown)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-on-surface transition-colors"
                style={{
                  background: "var(--m3-surface-container)",
                  border: "0.5px solid rgba(255, 255, 255, 0.05)",
                }}
              >
                <span className="material-symbols-outlined text-sm">sort</span>
                {sortLabel}
              </button>

              {showSortDropdown && (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setShowSortDropdown(false)}
                  />
                  <div
                    className="absolute right-0 top-full mt-1 rounded-xl p-1 z-20 min-w-[160px]"
                    style={{
                      ...glassStyle,
                      background: "var(--m3-surface-container)",
                      backdropFilter: "blur(20px)",
                    }}
                  >
                    {(
                      [
                        ["popularity", "Popularity"],
                        ["recent", "Recently Updated"],
                        ["alphabetical", "Alphabetical"],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => {
                          setSortBy(value);
                          setShowSortDropdown(false);
                        }}
                        className={`w-full text-left px-3 py-2 rounded-lg text-xs font-label transition-colors ${
                          sortBy === value
                            ? "text-primary bg-primary/10"
                            : "text-on-surface-variant hover:text-on-surface hover:bg-white/5"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* ── Type + SDK Filters ──────────────────── */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          {/* Type filter pills */}
          <div className="flex gap-2">
            {TYPE_FILTERS.map((tf) => (
              <button
                key={tf.value}
                type="button"
                onClick={() => setTypeFilter(tf.value)}
                className={`py-1 px-3 rounded-full text-xs font-label uppercase tracking-widest transition-colors ${
                  typeFilter === tf.value
                    ? "text-primary"
                    : "text-on-surface-variant hover:bg-surface-container"
                }`}
                style={
                  typeFilter === tf.value
                    ? {
                        background: "var(--m3-surface-container)",
                        border: "0.5px solid rgba(167, 200, 255, 0.3)",
                      }
                    : undefined
                }
              >
                {tf.label}
              </button>
            ))}
          </div>

          <div className="h-4 w-px bg-white/10" />

          {/* SDK language pills */}
          <div className="flex gap-2 items-center">
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/50 font-label mr-1">SDK</span>
            {SDK_FILTERS.map((sf) => (
              <button
                key={sf.value}
                type="button"
                onClick={() => setSdkFilter(sf.value)}
                className={`py-1 px-3 rounded-full text-xs font-label uppercase tracking-widest transition-colors ${
                  sdkFilter === sf.value
                    ? "text-primary"
                    : "text-on-surface-variant hover:bg-surface-container"
                }`}
                style={
                  sdkFilter === sf.value
                    ? {
                        background: "var(--m3-surface-container)",
                        border: "0.5px solid rgba(167, 200, 255, 0.3)",
                      }
                    : undefined
                }
              >
                {sf.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Search Bar ──────────────────────────────────────────── */}
        <div className="relative mb-6">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-lg">
            search
          </span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-surface-container-highest border-none rounded-xl pl-10 pr-4 py-2.5 text-sm focus:ring-1 focus:ring-primary-container transition-all outline-none text-on-surface placeholder:text-on-surface-variant/50"
            placeholder="Search connectors by name, description, or publisher..."
          />
        </div>

        {/* ── Marketplace Tab Content ─────────────────────────────── */}
        {activeTab === "marketplace" && (
          loading ? (
            <div className="flex flex-col items-center justify-center py-20">
              <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4 animate-spin">
                progress_activity
              </span>
              <p className="text-sm text-on-surface-variant/40">
                Loading connectors...
              </p>
            </div>
          ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredConnectors.map((connector) => (
              <ConnectorCard
                key={connector.id}
                connector={connector}
                onSelect={handleSelectConnector}
                onInstall={handleInstall}
              />
            ))}

            {filteredConnectors.length === 0 && (
              <div className="col-span-3 flex flex-col items-center justify-center py-20">
                <span className="material-symbols-outlined text-5xl text-on-surface-variant/30 mb-4">
                  search_off
                </span>
                <h3 className="text-lg font-headline font-semibold text-on-surface/60 mb-1">
                  No connectors found
                </h3>
                <p className="text-sm text-on-surface-variant/40">
                  Try adjusting your search or filter criteria.
                </p>
              </div>
            )}
          </div>
          )
        )}

        {/* ── Instances Tab ────────────────────────────────────────── */}
        {activeTab === "instances" && (
          <InstancesTab
            onCreateInstance={() => setShowCreateInstance(true)}
            allConnectors={connectors}
            instances={selectedWorkspace === "all" ? instances : instances.filter((inst) => inst.workspaces.some((ws) => ws.slug === selectedWorkspace))}
            onTestInstance={handleTestInstance}
            onRefreshData={refreshData}
          />
        )}

        {/* ── Workspace Access Tab ──────────────────────────────────── */}
        {activeTab === "workspace" && <WorkspaceAccessTab onUninstall={handleUninstall} />}
      </div>

      {/* ── Connector Detail Slide-over ────────────────────────── */}
      {selectedConnector && (
        <ConnectorDetailPanel
          // Re-read the connector from the refreshed list so the panel's
          // Install / Uninstall button follows the state after a click.
          connector={connectors.find((c) => c.id === selectedConnector.id) ?? selectedConnector}
          onClose={() => setSelectedConnector(null)}
          onInstall={handleInstall}
          onUninstall={handleUninstall}
          onDelete={handleDelete}
          pendingAction={pendingActions[selectedConnector.id] ?? null}
        />
      )}

      {/* ── Upload Connector Slide-over ──────────────────────────── */}
      {showUploadPanel && (
        <UploadConnectorPanel
          onClose={() => setShowUploadPanel(false)}
          onInstalled={() => void refreshData()}
        />
      )}

      {/* ── Create Instance Slide-over ──────────────────────────── */}
      {showCreateInstance && (
        <CreateInstancePanel
          onClose={() => setShowCreateInstance(false)}
          allConnectors={connectors}
          onCreated={() => refreshData()}
        />
      )}

      {/* ── Keyframes ──────────────────────────────────────────────── */}
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>

      {/* ── Background Decoration ──────────────────────────────────── */}
      <div className="fixed top-[-20%] right-[-10%] w-[600px] h-[600px] bg-primary/5 blur-[120px] pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] left-[-5%] w-[400px] h-[400px] bg-secondary/5 blur-[100px] pointer-events-none -z-10" />
    </div>
  );
}
