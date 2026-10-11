/**
 * Runtime events summary — counts-by-name rollup over the runtime
 * events feed declared in manifest.observability.events. Companion
 * to /api/agent/observability/events. See that file for the rationale
 * on why this is separate from /api/agent/audit.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/observability/events/summary');
}
