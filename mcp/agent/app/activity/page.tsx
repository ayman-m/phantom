'use client';

import { AdminShell } from '@/components/admin/admin-shell';
import { useAuditStream } from '@/lib/use-audit-stream';

/**
 * Per-action icon + color metadata for the
 * activity feed. Maps audit action names to a Material Symbol +
 * a Tailwind color class so each event row gets visual recognition.
 *
 * Pattern matching: exact action match wins, then prefix match
 * (e.g. `chat_compaction_*` falls back to a single bucket if no
 * exact entry). Unknown actions fall through to the generic icon.
 */
function actionMeta(action: string): { icon: string; tone: string } {
  // Color tones tuned for dark theme — -400/-500 shades have enough
  // contrast against bg-slate-900 surfaces. -600/-700 (their old
  // values) blended into the background and were nearly invisible.
  // text-primary is a theme-aware token; it adapts to either theme.
  // Chat-route emitters (compaction, context-guard and cache audit families).
  if (action === 'chat_compaction_start') return { icon: 'compress', tone: 'text-primary' };
  if (action === 'chat_compaction_end') return { icon: 'compress', tone: 'text-emerald-400' };
  if (action === 'chat_compaction_failed') return { icon: 'error', tone: 'text-rose-400' };
  if (action === 'chat_context_warning') return { icon: 'warning', tone: 'text-amber-400' };
  if (action === 'chat_cache_hit') return { icon: 'bolt', tone: 'text-amber-400' };
  // Existing phantom audit families.
  if (action === 'tool_call') return { icon: 'build', tone: 'text-primary' };
  if (action === 'simulation_created' || action === 'scenario_started') {
    return { icon: 'play_circle', tone: 'text-primary' };
  }
  if (action === 'caldera_operation_created') return { icon: 'security', tone: 'text-rose-400' };
  if (action === 'detection_validation_recorded') return { icon: 'fact_check', tone: 'text-emerald-400' };
  if (action === 'coverage_report_generated') return { icon: 'assessment', tone: 'text-primary' };
  if (action === 'settings_changed') {
    return { icon: 'settings', tone: 'text-slate-300' };
  }
  if (action.startsWith('secret_')) return { icon: 'key', tone: 'text-amber-400' };
  if (action.startsWith('instance_')) return { icon: 'cloud', tone: 'text-primary' };
  if (action.startsWith('provider_')) return { icon: 'extension', tone: 'text-primary' };
  return { icon: 'circle', tone: 'text-slate-400' };
}

/**
 * Activity timeline — live audit feed via SSE.
 *
 * Subscribes to /api/agent/audit/stream which the agent proxies to
 * the MCP's /api/v1/audit/stream. The stream replays the most recent
 * 100 events as a baseline on connect and then pushes any new rows
 * within ~1s of the audit log writing them. Reconnects with
 * exponential backoff if the stream drops.
 *
 * Replaces the deprecated A2UI SparkActivityTimeline pattern (where
 * the MCP would `surface_bus.publish("activity", ...)` and the
 * renderer would re-fetch /api/v1/audit on each ping). Same end
 * result, simpler protocol — just JSON rows on an SSE wire.
 */
export default function ActivityPage() {
  const { events, status, error } = useAuditStream(100);

  const dotClass =
    status === 'live'
      ? 'bg-emerald-500'
      : status === 'connecting'
      ? 'bg-amber-400 animate-pulse'
      : status === 'reconnecting'
      ? 'bg-amber-400'
      : 'bg-rose-500';

  return (
    <AdminShell
      title="Activity"
      subtitle="Live audit feed. Tool calls, approvals, settings changes, runs — newest first, streamed as they happen."
      error={error}
      toolbar={
        <span className="flex items-center gap-2 rounded-full border border-outline-variant/40 bg-white/5 px-3 py-1 text-[11px] font-medium text-on-surface-variant shadow-sm">
          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
          {status}
        </span>
      }
    >
      {events.length === 0 ? (
        <p className="text-sm text-on-surface-variant">
          {status === 'connecting'
            ? 'Connecting to audit stream…'
            : 'No activity yet. Use the chat or trigger a job to see events here.'}
        </p>
      ) : (
        // Theme tokens (text-on-surface, text-on-surface-variant,
        // border-outline-variant) adapt to light + dark automatically.
        // The status-pill tones use semi-transparent dark fills so the
        // colored badge reads on either theme without a hard
        // background swap.
        <ul className="divide-y divide-outline-variant/20">
          {events.map((e) => {
            const meta = actionMeta(e.action);
            return (
            <li key={String(e.id)} className="py-3 text-sm">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[11px] text-on-surface-variant">
                  {e.ts}
                </span>
                {/* Per-action icon. Inline so
                    the eye sweep down the timeline picks up event
                    KIND from the icon column rather than reading
                    each action name. */}
                <span
                  className={`material-symbols-outlined text-[14px] -mb-0.5 ${meta.tone}`}
                  aria-hidden="true"
                >
                  {meta.icon}
                </span>
                <span className="font-semibold text-on-surface">{e.action}</span>
                {e.target ? (
                  <span className="font-mono text-xs text-on-surface-variant">
                    {e.target}
                  </span>
                ) : null}
                {e.status ? (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      e.status === 'ok' || e.status === 'success'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : e.status === 'denied' || e.status === 'failed'
                        ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                        : 'bg-white/10 text-on-surface-variant border border-outline-variant/30'
                    }`}
                  >
                    {e.status}
                  </span>
                ) : null}
                {e.actor ? (
                  <span className="ml-auto text-xs text-on-surface-variant">
                    by {e.actor}
                  </span>
                ) : null}
              </div>
              {(() => {
                const eventMeta = e.metadata ?? e.meta;
                return eventMeta && Object.keys(eventMeta).length > 0 ? (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-on-surface-variant">
                      meta
                    </summary>
                    <pre className="mt-1 overflow-auto rounded bg-black/30 p-2 text-[11px] text-on-surface-variant border border-outline-variant/20">
                      {JSON.stringify(eventMeta, null, 2)}
                    </pre>
                  </details>
                ) : null;
              })()}
            </li>
            );
          })}
        </ul>
      )}
    </AdminShell>
  );
}
