/**
 * Personality proxy. The agent persona lives in the MCP's
 * SqlitePersonalityStore (single source of truth shared with the chat-
 * driven self-mod tools). This route is a thin proxy through to
 * /api/v1/personality on the embedded MCP — same shape as
 * /api/agent/settings.
 *
 *   GET  /api/agent/personality  → {personality, updated_at, updated_by, version}
 *   PUT  /api/agent/personality  → replace blob; body = {personality: {...}}
 *
 * Why this is not stored in setup.json:
 *   The Tier-2 self-mod tool `personality_update` mutates persona via
 *   chat. If persona lived in the agent's setup.json (Next.js
 *   process), the MCP tool would have to call back over HTTP — circular
 *   dep. The canonical store lives in the MCP, so the tool can
 *   write directly via the singleton, and the UI is just a viewer.
 *
 * Migration: SqlitePersonalityStore.__init__ checks for an existing
 * setup.json:values.personality on first init and copies it into the
 * SQLite row. Operators don't lose their UI-saved persona. After
 * migration, setup.json:values.personality is a stale shadow — left
 * in place to avoid breaking older readers but no longer authoritative.
 */

import { NextResponse } from "next/server";

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

async function _resolveMcp(): Promise<{ base: string; token: string } | NextResponse> {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || "").trim() || process.env.MCP_TOKEN?.trim() || "";
  if (!mcpToken)
    return NextResponse.json({ error: "MCP_TOKEN not configured" }, { status: 503 });
  const mcpUrl =
    (config.MCP_URL || "").trim() ||
    process.env.MCP_URL?.trim() ||
    "http://phantom-mcp:8080/api/v1/stream/mcp";
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base)
    return NextResponse.json({ error: "bad MCP URL" }, { status: 500 });
  return { base, token: mcpToken };
}

export async function GET() {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const upstream = await fetch(`${r.base}/api/v1/personality`, {
      headers: { Authorization: `Bearer ${r.token}` },
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "personality GET failed" },
      { status: 502 },
    );
  }
}

export async function PUT(request: Request) {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const body = await request.text();
    const upstream = await fetch(`${r.base}/api/v1/personality`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${r.token}`,
        "Content-Type": "application/json",
      },
      body,
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "personality PUT failed" },
      { status: 502 },
    );
  }
}
