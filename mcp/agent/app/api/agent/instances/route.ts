import { NextResponse } from 'next/server';

import { instanceSecretsError } from '@/lib/instance-secrets';
import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/instances');
}

/**
 * Create a connector instance.
 *
 * Body shape: {connector_id, name, config?, secrets?}. Mirrors the
 * setup-form materialization but for ad-hoc additions from the UI's
 * "+ Create Instance" button.
 *
 * A secret starting with "/" is refused here (400) before it reaches the MCP,
 * which would read it as a path to another stored secret.
 */
export async function POST(request: Request) {
  const body = await request.text();
  const error = instanceSecretsError(body);
  if (error) return NextResponse.json({ error }, { status: 400 });
  return proxyToMcp(request, '/api/v1/instances', { body });
}
