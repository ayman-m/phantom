import { NextResponse } from 'next/server';

import { agentContract } from '@/lib/agent-contract';
import { getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

type ProbeResult = {
  id: string;
  url: string;
  status: 'ok' | 'failed' | 'skipped';
  httpStatus?: number;
  latencyMs?: number;
  error?: string;
};

function mcpPingUrl(mcpUrl: string) {
  try {
    const url = new URL(mcpUrl);
    url.pathname = '/ping/';
    url.search = '';
    return url.toString();
  } catch {
    return 'http://phantom-mcp:8080/ping/';
  }
}

async function probe(id: string, url: string): Promise<ProbeResult> {
  if (!url) {
    return {
      id,
      url,
      status: 'skipped',
    };
  }

  const startedAt = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(url, {
      cache: 'no-store',
      signal: controller.signal,
    });
    return {
      id,
      url,
      status: response.ok ? 'ok' : 'failed',
      httpStatus: response.status,
      latencyMs: Date.now() - startedAt,
    };
  } catch (error) {
    return {
      id,
      url,
      status: 'failed',
      latencyMs: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET() {
  const runtimeConfig = await getEffectiveRuntimeConfig();
  // Self-probe: the agent has to reach its OWN /api/auth/status. In TLS
  // mode (TLS is the default), public 3000 is the HTTPS proxy
  // and Next.js binds the loopback HTTP port 3001 — so an HTTP probe to
  // localhost:3000 fails the TLS handshake. The entrypoint exports
  // PHANTOM_AGENT_INTERNAL_URL=http://127.0.0.1:3001 specifically for
  // in-process round-trips like this; honor it and fall back to the
  // legacy URL for non-TLS deploys.
  const selfBase =
    process.env.PHANTOM_AGENT_INTERNAL_URL?.trim() ||
    'http://localhost:3000';
  const probes = await Promise.all([
    probe('xlog-api', `${runtimeConfig.XLOG_URL.replace(/\/$/, '')}/health`),
    probe('phantom-mcp', mcpPingUrl(runtimeConfig.MCP_URL)),
    probe('phantom-agent', `${selfBase.replace(/\/$/, '')}/api/auth/status`),
    probe('caldera', `${runtimeConfig.CALDERA_URL.replace(/\/$/, '')}/`),
  ]);

  const failed = probes.filter((result) => result.status === 'failed');
  const status = failed.length === 0 ? 'ok' : failed.length === probes.length ? 'failed' : 'degraded';

  return NextResponse.json(
    {
      agentId: agentContract.metadata.id,
      status,
      // There is no setup page. setupRequired stays in the
      // payload as a constant `false` for API back-compat (callers
      // that still read this field shouldn't break).
      setupRequired: false,
      checkedAt: new Date().toISOString(),
      probes,
    },
    { status: status === 'failed' ? 503 : 200 }
  );
}
