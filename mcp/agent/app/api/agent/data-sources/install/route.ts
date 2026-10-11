/**
 * POST /api/agent/data-sources/install
 *
 * Thin proxy to /api/v1/data-sources/install on the MCP side.
 *
 * Installs a vendor schema (data source) by
 * extracting it from the matching Cortex ModelingRule + persisting
 * to data_sources.db. The MCP side does the extraction itself via
 * the cortex-content connector's public functions — the UI just
 * sends pack_name + rule_name (+ optional dataset_name).
 *
 * Request body:
 *   { pack_name: string, rule_name: string, dataset_name?: string }
 *
 * Response shape (passthrough from MCP):
 *   { ok: bool, data_source_ids: string[], fields_count: number,
 *     datasets_installed: number, datasets_in_rule: number,
 *     pack_version: string | null }
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface InstallBody {
  pack_name?: unknown;
  rule_name?: unknown;
  dataset_name?: unknown;
}

export async function POST(request: NextRequest) {
  let body: InstallBody;
  try {
    body = (await request.json()) as InstallBody;
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const packName = typeof body.pack_name === 'string' ? body.pack_name.trim() : '';
  const ruleName = typeof body.rule_name === 'string' ? body.rule_name.trim() : '';
  if (!packName || !ruleName) {
    return NextResponse.json(
      { error: 'pack_name and rule_name are required (strings)' },
      { status: 400 },
    );
  }
  const datasetName =
    typeof body.dataset_name === 'string' && body.dataset_name.trim()
      ? body.dataset_name.trim()
      : null;

  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const upstreamBody: Record<string, string> = {
    pack_name: packName,
    rule_name: ruleName,
  };
  if (datasetName !== null) {
    upstreamBody.dataset_name = datasetName;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/data-sources/install`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${r.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(upstreamBody),
      cache: 'no-store',
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: 'MCP unreachable',
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  const payload = await upstream.json().catch(() => null);
  if (!upstream.ok) {
    return NextResponse.json(
      payload ?? { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }
  return NextResponse.json(payload, { status: 201 });
}
