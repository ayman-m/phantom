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
 */
export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/instances');
}
