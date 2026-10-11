import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyToMcp(
    request,
    `/api/v1/notifications/${encodeURIComponent(id)}/ack`,
  );
}
