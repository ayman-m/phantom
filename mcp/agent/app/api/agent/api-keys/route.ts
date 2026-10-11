import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  return proxyToMcp(request, '/api/v1/api_keys');
}

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/api_keys');
}
