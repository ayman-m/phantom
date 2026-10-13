/**
 * Personality defaults proxy. GET /api/agent/personality/defaults →
 * the MCP's /api/v1/personality/defaults: the bundle default document
 * ({personality: {personalityMd, actionPolicy}}).
 *
 * The personality page carries no defaults of its own. It reads them here
 * to fill any key a stored blob lacks and for its Reset Defaults button, so
 * the MCP's DEFAULT_PERSONALITY stays the one canonical home.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/personality/defaults');
}
