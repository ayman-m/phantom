---
name: release-tag-flow
description: >-
  Use when preparing a release tag (vX.Y.Z). Walks the capability-complete
  check, the pre-tag docs checklist, the tag itself, and the release notes.
  Prevents tagging half-finished work or skipping the docs that must ship
  with a release.
paths:
  - CHANGELOG.md
  - mcp/agent/lib/release-notes.ts
---

# Release tag flow

Activates when you're editing `CHANGELOG.md` or `mcp/agent/lib/release-notes.ts`. A release tag `vX.Y.Z` versions the whole monorepo: **all images ship together at that one version**.

## Pre-tag: capability-complete check (root CLAUDE.md § Releases)

Tag only when the user-facing capability the release is meant to deliver works end-to-end on a running install, not merely when each commit passes its own checks.

- One concept per release (root § Contained-release discipline): one named scope, one contained docs section, one coherent test surface.
- If a capability spans several commits, the in-between commits get CHANGELOG entries that name their prerequisite role (*"this is a prerequisite for the `<capability>` work; the capability ships in vX.Y.Z"*) and are not tagged on their own.
- Declare the capability's acceptance criteria in the first commit's CHANGELOG entry, and check them off against a running install before tagging.
- Run the pre-deploy gate from the root CLAUDE.md (`tsc`, `lint`, `build`, `pytest`).

## Pre-tag docs checklist (root § Documentation discipline)

Before tagging any `vX.Y.Z`, every backend feature merged since the last release MUST have:

1. **Architecture page reflects reality**: `mcp/agent/app/help/architecture/page.tsx`. Services match `docker compose ps -a`. New services have a section with container name, source path, runtime, host ports, role, **explicit inter-service connections**.
2. **User guide reflects every operator-visible feature**: `mcp/agent/app/help/user/page.tsx`. Tag new content with the introducing version.
3. **User journeys cover every documented flow**: `mcp/agent/lib/journeys.ts`.
4. **Observability surfaces reflect runtime reality**: `mcp/agent/app/observability/`.
5. **Skills page in sync with on-disk skills**: `mcp/agent/app/skills/page.tsx`.
6. **No backend feature without a UI surface (or documented deferral).** No new UI page without a sidebar nav entry in the SAME release.
7. **Release notes describe user-visible deltas in BOTH places.** `CHANGELOG.md` (long-form) + `mcp/agent/lib/release-notes.ts` (3-7 highlights, ~10-15 words each, **newest first**).
8. **Spec drift fixed in the same PR**, not deferred.
9. **MCP tool docstrings in lockstep with UI forms.**

## Tagging

```bash
git tag -a vX.Y.Z -m "vX.Y.Z: <capability>

<one-paragraph description>"
git push origin vX.Y.Z
```

Confirm with the maintainer before tagging: a tag publishes release artifacts.

## After the tag

1. Put the release's CHANGELOG section on the release page as its notes.
2. Check what actually changed against what you claim changed:
   `git diff vX.Y.Z-1..vX.Y.Z -- mcp/agent/app/help mcp/agent/lib/journeys.ts CHANGELOG.md mcp/agent/lib/release-notes.ts`.
3. Tell the reviewer exactly which help-page anchors changed (e.g. `/help/architecture#authentication`, `/help/user#authentication`), so nobody has to hunt.

## Forbidden

- Tagging in-between commits as if they were standalone releases.
- Skipping CHANGELOG entries for in-between commits.
- Claiming docs landed without opening them to confirm.
- Putting developer-only context on operator-facing pages (it belongs in code comments, the architecture page or the CHANGELOG).
