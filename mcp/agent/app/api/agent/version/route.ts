/**
 * Running-version proxy.
 *
 * Returns the agent stack's pinned `PHANTOM_VERSION` so the UI can
 * render an authoritative "you're on vX.Y.Z" indicator in the sidebar
 * + the About modal's release-notes view.
 *
 * Also returns per-stack-image digests. The customer compose
 * pins each image by content digest; this endpoint surfaces those
 * digests so the UI (sidebar tooltip, About modal "Image versions"
 * section, /observability/connectors digest column) can show
 * authoritative "what bytes is this container running" info.
 *
 * Source-of-truth resolution:
 *   1. process.env.PHANTOM_VERSION   → version label (set by installer
 *      from /opt/phantom/.env; .env in turn populated from the
 *      release manifest)
 *   2. process.env.DIGEST_PHANTOM_*  → per-image content digests
 *      (same source: installer-managed manifest in .env)
 *   3. fallback "dev" / undefined    → local development image with
 *      no manifest applied
 *
 * The static release-notes history (lib/release-notes.ts) is bundled
 * with the UI image; the API just supplies "what version am I right
 * now" so the modal can highlight the matching entry.
 *
 * For a richer view (per-instance connector digests, GitHub-released
 * manifest comparison, etc.) hit /api/agent/digests instead.
 */

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface VersionResponse {
  version: string;
  /** Per-stack-image content digests (sha256:...). Keys match the
   * compose service names. Undefined on dev builds without an
   * installer-applied manifest. */
  digests?: Record<string, string>;
}

export async function GET() {
  const version =
    process.env.PHANTOM_VERSION?.trim() ||
    process.env.NEXT_PUBLIC_PHANTOM_VERSION?.trim() ||
    'dev';

  // Stack-tier digests, sourced from compose-injected env vars. The
  // customer compose forwards each DIGEST_PHANTOM_* env var into
  // phantom-agent's environment block; those values come from
  // /opt/phantom/.env which was populated by the phantom-installer
  // from the release manifest.
  const digestSources: Record<string, string | undefined> = {
    'phantom-agent': process.env.DIGEST_PHANTOM_AGENT,
    'phantom-xlog': process.env.DIGEST_PHANTOM_XLOG,
    'phantom-caldera': process.env.DIGEST_PHANTOM_CALDERA,
    'phantom-updater': process.env.DIGEST_PHANTOM_UPDATER,
    'phantom-browser': process.env.DIGEST_PHANTOM_BROWSER,
  };

  const digests: Record<string, string> = {};
  for (const [svc, val] of Object.entries(digestSources)) {
    if (val && val.startsWith('sha256:')) {
      digests[svc] = val;
    }
  }

  const body: VersionResponse = { version };
  if (Object.keys(digests).length > 0) {
    body.digests = digests;
  }
  return NextResponse.json(body);
}
