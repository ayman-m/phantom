/**
 * Next.js middleware — server-side session-cookie enforcement for all
 * agent-control surfaces.
 *
 * # Threat model
 *
 * AuthGate (`components/auth/auth-gate.tsx`) only decides what the BROWSER
 * renders; it imposes no protection on the server-side API. Any caller that
 * reaches port 3000 — by VM lateral movement, misconfigured firewall,
 * accidentally-exposed cloud LB, container escape — could otherwise POST
 * `/api/agent/memory`, `/api/agent/jobs`, `/api/chat`, `/api/skills`, etc.
 * without credentials. The network boundary must not be the only auth gate.
 *
 * This middleware therefore enforces a session-cookie check at the SERVER
 * tier. Same `phantom_session` cookie AuthGate reads on the client; same
 * `validateSession` call the `/api/auth/status` route makes. The cookie's
 * value must validate against the MCP-side session store; absence OR invalid
 * value → 401 JSON.
 *
 * # Coverage
 *
 * The matcher (see `config.matcher` below) targets every server endpoint that
 * exposes the agent or its data:
 *
 *   /api/agent/**   — 84 routes including memory, jobs, hooks, sessions,
 *                     skills CRUD, tool dispatch, secrets-adjacent metadata
 *   /api/chat       — kicks off a full LLM turn with real tool calls
 *   /api/skills/**  — skill CRUD outside the /api/agent/ prefix
 *
 * `/api/auth/*` is INTENTIONALLY excluded — login can't require login, and
 * AuthGate polls `/api/auth/status` BEFORE any cookie exists.
 *
 * `/api/marketplace/connectors` and `/api/marketplace/connectors/[id]` are
 * ALSO intentionally excluded (silently — they're outside the `/api/agent/`
 * prefix). They serve hardcoded read-only connector catalog JSON: no
 * secrets, no mutation surface, no credential access. Leaving them open
 * lets pre-login pages render the marketplace card list. **If these routes
 * ever grow write handlers, extend the matcher to cover them in the same
 * PR** — the silent exclusion becomes dangerous the moment they mutate.
 *
 * # Exemptions (paths the matcher hits but cookie-check skips)
 *
 *   /api/agent/health           — Docker compose healthcheck calls this
 *                                  from inside the container with no cookies.
 *                                  Gating it makes the container unhealthy.
 *
 *   /api/agent/internal/fire-hook — Called by the embedded MCP subprocess,
 *                                  uses `MCP_TOKEN` bearer (not the session
 *                                  cookie). Has its own auth layer. Gating
 *                                  it with a session check would break hook
 *                                  dispatch.
 *
 * # Edge runtime
 *
 * Next.js 15.1.6 — middleware runs on the Edge runtime (Node.js runtime is
 * GA in 15.2+). `validateSession` uses only `fetch` + in-memory cache, so it
 * works in Edge. `mcpPost` resolves the MCP URL from runtime-config, which
 * also only uses fetch.
 *
 * # Performance
 *
 * `validateSession` has a 30-second positive cache (in-memory Map inside
 * `lib/auth-store.ts`). First request per cookie: one fetch to the embedded
 * MCP's `/api/v1/ui/auth/session` (~10ms loopback). Cached requests: 0 ms.
 * Negative results NOT cached (revocation must surface immediately).
 */

import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";
import { validateSession, validateApiKey } from "@/lib/auth-store";
import {
  requiredScope,
  isCredentialRoute,
  scopeSatisfied,
} from "@/lib/agent-scopes";

// Paths the matcher catches that should bypass the session check entirely.
// Kept as a Set so the membership check is O(1) per request.
const EXEMPT_PATHS = new Set<string>([
  "/api/agent/health",
  "/api/agent/internal/fire-hook",
]);

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;

  if (EXEMPT_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  // API-key bearer path — checked BEFORE the cookie. An
  // `Authorization: Bearer phantom_ak_*` authenticates programmatic
  // clients; absence falls through to the session-cookie path below
  // (human UI auth). Coarse scopes gate
  // read vs write; credential-management routes are denied even with
  // `agent:*` (security invariant — those stay session-only).
  const authz = request.headers.get("authorization") ?? "";

  // Internal-service auth — the embedded MCP subprocess calls
  // back into the agent (the job scheduler firing a scheduled prompt via
  // /api/chat) using the container's MCP_TOKEN as a bearer, the same
  // loopback trust the exempt /api/agent/internal/* routes use. MCP_TOKEN
  // is the per-boot agent↔MCP secret, never exposed to the browser; a
  // caller that already holds it has full embedded-MCP access, so honoring
  // it here doesn't widen the trust boundary. Credential-management routes
  // stay blocked (same invariant as API keys). Scheduled prompt jobs
  // depend on this path: they carry no session cookie.
  const internalToken = process.env.MCP_TOKEN?.trim();
  if (internalToken && authz === `Bearer ${internalToken}`) {
    if (isCredentialRoute(pathname)) {
      return NextResponse.json(
        { error: "forbidden", code: "internal_token_credential_route_forbidden" },
        { status: 403 },
      );
    }
    return NextResponse.next();
  }

  if (authz.toLowerCase().startsWith("bearer phantom_ak_")) {
    const apiKey = authz.slice("bearer ".length).trim();
    const keyResult = await validateApiKey(apiKey);
    if (!keyResult.valid) {
      return NextResponse.json(
        { error: "unauthenticated", code: keyResult.reason },
        { status: 401 },
      );
    }
    if (isCredentialRoute(pathname)) {
      return NextResponse.json(
        { error: "forbidden", code: "api_key_credential_route_forbidden" },
        { status: 403 },
      );
    }
    const needed = requiredScope(pathname, request.method);
    if (!scopeSatisfied(keyResult.scopes, needed)) {
      return NextResponse.json(
        { error: "forbidden", code: "insufficient_scope", required: needed },
        { status: 403 },
      );
    }
    return NextResponse.next();
  }

  const cookie = request.cookies.get(SESSION_COOKIE_NAME);
  const token = cookie?.value;
  if (!token) {
    return NextResponse.json(
      { error: "unauthenticated", code: "no_session_cookie" },
      { status: 401 },
    );
  }

  // validateSession returns { valid: true, ... } | { valid: false, reason }.
  // Anything other than `valid: true` → 401. The reason is included in the
  // body so operators debugging "why am I getting 401" see the actual cause.
  const result = await validateSession(token);
  if (!result.valid) {
    return NextResponse.json(
      { error: "unauthenticated", code: result.reason },
      { status: 401 },
    );
  }

  return NextResponse.next();
}

// Next.js requires `matcher` to be statically analyzable — string literals,
// no template strings or computed values. The two distinct prefix patterns
// below cover /api/agent/**, /api/chat, /api/skills + /api/skills/**.
export const config = {
  matcher: [
    "/api/agent/:path*",
    "/api/chat",
    "/api/chat/:path*",
    "/api/skills",
    "/api/skills/:path*",
  ],
};
