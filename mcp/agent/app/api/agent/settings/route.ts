/**
 * Settings proxy — used by SparkSettingsEditor to load + save the
 * runtime overridable settings declared in manifest.settings.
 *
 *   GET  /api/agent/settings    → describe-store snapshot
 *                                  {defaults, overridable, effective, overrides}
 *   PUT  /api/agent/settings    → bulk set/clear
 *                                  body: {updates, clear, actor}
 *
 * Both endpoints proxy to the embedded MCP's /api/v1/settings,
 * attaching MCP_TOKEN server-side so the browser doesn't need to
 * hold the bundle-internal bearer.
 *
 * `defaultModel` (the install's default chat model) is checked here before it
 * is forwarded: it must name a model the registry accepts, and it is stored as
 * the canonical "provider/model" ref. A name the registry rejects answers 400
 * with `code`, `field` and `suggestions`; nothing is written. A successful
 * write drops the 30 s cache the chat route reads the default through, so the
 * next turn uses the new default.
 */

import { NextResponse } from 'next/server';

import { bustInstallDefaultModelCache, checkModelWrite } from '@/lib/model-registry-server';
import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

async function _resolveMcp(): Promise<{ base: string; token: string } | NextResponse> {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken)
    return NextResponse.json({ error: 'MCP_TOKEN not configured' }, { status: 503 });
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    'http://phantom-mcp:8080/api/v1/stream/mcp';
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base)
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  return { base, token: mcpToken };
}

export async function GET() {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const upstream = await fetch(`${r.base}/api/v1/settings`, {
      headers: { Authorization: `Bearer ${r.token}` },
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'settings GET failed' },
      { status: 502 },
    );
  }
}

export async function PUT(request: Request) {
  const r = await _resolveMcp();
  if (r instanceof NextResponse) return r;
  try {
    const checked = await checkModelWrite('settings', await request.text());
    if (!checked.ok) return NextResponse.json(checked.body, { status: checked.status });
    const body = checked.body;
    const upstream = await fetch(`${r.base}/api/v1/settings`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${r.token}`,
        'Content-Type': 'application/json',
      },
      body,
      signal: AbortSignal.timeout(10000),
    });
    // Any 2xx may have set or cleared defaultModel (207 = some keys applied).
    if (upstream.ok) bustInstallDefaultModelCache();
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'settings PUT failed' },
      { status: 502 },
    );
  }
}
