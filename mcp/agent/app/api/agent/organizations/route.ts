/**
 * Organizations proxy. The sample organization every generator draws from lives in the MCP's
 * SqliteOrganizationStore; this route is the thin proxy to /api/v1/organizations.
 *
 *   GET  /api/agent/organizations  → {organizations: [meta], active_id, count}
 *   POST /api/agent/organizations  → add one; body {document | text, format?, activate?, replace?}
 *
 * The rest of the surface: [orgId]/route.ts (one organization), [orgId]/[action]/route.ts (activate, fork, changes,
 * export, section, cortex-setup, history, restore) and validate/route.ts.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/organizations');
}

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/organizations');
}
