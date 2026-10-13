/**
 * Where an adapter's non-fatal observations go.
 *
 * An adapter reports a request setting it had to change (`tool_choice_downgraded`),
 * model output it had to drop (`tool_call_truncated`, `unknown_tool_name`) or an
 * answer it could not give (`refusal`) through `CallContext.onEvent`. The chat
 * route hands every model call a sink made here, which writes each observation
 * to two places and never to the operator's thread:
 *
 *   - an SSE `debug` event, shaped like the route's debug lines (`stage`,
 *     `detail`) plus the structured fields. The chat UI shows it only in the
 *     Wire events panel; it adds no message text;
 *   - an audit row `provider_event` (`target: session:<id>`), so a refusal or a
 *     downgrade can be found after the session is closed.
 *
 * The same observation is written once per sink: a turn that keeps calling an
 * unknown tool name does not flood either stream. Both outputs are best effort;
 * a failing one never reaches the model call. Observations carry names and
 * counts only, never credentials, URLs or message text, and the structured
 * `data` is capped.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import type { ModelRef, ModelRequest, ProviderEvent } from './types.ts';

/** The audit action the sink writes. */
export const PROVIDER_EVENT_AUDIT_ACTION = 'provider_event';

/** The SSE event name the sink sends. */
export const PROVIDER_EVENT_SSE_NAME = 'debug';

/** Longest serialized `data` kept on an observation. */
export const MAX_EVENT_DATA_CHARS = 1000;

export interface ProviderEventSinkOptions {
  ref: ModelRef;
  purpose: ModelRequest['purpose'];
  /** The session the call belongs to (audit target). */
  sessionId: string;
  sendEvent?: (kind: string, data: unknown) => void;
  audit?: (
    action: string,
    row: { target: string; status: 'success'; metadata: Record<string, unknown> },
  ) => void | Promise<void>;
}

function boundedData(data: Record<string, unknown> | undefined): Record<string, unknown> | undefined {
  if (!data) return undefined;
  let text: string;
  try {
    text = JSON.stringify(data);
  } catch {
    return { truncated: true };
  }
  return text.length > MAX_EVENT_DATA_CHARS ? { truncated: true } : data;
}

/** The SSE `debug` payload for an observation. */
export function debugPayload(event: ProviderEvent, opts: Pick<ProviderEventSinkOptions, 'ref' | 'purpose'>): Record<string, unknown> {
  const data = boundedData(event.data);
  return {
    stage: 'provider',
    detail: `${event.type}: ${event.message}`,
    provider: opts.ref.provider,
    model: opts.ref.model,
    purpose: opts.purpose,
    type: event.type,
    ...(data ? { data } : {}),
  };
}

export function createProviderEventSink(opts: ProviderEventSinkOptions): (event: ProviderEvent) => void {
  const seen = new Set<string>();
  return (event: ProviderEvent): void => {
    const payload = debugPayload(event, opts);
    const key = JSON.stringify([event.type, payload.data ?? null]);
    if (seen.has(key)) return;
    seen.add(key);
    try {
      opts.sendEvent?.(PROVIDER_EVENT_SSE_NAME, payload);
    } catch {
      // A closed stream must not fail the model call.
    }
    try {
      void Promise.resolve(
        opts.audit?.(PROVIDER_EVENT_AUDIT_ACTION, {
          target: `session:${opts.sessionId}`,
          status: 'success',
          metadata: {
            provider: opts.ref.provider,
            model: opts.ref.model,
            purpose: opts.purpose,
            type: event.type,
            message: event.message,
            ...(payload.data ? { data: payload.data } : {}),
          },
        }),
      ).catch(() => {});
    } catch {
      // Auditing never blocks a model call.
    }
  };
}
