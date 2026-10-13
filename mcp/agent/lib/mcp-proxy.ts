/**
 * Shared helpers for /api/agent/* proxy routes that forward to the
 * embedded MCP at /api/v1/* with bearer auth attached server-side.
 *
 * Pattern: every proxy route has the same boilerplate (resolve
 * MCP_URL + token, forward the request, pass response through).
 * This module centralizes it so each route file is just 5 lines.
 */

import { NextResponse } from 'next/server';

import { deriveMcpBaseUrl, getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export interface McpResolved {
  base: string;
  token: string;
}

/**
 * Resolve the MCP base URL + bearer token. Returns either the
 * resolved values or a NextResponse error to return immediately.
 */
export async function resolveMcp(): Promise<McpResolved | NextResponse> {
  const config = await getEffectiveRuntimeConfig();
  const mcpToken =
    (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
  if (!mcpToken) {
    return NextResponse.json(
      { error: 'MCP_TOKEN not configured' },
      { status: 503 },
    );
  }
  const mcpUrl =
    (config.MCP_URL || '').trim() ||
    process.env.MCP_URL?.trim() ||
    // Fallback URL: the MCP runs as a subprocess inside
    // `phantom-agent` listening on localhost:8080. The fallback only
    // fires when both config.MCP_URL AND process.env.MCP_URL are
    // unset, which is rare since the installer always sets the env
    // var.
    // entrypoint.sh also flips the scheme to https:
    // when TLS_CERT_PEM is set; but the literal default below stays
    // http: because that's what the compose env sets.
    'http://localhost:8080/api/v1/stream/mcp';
  const base = deriveMcpBaseUrl(mcpUrl);
  if (!base) {
    return NextResponse.json({ error: 'bad MCP URL' }, { status: 500 });
  }
  return { base, token: mcpToken };
}

/**
 * Query parameters a caller may never smuggle through this proxy.
 *
 * `include_secrets` flips the MCP's redaction off and returns resolved
 * plaintext credentials. On the MCP side its only gate is `_is_loopback()`
 * — and this proxy IS loopback (MCP_URL is http://localhost:8080), so every
 * hop through here satisfies that check on the caller's behalf. Forwarding
 * the raw query string therefore turned any external caller into a trusted
 * local one: a confused deputy that leaked real Splunk HEC tokens, webhook
 * bearers and connector secrets to anyone holding an agent:read API key.
 *
 * Stripping here rather than in middleware is deliberate. Middleware guards
 * by PATH PREFIX, but this capability is reachable from ANY route that
 * proxies to the MCP — so a prefix denylist silently widens every time a new
 * proxy route is added. This function is the one place all of that traffic
 * converges.
 *
 * Nothing legitimate is broken: no client or route obtains secrets through
 * this proxy. The three server-side readers (backup, vertex-credentials,
 * providers/credentials) each build their own URL against the MCP base with
 * MCP_TOKEN and never call proxyToMcp.
 */
const FORBIDDEN_UPSTREAM_PARAMS = ["includesecrets"];

function sanitizeSearch(search: string): string {
  if (!search) return search;
  const params = new URLSearchParams(search);
  let stripped = false;
  for (const key of [...params.keys()]) {
    // Normalize so include_secrets / include-secrets / includeSecrets all match.
    const norm = key.toLowerCase().replace(/[_-]/g, "");
    if (FORBIDDEN_UPSTREAM_PARAMS.includes(norm)) {
      params.delete(key);
      stripped = true;
    }
  }
  if (!stripped) return search;
  const rest = params.toString();
  return rest ? `?${rest}` : "";
}

/**
 * Forward a request to the MCP, preserving query string + body.
 * `path` is the /api/v1/* portion (e.g. "/api/v1/audit" or
 * "/api/v1/jobs/foo/run"). Returns a NextResponse.
 */
export async function proxyToMcp(
  request: Request,
  path: string,
  options: { method?: string; body?: string | null } = {},
): Promise<NextResponse> {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  const url = new URL(request.url);
  const upstreamUrl = `${r.base}${path}${sanitizeSearch(url.search)}`;
  const method = options.method ?? request.method;

  // For non-GET methods, forward the request body unless an explicit
  // body is given. For GETs we don't propagate body (HTTP semantics).
  let body: string | null = null;
  if (options.body !== undefined) {
    body = options.body;
  } else if (method !== 'GET' && method !== 'HEAD') {
    try {
      body = await request.text();
    } catch {
      body = null;
    }
  }

  const headers: Record<string, string> = {
    Authorization: `Bearer ${r.token}`,
  };
  const ct = request.headers.get('content-type');
  if (ct && body !== null) {
    headers['Content-Type'] = ct;
  } else if (body !== null) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const resp = await fetch(upstreamUrl, {
      method,
      headers,
      body: body !== null ? body : undefined,
      signal: AbortSignal.timeout(15000),
    });
    const text = await resp.text();
    return new NextResponse(text, {
      status: resp.status,
      headers: {
        'Content-Type':
          resp.headers.get('content-type') ?? 'application/json',
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'proxy fetch failed' },
      { status: 502 },
    );
  }
}

/**
 * Server-initiated REST call to the embedded MCP. Use this when an
 * agent route needs to talk to the MCP without forwarding an
 * inbound request — for example, /api/chat creating + appending to
 * a session as a side effect of a model turn.
 *
 * Returns the parsed JSON response on 2xx, throws on non-2xx or
 * network failure. Callers should treat this as best-effort and
 * decide per-call whether to fail hard or continue.
 *
 * Differences from `proxyToMcp`:
 *   - No inbound Request to forward; you supply method + body
 *   - Returns parsed JSON (callers don't need to re-parse)
 *   - Throws instead of returning a NextResponse (chat-route style)
 */
export async function callMcpServer<T = unknown>(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    timeoutMs?: number;
    /**
     * Custom headers merged into the request. Reserved names
     * (Authorization, Content-Type) take precedence over extras
     * to keep the bearer + JSON contract intact. Used by the
     * chat route to forward X-Phantom-Trigger so MCP-side audit
     * rows inherit the trigger tag.
     */
    headers?: Record<string, string>;
  } = {},
): Promise<T> {
  const r = await resolveMcp();
  if (r instanceof NextResponse) {
    // resolveMcp returns NextResponse only on missing config — surface
    // that as a thrown error so chat-route can catch + log + continue.
    const detail = await r.json().catch(() => ({}));
    throw new Error(
      `MCP unavailable: ${(detail as { error?: string })?.error ?? 'misconfigured'}`,
    );
  }
  const { base, token } = r;
  const method = init.method ?? 'GET';
  const body =
    init.body === undefined
      ? undefined
      : typeof init.body === 'string'
        ? init.body
        : JSON.stringify(init.body);
  // Spread extras first so reserved names cleanly override.
  const headers: Record<string, string> = { ...(init.headers ?? {}) };
  headers['Authorization'] = `Bearer ${token}`;
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  const resp = await fetch(`${base}${path}`, {
    method,
    headers,
    body,
    signal: AbortSignal.timeout(init.timeoutMs ?? 10000),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`MCP ${method} ${path} → ${resp.status} ${text}`);
  }
  return (await resp.json()) as T;
}
