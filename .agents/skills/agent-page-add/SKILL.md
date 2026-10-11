---
name: agent-page-add
description: >-
  Use when adding or modifying a Next.js page under mcp/agent/app. Walks the
  sidebar-entry discipline, AuthGate wrapping, Material
  3 token usage for theme switching, and observability extension when telemetry
  is involved.
paths:
  - mcp/agent/app/**
  - mcp/agent/components/**
---

# Adding or modifying a Next.js page

Activates for work in `mcp/agent/app/` or `mcp/agent/components/`. Phantom's agent is Next.js 15 App Router with React 19.

## 1. Sidebar entry discipline (MANDATORY)

When you add `app/<new-page>/page.tsx`, edit `components/sidebar.tsx` in the SAME PR. A page that exists on disk + ships in the bundle but isn't reachable from `sidebar.tsx`'s nav tree is **operationally invisible** — the operator can only get there by typing the URL directly.

- Pick the right group: **Command** / **Integration** / **Observability** / **Settings** / **Learn**.
- Pick a Material Symbol icon distinct from siblings.
- Write an inline comment if the entry needs context (e.g. *"entry-point catalog; distinct from /plugins filesystem tree"*).

**Grep test before commit:**

```bash
find mcp/agent/app -maxdepth 3 -name 'page.tsx' | xargs dirname | sort
```

vs the `href:` entries in `components/sidebar.tsx`'s `navEntries`. Every page (except redirects + `[param]` dynamic routes) should appear. If a page is deliberately operator-hidden (e.g. accessed only via a button on another page), document that with a code comment near the page's `export default`.

## 2. AuthGate wrapping

Pages under `app/(main)/**` are gated by `AuthGate` in the layout. Unauthenticated users redirect to `/`. You usually don't need to do anything — the layout handles it. Exceptions: pages under `app/setup/**` and `app/api/auth/**` are unauth-bypass.

## 3. Material 3 token system

Theme switching uses `[data-theme="light"]` attribute selector (NOT a `.light` class). `.dark` is implicit default; light requires explicit `data-theme="light"`.

**Use semantic tokens, NEVER hex literals or dark: prefixes in JSX:**

| Use | Don't use |
|---|---|
| `text-primary`, `text-on-surface`, `text-on-surface-variant` | `text-white`, `text-gray-300`, `dark:text-white` |
| `bg-surface-container`, `bg-surface-container-lowest` | `bg-zinc-900`, `dark:bg-gray-800` |
| `border-outline-variant`, `border-outline` | `border-gray-600`, `border-zinc-700` |
| `var(--m3-primary)` (in inline styles) | `#7aafff` |

The Material 3 token surface auto-routes through CSS variables for theme switching — same DOM, different `--m3-*` values per theme.

## 4. Page conventions

- Use the existing utility classes: `.glass-panel` (semi-transparent + 20px backdrop blur), `.ghost-border` (0.5px subtle outline), `.atmospheric-shadow`, `.skeleton-shimmer` (loading placeholders).
- Material Symbols Outlined for all icons. Pick distinct icons per sidebar group.
- For pages with data fetches: show skeleton shimmer on cold load, glass-pane cards for content, ruby-red modal for destructive actions.

## 5. API route convention

If the page needs a backend, add the route under `app/api/agent/<resource>/route.ts` as a thin proxy to the embedded MCP at `/api/v1/<resource>`. Use [`lib/mcp-proxy.ts`](../../../mcp/agent/lib/mcp-proxy.ts) — don't hand-roll fetch.

```ts
import { proxyToMcp } from "@/lib/mcp-proxy";

export async function GET(req: Request) {
  return proxyToMcp(req, "/api/v1/my-resource");
}
```

The MCP-side handler lives at `bundles/spark/mcp/src/api/<resource>.py`.

## 6. Observability extension

If the new page emits telemetry (events, traces, metrics, cost line items), extend the matching `app/observability/<sub>/page.tsx`. Silent telemetry that doesn't surface in observability is rot waiting to happen.

## 7. Pre-deploy gate (LOCAL to this directory)

```bash
cd mcp/agent
npx tsc --noEmit                  # type-check
npm run lint                      # ESLint
npm run build                     # catches strict route validation
```

Only `npm run build` catches strict Route-type validation. `route.ts` files reject any export beyond the documented HTTP-method handlers + route-config exports.

## 8. After the build

- Update help docs: `app/help/architecture/page.tsx` (if architectural) AND `app/help/user/page.tsx` (always, if operator-visible).
- Add a journey entry in `lib/journeys.ts` if the page introduces a new flow.
- Update `CHANGELOG.md` + `lib/release-notes.ts` with the operator-facing delta.

See also: [mcp/agent/CLAUDE.md](../../../mcp/agent/CLAUDE.md).
