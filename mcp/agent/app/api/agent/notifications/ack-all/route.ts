import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

/** Mark every unread notification read. Optional body: { target }. */
export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/notifications/ack_all');
}
