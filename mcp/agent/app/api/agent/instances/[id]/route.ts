/**
 * Per-instance proxy — GET / PATCH / DELETE one connector instance.
 *
 * GET     → fetch instance + its derived enabled/state (sourced from
 *           connector_state since instance↔connector is 1:1 in
 *           single-tenant Phantom).
 * PATCH   → partial update; currently `{enabled: bool}` is the only
 *           supported field. Toggles connector_state.disabled and
 *           gates tool advertisement accordingly.
 * DELETE  → remove the instance row.
 */

import { NextResponse } from 'next/server';

import { instanceSecretsError } from '@/lib/instance-secrets';
import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(request, `/api/v1/instances/${encodeURIComponent(id)}`);
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  // A secret starting with "/" would be read by the MCP as a path to another
  // stored secret; refuse it before it gets there.
  const body = await request.text();
  const error = instanceSecretsError(body);
  if (error) return NextResponse.json({ error }, { status: 400 });
  return proxyToMcp(request, `/api/v1/instances/${encodeURIComponent(id)}`, { body });
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(request, `/api/v1/instances/${encodeURIComponent(id)}`);
}
