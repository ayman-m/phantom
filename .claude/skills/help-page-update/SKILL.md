---
name: help-page-update
description: >-
  Use when editing in-product help pages (architecture, user, journeys). Walks
  the Section / SubSection / anchor-ID component conventions, when to update
  architecture vs user, how to keep both in sync, and the architecture-page-is-
  the-spec discipline.
paths:
  - mcp/agent/app/help/**
---

# Updating help pages

Activates for work in `mcp/agent/app/help/`. Phantom's help pages are the SPEC (architecture) + the user-facing description (user) + the click-path catalog (journeys). They are MANDATORY pre-release docs.

## File responsibilities

| File | Role | When to edit |
|---|---|---|
| `app/help/architecture/page.tsx` | **Canonical spec** — describes target state. When code disagrees with the architecture page, the architecture page wins. | Any backend/architectural change. Add `Implementation gap` subsections for known drift. |
| `app/help/user/page.tsx` | **User-facing description** of every operator-visible feature. Tag with introducing version (e.g. *"Export + Import (v1.1+)"*). | Any UI affordance, page, setting, action type. Update or remove when behavior changes. |
| `app/help/journeys/page.tsx` | **Click-path catalog** — typed journey definitions from `lib/journeys.ts`. | A new operator-visible flow ships; an old flow goes away. |
| `app/help/api/page.tsx` | **REST reference.** | New `/api/agent/*` endpoint or new MCP tool exposed via REST. |

## Section component shape

```tsx
function MyFeature() {
  return (
    <Section id="my-feature" icon="<material-icon>" title="My Feature">
      <p>One-paragraph what it is + why it exists.</p>

      <SubSection icon="<icon>" title="Sub-aspect title">
        <p>Detail.</p>
        <ul className="list-disc pl-6 space-y-1">
          <li><Code>token</Code> — explanation.</li>
        </ul>
      </SubSection>
    </Section>
  );
}
```

Then add to the JSX render list (search for sibling `<MyFeature />`).

## Anchor IDs

- Use `id="<kebab-case>"` matching the URL fragment (e.g. `#data-sources`).
- The contained-release discipline says: one release adds or rewrites EXACTLY ONE anchor. Scattered edits across many sections violates the "one concept = one release" rule.

## When to update architecture vs user

| Change | Architecture | User |
|---|---|---|
| New service in compose | ✓ container name, source, runtime, ports, role, inter-service connections | If operator-visible: yes; else no |
| New REST endpoint | ✓ in `#rest-api` reference | If operator-callable: yes |
| New MCP tool | ✓ in catalog/credential boundary section | If agent-callable from chat: yes |
| New `/observability/<sub>` page | ✓ in `#observability` | ✓ in user-guide observability section |
| New UI affordance | Sometimes (if it touches architecture) | ✓ always |
| New skill | ✓ if it changes architecture | ✓ user-guide skills section |

When in doubt: any new UI surface → user. Any architectural change → architecture.

## Inter-service connections emphasis (root CLAUDE.md)

When documenting a new service or changed wiring, the architecture page MUST include:
- Source service + outgoing port
- Destination service + listening port
- Auth mechanism (bearer? cookie? mTLS? unauthenticated?)
- Failure mode (retries? circuit breaker?)
- Sync vs async

Example: *`phantom-agent` (Next.js, port 3000) → embedded MCP subprocess (Python FastMCP, port 8080) — bearer auth via `MCP_TOKEN`, in-process loopback over HTTPS, ~5s timeout, no retry. The agent proxies every `/api/agent/*` call to the MCP at `/api/v1/*` via [lib/mcp-proxy.ts](../../../mcp/agent/lib/mcp-proxy.ts).*

Boxes-with-labels diagrams are not enough. Drift hides in the wires.

## Spec drift discipline

When the architecture page describes target state the code doesn't yet meet, the gap goes in the section's `Implementation gap` subsection. If you fix one of the listed gaps, remove the corresponding bullet in the same PR — the gap list is a living checklist, not a permanent record.

## Customer-facing surfaces don't carry developer context (Rule 4)

Design context (what we're building toward, why a feature is limited, internal references) goes in code comments OR architecture page OR CHANGELOG — **not on customer-facing UI pages**. The customer-facing path for "how do I reset my password" is `/help/user#authentication`, not a paragraph wedged into `/profile`.

**Practical test**: would a customer who installed the product yesterday be confused by this sentence? If it references roadmap plans, internal mechanics, or "we used to do X but now we do Y," it doesn't belong on a customer-facing page.

## Retire docs + journeys in the SAME release that retires the code (Rule 5)

Stub-comment over silent deletion: a retired journey ID stays in `journeys.ts` as a `// [vX.Y.Z] Retired: <id>. Replaced by <new-id> because <reason>` comment. Same for architecture-page sections.

## After the build

- Tell the reviewer which anchor changed.
- Update `CHANGELOG.md` + `mcp/agent/lib/release-notes.ts` if operator-visible.

See also: [mcp/agent/CLAUDE.md](../../../mcp/agent/CLAUDE.md).
