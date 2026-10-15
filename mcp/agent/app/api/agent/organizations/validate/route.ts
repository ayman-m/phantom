/**
 * POST /api/agent/organizations/validate → {valid, errors, warnings} for {document | text, format?}.
 * Checks an organization without saving it; the editor calls it as the operator types.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/organizations/validate');
}
