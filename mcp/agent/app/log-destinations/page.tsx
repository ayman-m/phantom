/**
 * /log-destinations — operator-managed log forwarding targets.
 *
 * CRUD over the LogDestinationStore backed by per-type yaml manifests
 * (bundles/spark/destinations/<id>/spec.yaml). Each type has its own
 * config schema rendered dynamically by the FormEngine component. The
 * existing-instance row's "Test" button fires the type's probe handler
 * + persists the outcome (last_probe_at / _ok / _error).
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  FormEngine,
  type FormFieldDef,
  findMissingRequired,
  projectVisibleValues,
} from "@/components/form-engine";
import {
  createDestination,
  deleteDestination,
  listDestinationTypes,
  listDestinations,
  probeDestination,
  setDefaultDestination,
  updateDestination,
  type DestinationTypeManifest,
  type LogDestination,
} from "@/lib/api/log-destinations";
import GenerationAdmissionPanel from "@/components/generation-admission-panel";

// ── Page ───────────────────────────────────────────────────────────

export default function LogDestinationsPage() {
  const [types, setTypes] = useState<DestinationTypeManifest[]>([]);
  const [destinations, setDestinations] = useState<LogDestination[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<LogDestination | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [search, setSearch] = useState("");
  const [probeResults, setProbeResults] = useState<
    Record<string, { ok: boolean; message: string }>
  >({});
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [t, d] = await Promise.all([
      listDestinationTypes(),
      listDestinations(),
    ]);
    setTypes(t);
    setDestinations(d);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const typeById = useMemo(() => {
    const m: Record<string, DestinationTypeManifest> = {};
    for (const t of types) m[t.id] = t;
    return m;
  }, [types]);

  const filtered = useMemo(() => {
    return destinations.filter((d) => {
      if (filterType && d.type_id !== filterType) return false;
      if (search) {
        const needle = search.toLowerCase();
        if (
          !d.name.toLowerCase().includes(needle) &&
          !(d.description || "").toLowerCase().includes(needle)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [destinations, filterType, search]);

  // Group by type for visual structure
  const grouped = useMemo(() => {
    const m: Record<string, LogDestination[]> = {};
    for (const d of filtered) {
      (m[d.type_id] ||= []).push(d);
    }
    return m;
  }, [filtered]);

  const onTest = useCallback(async (dest: LogDestination) => {
    setProbeResults((p) => ({
      ...p,
      [dest.id]: { ok: false, message: "Testing..." },
    }));
    const result = await probeDestination(dest.id);
    if (!result.ok) {
      setProbeResults((p) => ({
        ...p,
        [dest.id]: { ok: false, message: "request failed" },
      }));
      return;
    }
    const ok = !!result.data.ok;
    const message = ok
      ? `OK · ${result.data.latency_ms}ms`
      : result.data.error ?? "failed";
    setProbeResults((p) => ({ ...p, [dest.id]: { ok, message } }));
    void refresh();
    // Auto-clear the banner after 6s
    setTimeout(() => {
      setProbeResults((p) => {
        const { [dest.id]: _omit, ...rest } = p;
        return rest;
      });
    }, 6000);
  }, [refresh]);

  const onToggleEnabled = useCallback(async (dest: LogDestination) => {
    await updateDestination(dest.id, { enabled: !dest.enabled });
    void refresh();
  }, [refresh]);

  const onSetDefault = useCallback(async (dest: LogDestination) => {
    await setDefaultDestination(dest.id);
    void refresh();
  }, [refresh]);

  const onDelete = useCallback(async (dest: LogDestination) => {
    await deleteDestination(dest.id);
    setConfirmDeleteId(null);
    void refresh();
  }, [refresh]);

  return (
    <div className="min-h-screen px-8 py-8 text-on-surface">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-3xl font-headline font-bold tracking-tight">
            Log Destinations
          </h1>
          <p className="text-sm text-on-surface-variant mt-1 max-w-2xl">
            Configure where Phantom forwards synthesized security records.
            Each destination has a type — syslog, webhook, XSIAM, Splunk
            HEC — with type-specific config and credentials. Records flow
            through here when a data worker references the destination by name.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="text-white font-bold py-3 px-6 rounded-xl flex items-center gap-2 transition-all hover:shadow-[0px_0px_30px_rgba(25,99,179,0.3)]"
          style={{
            background: "linear-gradient(to right, #1963B3, #2D8DF0)",
          }}
        >
          <span className="material-symbols-outlined text-xl">add</span>
          New Destination
        </button>
      </div>

      <GenerationAdmissionPanel />

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-6">
        <input
          type="text"
          placeholder="Search by name or description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-surface-container-highest border-none rounded-xl px-4 py-2.5 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
          style={{ border: "0.5px solid var(--glass-border)" }}
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="bg-surface-container-highest border-none rounded-xl px-4 py-2.5 text-sm focus:ring-1 focus:ring-primary/40 outline-none text-on-surface"
          style={{ border: "0.5px solid var(--glass-border)" }}
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      {loading && (
        <div className="text-on-surface-variant py-10 text-center text-sm">
          Loading destinations…
        </div>
      )}

      {!loading && destinations.length === 0 && (
        <EmptyState onCreate={() => setCreating(true)} />
      )}

      {!loading && destinations.length > 0 && (
        <div className="space-y-10">
          {Object.entries(grouped).map(([typeId, rows]) => {
            const manifest = typeById[typeId];
            if (!manifest) return null;
            return (
              <section key={typeId}>
                <TypeHeader manifest={manifest} count={rows.length} />
                <div className="space-y-3">
                  {rows.map((dest) => (
                    <DestinationRow
                      key={dest.id}
                      dest={dest}
                      manifest={manifest}
                      probeResult={probeResults[dest.id]}
                      confirmDelete={confirmDeleteId === dest.id}
                      onConfirmDelete={() => setConfirmDeleteId(dest.id)}
                      onCancelDelete={() => setConfirmDeleteId(null)}
                      onTest={() => onTest(dest)}
                      onEdit={() => setEditing(dest)}
                      onToggleEnabled={() => onToggleEnabled(dest)}
                      onSetDefault={() => onSetDefault(dest)}
                      onDelete={() => onDelete(dest)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Create modal */}
      {creating && (
        <EditPanel
          types={types}
          existing={null}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            void refresh();
          }}
        />
      )}

      {/* Edit modal */}
      {editing && (
        <EditPanel
          types={types}
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void refresh();
          }}
        />
      )}
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-20">
      <span className="material-symbols-outlined text-6xl text-on-surface-variant/30 mb-4">
        cloud_upload
      </span>
      <h3 className="text-xl font-headline font-semibold text-on-surface/70 mb-2">
        No log destinations yet
      </h3>
      <p className="text-sm text-on-surface-variant/50 mb-6 max-w-md text-center">
        Add a destination to forward synthesized records to your SIEM,
        webhook, or HTTP collector. Workers reference destinations by name.
      </p>
      <button
        type="button"
        onClick={onCreate}
        className="text-white px-6 py-3 rounded-xl font-headline font-bold flex items-center gap-2"
        style={{
          background: "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)",
        }}
      >
        <span className="material-symbols-outlined">add</span>
        New Destination
      </button>
    </div>
  );
}

