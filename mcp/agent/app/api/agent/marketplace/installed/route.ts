/**
 * GET /api/agent/marketplace/installed
 *
 * Thin proxy to the MCP marketplace catalogue.
 *
 * The marketplace state has ONE source of truth
 * (`bundles/spark/mcp/src/api/marketplace.py`),
 * which carries the install row + instances_count per entry
 * in its catalogue response. This handler just unwraps that response
 * into the shape the UI client expects.
 *
 * Response shape preserved for backward compat with the UI client
 * (`lib/api/marketplace.ts:listInstalledConnectors`):
 *   { data: [{ id, connector_id, version, execution_mode }, ...] }
 *
 * Source of "installed": the MCP returns one catalogue
 * entry per connector with `installed: true|false`. We filter to
 * `installed === true` here. Instances do not implicitly imply
 * installed (install is the functional gate).
 */

import { NextResponse } from 'next/server';

import { resolveMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

interface MarketplaceConnectorRow {
  id?: unknown;
  installed?: unknown;
  install?: unknown;
}

interface MarketplaceEnvelope {
  connectors?: MarketplaceConnectorRow[];
}

interface InstalledRow {
  id: string;
  connector_id: string;
  version: string;
  execution_mode: string;
}

export async function GET() {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  let upstream: Response;
  try {
    upstream = await fetch(`${r.base}/api/v1/marketplace`, {
      headers: { Authorization: `Bearer ${r.token}` },
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

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `MCP returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  let payload: MarketplaceEnvelope;
  try {
    payload = (await upstream.json()) as MarketplaceEnvelope;
  } catch {
    return NextResponse.json(
      { error: 'MCP returned non-JSON marketplace payload' },
      { status: 502 },
    );
  }

  const installed: InstalledRow[] = [];
  for (const row of payload.connectors ?? []) {
    if (row.installed !== true) continue;
    const id = typeof row.id === 'string' ? row.id : null;
    if (!id) continue;
    const install =
      row.install && typeof row.install === 'object'
        ? (row.install as Record<string, unknown>)
        : null;
    const version =
      install && typeof install.version === 'string'
        ? install.version
        : 'bundled';
    installed.push({
      id,
      connector_id: id,
      version,
      // `execution_mode: "embedded"` is a legacy sentinel the UI's
      // version-comparison logic treats as "no upgrade available".
      // Kept until the UI is updated to read directly from the
      // marketplace envelope.
      execution_mode: 'embedded',
    });
  }

  return NextResponse.json({ data: installed });
}
