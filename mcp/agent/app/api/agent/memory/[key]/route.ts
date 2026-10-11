/**
 * Per-key memory proxy — phantom's MCP keys memory rows by `key`
 * (per `/api/v1/memories/by-key/{key}`). The route folder is named
 * `[key]` and the destructured param matches, so callers using the
 * memory's `key` field from the list/search responses can address
 * a row directly.
 *
 * The folder is named `[key]` rather than `[id]` so callers pass the
 * memory's `key` field, not the row's UUID `id` (the upstream is keyed
 * by `key`, so a UUID would 404).
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ key: string }> },
) {
  const { key } = await params;
  return proxyToMcp(request, `/api/v1/memories/by-key/${encodeURIComponent(key)}`);
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ key: string }> },
) {
  const { key } = await params;
  return proxyToMcp(request, `/api/v1/memories/by-key/${encodeURIComponent(key)}`);
}
