/**
 * Instance health test — runs a real probe against the instance's
 * connector and returns the updated connector_state.
 *
 * Response shape: {instance, probe_implemented, ok?, error?,
 *                   is_auth_error?, connector_state}.
 *
 * For connectors without a wired probe (xsiam) the response includes
 * `probe_implemented: false` so the UI can render an explanatory
 * "no real probe — call a tool to verify" message instead of pretending
 * the test passed.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/instances/${encodeURIComponent(id)}/test`,
  );
}
