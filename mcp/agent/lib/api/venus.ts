/**
 * Venus messaging service API client.
 *
 * Venus runs at http://venus:8090 internally. All calls are routed through
 * the Next.js proxy at /api/venus/* to avoid CORS and keep the API key
 * server-side.
 */

// ── Types ────────────────────────────────────────────────────────────────────

export interface VenusChannel {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface VenusMessage {
  id: string;
  channel_id: string;
  sender_id: string;
  sender_name: string;
  text: string;
  thread_id?: string;
  reply_to_id?: string;
  created_at: string;
}

export interface VenusStatus {
  service: string;
  version: string;
  uptime: string;
  channels: number;
  messages: number;
  webhooks: number;
}

// ── API Functions ────────────────────────────────────────────────────────────

const BASE = "/api/venus";

async function venusGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function venusPost<T>(path: string, body: Record<string, unknown>): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** List all Venus channels. */
export async function listChannels(): Promise<VenusChannel[]> {
  return (await venusGet<VenusChannel[]>("/channels")) ?? [];
}

/** List messages in a Venus channel. */
export async function listMessages(channelId: string, since?: string): Promise<VenusMessage[]> {
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  return (await venusGet<VenusMessage[]>(`/channels/${encodeURIComponent(channelId)}/messages${qs}`)) ?? [];
}

/** Send a message to a Venus channel. */
export async function sendMessage(
  channelId: string,
  text: string,
  senderName = "User",
): Promise<VenusMessage | null> {
  return venusPost<VenusMessage>(`/channels/${encodeURIComponent(channelId)}/messages`, {
    text,
    sender_id: "ui-user",
    sender_name: senderName,
  });
}

/** Get Venus service status. */
export async function getStatus(): Promise<VenusStatus | null> {
  return venusGet<VenusStatus>("/status");
}

/** Build a WebSocket URL for a Venus channel. */
export function venusWebSocketUrl(channelId: string): string {
  // In the browser, connect through the Next.js proxy which handles
  // the Venus URL resolution. But Venus WS requires direct connection
  // since Next.js API routes don't support WebSocket upgrade.
  // Use the NEXT_PUBLIC_VENUS_WS_URL env var or default to same-origin.
  const wsBase = process.env.NEXT_PUBLIC_VENUS_WS_URL || "";
  if (wsBase) {
    return `${wsBase}/ws/channels/${encodeURIComponent(channelId)}`;
  }
  // Fallback: construct from window location — Venus is proxied through nginx
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/venus-ws/channels/${encodeURIComponent(channelId)}`;
}
