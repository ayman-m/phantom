# `mcp/agent/` — Phantom Agent (UI + embedded MCP host)

The `phantom-agent` container. Next.js 15 + React 19 (UI on port 3000) with a Python FastMCP subprocess inside the same container (loopback port 8080). TLS terminates at `tls-proxy.js` then forwards to both.

**Repo-wide rules live in the [root CLAUDE.md](../../CLAUDE.md)** — pre-deploy gate, contained-release discipline, documentation discipline, credential guardrail, feature-completeness contract. This file holds only conventions that are LOCAL to `mcp/agent/`.

## Layout

| Path | What it is |
|------|------------|
| `app/` | Next.js App Router. |
| `app/(main)/<feature>/page.tsx` | Operator-facing pages. EVERY new page MUST add a sidebar entry in `components/sidebar.tsx` in the SAME PR. |
| `app/api/agent/*/route.ts` | Thin proxies to the embedded MCP at `/api/v1/*`. Use [`lib/mcp-proxy.ts`](lib/mcp-proxy.ts) — don't hand-roll fetch. |
| `app/help/architecture/page.tsx` | Canonical spec (see root § Architecture page is the spec). |
| `app/help/user/page.tsx` | Operator user guide. |
| `app/observability/<sub>/page.tsx` | Runtime introspection surfaces. New telemetry MUST surface here. |
| `components/sidebar.tsx` | Nav source of truth. Grep test before commit: `find app -maxdepth 3 -name 'page.tsx' | xargs dirname | sort` vs the `href:` entries here — every page (except redirects + `[param]` routes) must appear. |
| `lib/mcp-proxy.ts` | The proxy layer to embedded MCP. Bearer auth via `MCP_TOKEN`. |
| `lib/runtime-config.ts` | TLS detection + base-URL resolution. **Derives from observable filesystem (cert presence), NOT env vars** — see root § Canonical-state discipline Rule 3 (a CLI invoked via `docker exec` does not inherit the entrypoint's env mutations, so it must check the filesystem). |
| `lib/system-prompt.ts` | Agent system prompt assembled at boot. Includes the credential-guardrail refusal recipe. |
| `lib/journeys.ts` | User journeys — every release that adds a flow adds a journey. |
| `lib/release-notes.ts` | Bundled About-modal entries. **Newest entry first.** Every CHANGELOG entry needs a matching entry here in the same PR. |
| `entrypoint.sh` | Container start: TLS proxy + MCP subprocess + Next.js. Skills volume seed runs here. |
| `tls-proxy.js` | Node.js sidecar terminating TLS in front of UI (3000) + MCP (8080). |

## Embedded MCP subprocess

The agent's Next.js side talks to MCP over loopback at `http://localhost:8080/api/v1/stream/mcp`, bearer auth via `MCP_TOKEN` (per-boot random unless externally set). Architecture: see [`bundles/spark/mcp/CLAUDE.md`](../../bundles/spark/mcp/CLAUDE.md) for the Python side.

## Skills bootstrap + per-release marker

`entrypoint.sh` runs a marker-driven auto-merge of image-baked default skills into the persistent `phantom_mcp_skills` volume on every boot. Operators upgrading to a new release automatically see the new release's skills appear in `/skills` — no manual `docker exec` needed.

**Boot logic** (`entrypoint.sh` §1):

| Trigger | Action |
|---|---|
| `FORCE_SKILLS_SYNC=1` env set | Always merge image defaults into the volume; stamp marker |
| Volume empty (fresh install) | Seed; stamp marker |
| `phantom_mcp_skills/.seeded_version` missing OR mismatches `PHANTOM_VERSION` | **Merge image defaults; stamp marker** — the per-release auto-rollout path |
| Marker matches running version | No-op (operator deletions of default skills stick across same-version restarts) |

**The merge is MERGE-not-REPLACE.** Files in image only → copied in. Files in volume only (operator-created) → stay. Files in both → image wins.

To permanently retire an image-default skill, the operator's option today is `docker exec phantom_agent rm /app/skills/<category>/<file>.md` after each upgrade; long-term fix is a bundle-level denylist.

## Auth surfaces

- **UI session**: cookie `phantom_session` (32-byte random server-validated token, not a flat flag), set by `/api/auth/login` after PBKDF2-HMAC-SHA256 password verification. Layout-level `AuthGate` (client-side) controls UI render; `middleware.ts` (server-side) gates every `/api/agent/**` + `/api/chat` + `/api/skills/**` request against the same cookie via `validateSession`.
- **MCP loopback**: bearer `MCP_TOKEN`.
- **Provider auth**: Gemini via `GEMINI_API_KEY`; Vertex AI via `GOOGLE_APPLICATION_CREDENTIALS` (GCP service-account JSON).
- **SecretStore + EnvSecretStore overlay**: at-rest AES-256-GCM with PBKDF2 KDF; env vars in `.env` shadow stored secrets at read time without overwriting them.

## Build-arg toggles

- `ANIMATED` (default `true`) toggles the animated UI variant. Exposed at runtime via `NEXT_PUBLIC_ANIMATED`.

## Pre-deploy gate (LOCAL to this directory)

```bash
cd mcp/agent
npx tsc --noEmit                  # type-check
npm run lint                      # ESLint
npm run build                     # Next.js prod build — catches strict route validation
```

The full pre-deploy gate (incl. pytest) lives in the root CLAUDE.md.

## Sidebar nav discipline

When you add `app/<new-page>/page.tsx`, edit `components/sidebar.tsx` in the SAME PR:
- Pick the right group (Command / Integration / Observability / Settings / Learn).
- Pick a Material Symbol icon distinct from siblings.
- Write an inline comment if the entry needs context (e.g. *"entry-point catalog; distinct from /plugins filesystem tree"*).

If a page is deliberately operator-hidden (accessed only via a button on another page), document that with a code comment near the page's `export default`.

## Material 3 token system

Theme switching uses `[data-theme="light"]` attribute selector (NOT a `.light` class). `.dark` is implicit default; light requires explicit `data-theme="light"`. Use semantic tokens (`text-primary`, `bg-surface-container`, `border-outline-variant`) — they auto-route through CSS variables for theme switching. No `dark:` prefixes; no hex literals in JSX.
