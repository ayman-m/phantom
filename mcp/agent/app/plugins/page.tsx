"use client";

/**
 * /plugins
 *
 * Inventory of plugins discovered under `bundles/spark/plugins/`.
 * Phantom plugins are filesystem-discovered (no marketplace, no
 * install flow): drop a directory, restart, plugin contributes
 * its skills + scenarios + memory seeds.
 *
 * The page is mostly informational — operators can see WHAT each
 * plugin contributed (counts) and READ the manifest (Plugin row
 * expands). The Reload action re-applies all enabled plugins
 * without a container restart, useful when an operator drops a
 * new plugin into the running container.
 */

import { useCallback, useEffect, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import { cn } from "@/lib/utils";

interface PluginInfo {
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  path: string;
  skills_count: number;
  scenarios_count: number;
  memory_seeds_count: number;
  seeded_count: number;
  error: string | null;
}

const glassCard = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedName, setExpandedName] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/plugins", { cache: "no-store" });
      if (!r.ok) throw new Error(`plugins fetch ${r.status}`);
      const data = (await r.json()) as { plugins?: PluginInfo[] };
      setPlugins(data.plugins ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleReload = useCallback(async () => {
    const accepted = await confirmAction({
      title: "Reload plugins?",
      message:
        "Re-applies skills, scenarios, and memory seeds for every enabled plugin. Operator-edited memories are preserved (only missing seeds get written).",
      confirmLabel: "Reload",
    });
    if (!accepted) return;
    setReloading(true);
    setError(null);
    try {
      const r = await fetch("/api/agent/plugins/reload", { method: "POST" });
      if (!r.ok) throw new Error(`reload ${r.status}`);
      const data = (await r.json()) as { plugins?: PluginInfo[] };
      setPlugins(data.plugins ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReloading(false);
    }
  }, []);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                extension
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Plugins
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Filesystem-discovered plugin bundles — each contributes skills, scenarios, and memory seeds.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleReload()}
              disabled={reloading || plugins.length === 0}
              className="px-4 py-2 rounded-xl text-xs font-medium text-on-primary-container bg-primary-container/30 hover:bg-primary-container/50 transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-base align-middle mr-1">
                {reloading ? "hourglass_top" : "refresh"}
              </span>
              {reloading ? "Reloading…" : "Reload all"}
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-16 text-sm text-on-surface-variant/60">
            Loading plugins…
          </div>
        ) : plugins.length === 0 ? (
          <div
            className="text-center py-12 rounded-2xl"
            style={glassCard}
          >
            <span className="material-symbols-outlined text-4xl text-on-surface-variant/40 mb-2 inline-block">
              extension_off
            </span>
            <p className="text-sm font-medium text-on-surface mb-1">
              No plugins installed.
            </p>
            <p className="text-xs text-on-surface-variant/60 max-w-md mx-auto leading-relaxed">
              Drop a plugin directory under{" "}
              <code className="font-mono">bundles/spark/plugins/</code>{" "}
              with a{" "}
              <code className="font-mono">manifest.yaml</code> declaring
              its skills / scenarios / memory_seeds, then click Reload.
              See the <code className="font-mono">example-vendor</code>{" "}
              reference plugin for the schema.
            </p>
          </div>
        ) : (
          <div className="grid gap-2">
            {plugins.map((p) => (
              <PluginRowCard
                key={p.name}
                plugin={p}
                expanded={expandedName === p.name}
                onToggleExpand={() =>
                  setExpandedName((prev) =>
                    prev === p.name ? null : p.name,
                  )
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PluginRowCard({
  plugin,
  expanded,
  onToggleExpand,
}: {
  plugin: PluginInfo;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl p-4 transition-opacity",
        !plugin.enabled && "opacity-60",
      )}
      style={glassCard}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "material-symbols-outlined text-base shrink-0 mt-0.5",
            plugin.error
              ? "text-error"
              : plugin.enabled
                ? "text-primary"
                : "text-on-surface-variant/50",
          )}
        >
          {plugin.error ? "error" : plugin.enabled ? "extension" : "extension_off"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-mono text-sm font-semibold text-on-surface truncate">
              {plugin.name}
            </span>
            <span className="text-[10px] font-mono text-on-surface-variant/60">
              v{plugin.version}
            </span>
            {!plugin.enabled && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-on-surface-variant/60">
                disabled
              </span>
            )}
            {plugin.error && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-error/15 text-error">
                error
              </span>
            )}
          </div>
          {plugin.description && (
            <p className="text-xs text-on-surface-variant mb-1.5 leading-relaxed">
              {plugin.description}
            </p>
          )}
          <div className="flex items-center gap-3 text-[11px] font-mono text-on-surface-variant/70">
            <span title="Skills">
              <span className="material-symbols-outlined text-[12px] align-middle mr-0.5">
                school
              </span>
              {plugin.skills_count} skill{plugin.skills_count === 1 ? "" : "s"}
            </span>
            <span title="Scenarios">
              <span className="material-symbols-outlined text-[12px] align-middle mr-0.5">
                play_circle
              </span>
              {plugin.scenarios_count} scenario
              {plugin.scenarios_count === 1 ? "" : "s"}
            </span>
            <span title="Memory seeds">
              <span className="material-symbols-outlined text-[12px] align-middle mr-0.5">
                psychology
              </span>
              {plugin.memory_seeds_count} seed
              {plugin.memory_seeds_count === 1 ? "" : "s"}
              {plugin.seeded_count > 0 && (
                <span className="text-secondary ml-0.5">
                  ({plugin.seeded_count} new)
                </span>
              )}
            </span>
          </div>
          {plugin.error && (
            <p className="text-[11px] text-error font-mono mt-2 break-all">
              {plugin.error}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onToggleExpand}
          aria-label={expanded ? "Collapse" : "Expand"}
          className="p-1.5 rounded hover:bg-white/5 text-on-surface-variant/70 hover:text-on-surface"
        >
          <span className="material-symbols-outlined text-base">
            {expanded ? "expand_less" : "expand_more"}
          </span>
        </button>
      </div>
      {expanded && (
        <div className="mt-3 pt-3 border-t border-white/5 grid grid-cols-1 gap-2">
          <Detail label="Path" value={plugin.path} mono />
          <Detail
            label="Memory seed kinds"
            value={
              "Loaded into the agent scope on plugin reload. Existing keys are NOT overwritten — operator edits win. Tagged with meta.source=plugin:" +
              plugin.name +
              " for provenance."
            }
          />
        </div>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60">
        {label}
      </p>
      <p
        className={cn(
          "text-on-surface-variant text-xs",
          mono && "font-mono break-all",
        )}
      >
        {value || "—"}
      </p>
    </div>
  );
}
