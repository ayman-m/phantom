'use client';

import { useEffect, useRef, useState } from 'react';

export type AuditEvent = {
  id: number | string;
  ts: string;
  actor?: string;
  action: string;
  target?: string;
  status?: string;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
  meta?: Record<string, unknown>;
};

type State = {
  events: AuditEvent[];
  status: 'connecting' | 'live' | 'reconnecting' | 'closed';
  error: string | null;
};

const MAX_EVENTS = 500;

/**
 * Subscribe to /api/agent/audit/stream as SSE. Maintains a bounded
 * MRU list (newest first) of events. On disconnect, reconnects with
 * exponential backoff (1s, 2s, 4s, 8s, capped at 15s) plus ±25%
 * jitter so a downed MCP doesn't get hammered.
 *
 * Uses fetch + ReadableStream (not EventSource) because EventSource
 * can't send custom headers, and the proxy's SSE pass-through is
 * simpler if we don't need them on the wire (auth is server-side).
 */
export function useAuditStream(initial = 100): State {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [status, setStatus] = useState<State['status']>('connecting');
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    let attempt = 0;
    let abort: AbortController | null = null;

    const connect = async (): Promise<void> => {
      if (cancelledRef.current) return;
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      setError(null);
      abort = new AbortController();
      try {
        const r = await fetch(
          `/api/agent/audit/stream?initial=${initial}`,
          { signal: abort.signal },
        );
        if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
        attempt = 0;
        setStatus('live');

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n');
          buffer = frames.pop() || '';
          for (const frame of frames) {
            const line = frame.trim();
            if (!line || !line.startsWith('data:')) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try {
              const ev = JSON.parse(payload) as AuditEvent;
              setEvents((cur) => {
                // Prepend (newest first), dedupe by id, cap.
                const seen = new Set([String(ev.id)]);
                const next: AuditEvent[] = [ev];
                for (const e of cur) {
                  const k = String(e.id);
                  if (seen.has(k)) continue;
                  seen.add(k);
                  next.push(e);
                  if (next.length >= MAX_EVENTS) break;
                }
                return next;
              });
            } catch {
              // Tolerate junk frames; SSE comments (`: heartbeat`) hit
              // the prefix check above and skip cleanly.
            }
          }
        }
      } catch (err) {
        if (cancelledRef.current) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        abort = null;
      }

      // Reconnect with exponential backoff + jitter unless cancelled.
      if (cancelledRef.current) return;
      attempt += 1;
      const base = Math.min(15_000, 1_000 * Math.pow(2, attempt - 1));
      const jitter = base * (0.75 + Math.random() * 0.5);
      setStatus('reconnecting');
      setTimeout(() => {
        if (!cancelledRef.current) connect();
      }, jitter);
    };

    connect();

    return () => {
      cancelledRef.current = true;
      abort?.abort();
      setStatus('closed');
    };
  }, [initial]);

  return { events, status, error };
}
