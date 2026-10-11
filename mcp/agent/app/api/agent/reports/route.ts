import { NextRequest, NextResponse } from 'next/server';

import { resolveXlogUrlFromStore } from '@/lib/xlog-url';

export const dynamic = 'force-dynamic';

async function proxyPhantom(path: string) {
  // Read the xlog URL from the InstanceStore (single source of
  // truth, set via /connectors). Falls back to env only when no
  // primary-xlog instance is configured yet (pre-setup window).
  // Reading process.env.XLOG_URL directly would diverge from the
  // operator-configured baseUrl after a TLS rollout.
  const fromStore = await resolveXlogUrlFromStore();
  // Default fallback is https. xlog serves
  // HTTPS on port 8000 unconditionally (mounts /tls/cert.pem from the
  // shared phantom_tls volume; uses TLS in its _resolve_ssl_args
  // priority 1). NODE_EXTRA_CA_CERTS=/tls/cert.pem in the Next.js
  // process trusts the self-signed cert; SAN covers "xlog" hostname.
  // Hitting http://xlog:8000 returns "Empty reply from
  // server" (TLS handshake on plain HTTP).
  const xlogUrl = fromStore || process.env.XLOG_URL || 'https://xlog:8000';

  // xlog/app/auth.py validates `Authorization: <XLOG_API_KEY>` (raw
  // token, not Bearer-prefixed — same shape phantom-agent's other
  // xlog callers use). XLOG_API_KEY is supplied via .env (compose).
  // The aliased XLOG_API_TOKEN env var also works.
  const xlogToken =
    process.env.XLOG_API_KEY || process.env.XLOG_API_TOKEN || '';
  const headers: Record<string, string> = {};
  if (xlogToken) headers.Authorization = xlogToken;

  try {
    const response = await fetch(`${xlogUrl.replace(/\/$/, '')}${path}`, {
      cache: 'no-store',
      headers,
    });
    const contentType =
      response.headers.get('content-type') || 'application/json';
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: {
        'content-type': contentType,
      },
    });
  } catch (err) {
    // Surface the upstream connection failure verbatim — same
    // principle as the connector probes: no silent self-healing,
    // no guesswork. If the operator's stored baseUrl is wrong (e.g.
    // http:// against an HTTPS-only xlog after a TLS rollout), the
    // error here points at exactly the URL that was used so they
    // can update via /connectors.
    const detail = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      {
        error: `Reports proxy failed: ${detail}`,
        target: `${xlogUrl}${path}`,
        hint:
          "Update the xlog instance's baseUrl via /connectors if " +
          'the protocol or hostname is stale.',
      },
      { status: 502 },
    );
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const report = searchParams.get('report') || 'coverage';
  const simulationId = searchParams.get('simulationId');
  const format = searchParams.get('format') || 'json';

  if (report === 'coverage') {
    return proxyPhantom('/api/v1/coverage-report');
  }

  if (report === 'simulation-export' && simulationId) {
    return proxyPhantom(`/api/v1/simulations/${encodeURIComponent(simulationId)}/export?format=${encodeURIComponent(format)}`);
  }

  return NextResponse.json(
    {
      error: 'Unsupported report request',
      supported: [
        { report: 'coverage' },
        { report: 'simulation-export', required: ['simulationId'], optional: ['format'] },
      ],
    },
    { status: 400 }
  );
}
