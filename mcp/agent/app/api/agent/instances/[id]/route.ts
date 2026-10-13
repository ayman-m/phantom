/**
 * Per-instance proxy — GET / PATCH / DELETE one connector instance.
 *
 * GET     → fetch instance + its derived enabled/state (sourced from
 *           connector_state since instance↔connector is 1:1 in
 *           single-tenant Phantom).
 * PATCH   → partial update (name, config, secrets, disabled_tools,
 *           enabled). `{enabled: false}` pauses the instance: the MCP
 *           reloads its tool registry and the connector's tools are no
 *           longer offered to the agent until it is enabled again.
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