// ── Per-type group header ──────────────────────────────────────────

function TypeHeader({
  manifest, count,
}: { manifest: DestinationTypeManifest; count: number }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center"
        style={{ background: manifest.iconBg }}
      >
        <span
          className="material-symbols-outlined text-lg"
          style={{ color: manifest.iconColor }}
        >
          {manifest.icon}
        </span>
      </div>
      <h4 className="text-xs font-label font-bold tracking-widest text-on-surface-variant uppercase">
        {manifest.name}
        <span className="ml-2 font-normal lowercase opacity-50">
          ({count} destination{count !== 1 ? "s" : ""})
        </span>
      </h4>
    </div>
  );
}

// ── Destination row ────────────────────────────────────────────────

interface DestinationRowProps {
  dest: LogDestination;
  manifest: DestinationTypeManifest;
  probeResult?: { ok: boolean; message: string };
  confirmDelete: boolean;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onTest: () => void;
  onEdit: () => void;
  onToggleEnabled: () => void;
  onSetDefault: () => void;
  onDelete: () => void;
}

function DestinationRow({
  dest,
  manifest,
  probeResult,
  confirmDelete,
  onConfirmDelete,
  onCancelDelete,
  onTest,
  onEdit,
  onToggleEnabled,
  onSetDefault,
  onDelete,
}: DestinationRowProps) {
  const statusDot =
    dest.last_probe_ok === true
      ? { color: "#7bdc7b", title: "Last probe: OK" }
      : dest.last_probe_ok === false
        ? { color: "#fc7676", title: `Last probe: ${dest.last_probe_error ?? "failed"}` }
        : { color: "#8c919d", title: "Never probed" };

  // A quick teaser line: pick a few representative non-secret config keys
  const summary = useMemo(() => {
    const parts: string[] = [];
    const cfg = dest.config || {};
    // syslog → host:port (protocol); webhook → url; xsiam_http → url; splunk_hec → url
    if (manifest.id === "syslog") {
      const host = cfg.host || "?";
      const port = cfg.port || "?";
      const proto = cfg.protocol || "?";
      parts.push(`${proto}://${host}:${port}`);
    } else if (cfg.url) {
      parts.push(String(cfg.url));
    }
    return parts.join(" · ");
  }, [dest.config, manifest.id]);

  return (
    <div
      className="rounded-2xl transition-all group"
      style={{
        background: "var(--glass-bg)",
        border: "0.5px solid rgba(140, 145, 157, 0.1)",
      }}
    >
      <div className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-5 min-w-0 flex-1">
          {/* Enable toggle */}
          <button
            type="button"
            onClick={onToggleEnabled}
            className="w-11 h-6 rounded-full relative p-1 cursor-pointer transition-colors shrink-0"
            style={{
              background: dest.enabled
                ? "rgba(3, 115, 33, 0.3)"
                : "var(--glass-border)",
            }}
            aria-label={dest.enabled ? "Disable destination" : "Enable destination"}
            title={dest.enabled ? "Disable" : "Enable"}
          >
            <div
              className="w-4 h-4 rounded-full transition-all"
              style={{
                background: dest.enabled ? "white" : "rgba(140, 145, 157, 0.4)",
                transform: dest.enabled ? "translateX(20px)" : "translateX(0)",
              }}
            />
          </button>

          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-on-surface font-headline font-semibold truncate">
                {dest.name}
              </span>
              {dest.is_default && (
                <span
                  className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                  style={{
                    background: "rgba(167, 200, 255, 0.15)",
                    border: "0.5px solid rgba(167, 200, 255, 0.3)",
                    color: "#a7c8ff",
                  }}
                  title="Default destination for this type"
                >
                  Default
                </span>
              )}
              <span
                className="text-[10px] font-label px-2 py-0.5 rounded-full text-on-surface-variant"
                style={{
                  background: "rgba(52, 51, 64, 0.6)",
                  border: "0.5px solid rgba(255, 255, 255, 0.05)",
                }}
              >
                {manifest.name}
              </span>
            </div>
            <div className="text-xs text-on-surface-variant/70 mt-1 truncate font-mono">
              {summary}
            </div>
            {dest.description && (
              <div className="text-[11px] text-on-surface-variant/50 mt-0.5 truncate italic">
                {dest.description}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {/* Status dot */}
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: statusDot.color }}
            title={statusDot.title}
          />
          {/* Probe result banner (transient) */}
          {probeResult && (
            <span
              className="text-[11px] font-medium px-2 py-1 rounded-full"
              style={{
                background: probeResult.ok
                  ? "rgba(3, 115, 33, 0.15)"
                  : "rgba(147, 0, 10, 0.15)",
                border: probeResult.ok
                  ? "0.5px solid rgba(123, 220, 123, 0.3)"
                  : "0.5px solid rgba(255, 180, 171, 0.3)",
                color: probeResult.ok ? "#7bdc7b" : "#fc7676",
              }}
            >
              {probeResult.message}
            </span>
          )}
          <div className="flex gap-1 opacity-100 group-hover:opacity-100 transition-opacity">
            <button
              type="button"
              onClick={onTest}
              className="px-3 py-1.5 rounded-lg text-xs font-headline font-bold transition-all flex items-center gap-1.5 text-primary"
              style={{
                background: "rgba(167, 200, 255, 0.1)",
                border: "0.5px solid rgba(167, 200, 255, 0.2)",
              }}
              title="Send a test message"
            >
              <span className="material-symbols-outlined text-base">
                play_circle
              </span>
              Test
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="p-2 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white/5 transition-colors"
              title="Edit"
            >
              <span className="material-symbols-outlined">edit</span>
            </button>
            {!dest.is_default && (
              <button
                type="button"
                onClick={onSetDefault}
                className="p-2 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white/5 transition-colors"
                title="Set as default for this type"
              >
                <span className="material-symbols-outlined">push_pin</span>
              </button>
            )}
            {confirmDelete ? (
              <button
                type="button"
                onClick={onDelete}
                onBlur={() => setTimeout(onCancelDelete, 200)}
                className="px-3 py-1.5 rounded-lg text-xs font-bold text-error transition-all"
                style={{
                  background: "rgba(147, 0, 10, 0.2)",
                  border: "0.5px solid rgba(255, 180, 171, 0.3)",
                }}
              >
                Confirm?
              </button>
            ) : (
              <button
                type="button"
                onClick={onConfirmDelete}
                className="p-2 rounded-lg text-on-surface-variant hover:text-error hover:bg-white/5 transition-colors"
                title="Delete"
              >
                <span className="material-symbols-outlined">delete</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Create/Edit slide-over panel ────────────────────────────────────

interface EditPanelProps {
  types: DestinationTypeManifest[];
  existing: LogDestination | null;
  onClose: () => void;
  onSaved: () => void;
}

function EditPanel({ types, existing, onClose, onSaved }: EditPanelProps) {
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [selectedTypeId, setSelectedTypeId] = useState<string>(
    existing?.type_id ?? "",
  );
  const [values, setValues] = useState<Record<string, string>>(() => {
    if (!existing) return {};
    // Merge non-secret config + secret slots as "***" placeholders
    return { ...existing.config, ...existing.secrets };
  });
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const manifest = useMemo(
    () => types.find((t) => t.id === selectedTypeId) ?? null,
    [types, selectedTypeId],
  );

  // Seed defaults on type selection (only for blank fields)
  useEffect(() => {
    if (!manifest) return;
    setValues((prev) => {
      const next = { ...prev };
      for (const f of manifest.fields) {
        if (
          f.defaultValue !== null &&
          f.defaultValue !== undefined &&
          next[f.name] === undefined
        ) {
          next[f.name] = String(f.defaultValue);
        }
      }
      return next;
    });
  }, [manifest]);

  const fields = useMemo<FormFieldDef[]>(
    () => (manifest?.fields ?? []) as FormFieldDef[],
    [manifest],
  );
  const missing = useMemo(
    () => findMissingRequired(fields, values),
    [fields, values],
  );
  const canSave = name.trim().length > 0 && !!manifest && missing.length === 0;

  const handleSave = useCallback(async () => {
    if (!manifest) return;
    setSaving(true);
    setFeedback(null);
    try {
      // Split visible values into config/secrets buckets per type manifest
      const visible = projectVisibleValues(fields as FormFieldDef[], values);
      const configBucket: Record<string, string> = {};
      const secretsBucket: Record<string, string> = {};
      for (const f of fields) {
        const v = visible[f.name];
        if (v === undefined) continue;
        if (f.type === "secret" || f.type === "password") {
          secretsBucket[f.name] = v;
        } else {
          configBucket[f.name] = v;
        }
      }
      if (existing) {
        const result = await updateDestination(existing.id, {
          name: name.trim(),
          config: configBucket,
          secrets: secretsBucket,
          description: description.trim() || null,
        });
        if (!result.ok) {
          setFeedback({
            type: "error",
            message: result.error?.message ?? "update failed",
          });
          return;
        }
      } else {
        const result = await createDestination({
          name: name.trim(),
          type_id: manifest.id,
          config: configBucket,
          secrets: secretsBucket,
          description: description.trim() || undefined,
        });
        if (!result.ok) {
          setFeedback({
            type: "error",
            message: result.error?.message ?? "create failed",
          });
          return;
        }
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  }, [manifest, name, description, values, fields, existing, onSaved]);

  return (
    <>
      <div
        className="fixed inset-0 z-40 backdrop-blur-sm"
        style={{ background: "rgba(18, 18, 30, 0.6)" }}
        onClick={onClose}
      />
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
        {/* Header */}
        <div className="flex items-start justify-between px-8 pt-8 pb-6">
          <div>
            <h2 className="text-3xl font-headline font-bold tracking-tight text-on-surface">
              {existing ? "Edit Destination" : "New Destination"}
            </h2>
            <p className="text-sm text-on-surface-variant mt-1">
              {existing
                ? "Update the destination's config or secrets."
                : "Configure a new log forwarding target."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full hover:bg-surface-variant/40 text-on-surface-variant transition-colors"
            aria-label="Close"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto custom-scrollbar px-8 pb-32 space-y-8">
          {/* Identity */}
          <section className="space-y-5">
            <SectionHeading title="Identity" />
            <div className="grid gap-5">
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                  Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
                  style={{ border: "0.5px solid var(--glass-border)" }}
                  placeholder="e.g. corp-syslog, dev-webhook"
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
                  Description (optional)
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline resize-none"
                  style={{ border: "0.5px solid var(--glass-border)" }}
                  placeholder="Free-text notes for the operator…"
                />
              </div>
            </div>
          </section>

          {/* Type selector (only when creating) */}
          {!existing && (
            <section className="space-y-5">
              <SectionHeading title="Type" />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {types.map((t) => {
                  const isOn = selectedTypeId === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => {
                        setSelectedTypeId(t.id);
                        setValues({});
                      }}
                      className="p-4 rounded-xl text-left transition-all flex items-start gap-3"
                      style={{
                        background: isOn
                          ? "rgba(167, 200, 255, 0.1)"
                          : "var(--m3-surface-container)",
                        border: isOn
                          ? "0.5px solid rgba(167, 200, 255, 0.4)"
                          : "0.5px solid var(--glass-border)",
                      }}
                    >
                      <div
                        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                        style={{ background: t.iconBg }}
                      >
                        <span
                          className="material-symbols-outlined"
                          style={{ color: t.iconColor }}
                        >
                          {t.icon}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-bold text-on-surface mb-0.5">
                          {t.name}
                        </div>
                        <div className="text-[11px] text-on-surface-variant/70 leading-relaxed line-clamp-2">
                          {t.description}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* Dynamic config */}
          {manifest && (
            <section className="space-y-5">
              <SectionHeading title="Configuration" />
              <FormEngine
                fields={manifest.fields as FormFieldDef[]}
                values={values}
                onChange={(k, v) => setValues((p) => ({ ...p, [k]: v }))}
                secretRedactSentinel={!!existing}
              />
            </section>
          )}

          {feedback && (
            <div
              className="p-3 rounded-xl text-xs"
              style={{
                background:
                  feedback.type === "error"
                    ? "rgba(147, 0, 10, 0.15)"
                    : "rgba(3, 115, 33, 0.15)",
                color: feedback.type === "error" ? "#fc7676" : "#7bdc7b",
                border:
                  feedback.type === "error"
                    ? "0.5px solid rgba(255, 180, 171, 0.3)"
                    : "0.5px solid rgba(123, 220, 123, 0.3)",
              }}
            >
              {feedback.message}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="absolute bottom-0 left-0 right-0 px-8 py-6 flex items-center justify-between"
          style={{
            background: "var(--glass-bg-strong)",
            backdropFilter: "blur(12px)",
            borderTop: "0.5px solid var(--glass-border)",
          }}
        >
          <div className="flex items-center gap-2 text-on-surface-variant text-xs">
            {missing.length > 0 && (
              <>
                <span className="material-symbols-outlined text-base">
                  info
                </span>
                <span>Missing required: {missing.join(", ")}</span>
              </>
            )}
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 rounded-xl text-on-surface font-medium hover:bg-surface-variant/50 transition-all"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSave || saving}
              onClick={handleSave}
              className="px-8 py-3 rounded-xl font-headline font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: canSave
                  ? "linear-gradient(to right, #1963b3, #2D8DF0)"
                  : "rgba(52, 51, 64, 0.6)",
                color: canSave ? "white" : "rgba(255, 255, 255, 0.3)",
              }}
            >
              {saving ? "Saving…" : existing ? "Save Changes" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function SectionHeading({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-1 h-4 bg-primary rounded-full" />
      <h2 className="font-headline font-semibold text-lg text-on-surface">
        {title}
      </h2>
    </div>
  );
}
