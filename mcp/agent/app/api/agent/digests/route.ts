/**
 * Comprehensive image-digest reporter.
 *
 * Returns ALL pinning information for the running stack:
 *   - Stack-tier images (5 services) with their pinned digests
 *     sourced from compose-injected DIGEST_PHANTOM_* env vars
 *   - Per-instance connector containers, queried from phantom-updater
 *     so we get accurate "what's actually running" info per instance
 *     (rather than what the manifest says SHOULD be running)
 *
 * Used by:
 *   - /observability/connectors panel (digest column per service +
 *     per-instance connector)
 *   - About modal's "Image versions" section
 *   - Audit / debugging — the response is reproducible across reboots
 *     for any given .env state, so operators can include it verbatim
 *     in incident reports.
 *
 * Difference from /api/agent/version:
 *   - /api/agent/version is the lightweight endpoint hit on every
 *     sidebar render. Synchronous, env-only, no upstream calls.
 *   - /api/agent/digests is the rich endpoint hit on demand
 *     (observability page open, About modal expanded). Async, may
 *     proxy to phantom-updater for per-instance info, can be slower.
 *
 * Auth surface: same cookie-based auth as the rest of /api/agent/*.
 * The phantom-updater query uses the same MCP_TOKEN proxying pattern
 * as other /api/agent/* → updater calls.
 */

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface StackImageDigest {
  service: string;
  /** sha256:... — the pinned content digest from the manifest, OR
   * null if the env var isn't set (install without a manifest, or dev mode). */
  digest: string | null;
  /** True iff the digest is set and well-formed. Drives the UI's
   * "digest-pinned" vs "tag-pinned (legacy)" badge. */
  pinned: boolean;
}

interface ConnectorInstanceDigest {
  connector_id: string;
  instance_id: string;
  instance_name: string;
  /** sha256:... — the digest the running container is pinned to.
   * Null if the per-instance container is not running, or if the
   * connector instance is in tag-fallback mode (DIGEST_PHANTOM_CONNECTOR_*
   * env not present in updater's environment). */
  digest: string | null;
  /** The digest the install pins for this connector (connector-digests.env);
   * null for an uploaded connector, which has no pin. */
  pinned_digest?: string | null;
  /** True when the running digest differs from the pin: the container is
   * stale and the updater's drift sweep has not recreated it yet. */
  drift?: boolean;
  /** "cached" when the registry pull failed at start and a local copy ran
   * (surfaces as a "cached image" chip); null for containers that predate
   * the phantom.image_pull label. */
  image_pull?: 'pulled' | 'cached' | null;
  /** "digest" (canonical) or "tag" (fallback — should never happen
   * on a clean install; surfaces as a yellow warning badge
   * in /observability/connectors). */
  pinning_mode: 'digest' | 'tag';
  /** The image ref actually used for `docker run`, e.g.
   * "ghcr.io/.../phantom-connector-xlog-oss@sha256:..." */
  image_ref: string;
}

interface DigestsResponse {
  version: string;
  /** ISO timestamp of when the response was generated. */
  generated_at: string;
  /** Per-stack-service digests (5 entries: phantom-agent, xlog,
   * caldera, phantom-updater, phantom-browser). */
  stack: StackImageDigest[];
  /** Per-instance connector container digests. Empty array if the
   * operator hasn't created any connector instances OR if the
   * phantom-updater query failed (in which case `connectors_error`
   * is set and the UI shows a soft error state). */
  connectors: ConnectorInstanceDigest[];
  /** If the connectors query failed, the human-readable reason.
   * Only set when `connectors` is empty due to error. */
  connectors_error?: string;
}

const STACK_SERVICE_TO_ENV: Array<[string, string]> = [
  ['phantom-agent', 'DIGEST_PHANTOM_AGENT'],
  ['phantom-xlog', 'DIGEST_PHANTOM_XLOG'],
  ['phantom-caldera', 'DIGEST_PHANTOM_CALDERA'],
  ['phantom-updater', 'DIGEST_PHANTOM_UPDATER'],
  ['phantom-browser', 'DIGEST_PHANTOM_BROWSER'],
];

export async function GET() {
  const version =
    process.env.PHANTOM_VERSION?.trim() ||
    process.env.NEXT_PUBLIC_PHANTOM_VERSION?.trim() ||
    'dev';

  // Stack-tier: synchronous env lookup. Cheap, always succeeds.
  const stack: StackImageDigest[] = STACK_SERVICE_TO_ENV.map(([svc, envVar]) => {
    const raw = process.env[envVar]?.trim();
    const digest = raw && raw.startsWith('sha256:') ? raw : null;
    return { service: svc, digest, pinned: digest !== null };
  });

  // Per-instance connectors: query phantom-updater. The updater knows
  // both the env-var-pinned digests AND the actual `docker inspect`
  // result for each running container, so it's the authoritative
  // source. If the updater is unreachable (network blip, container
  // restarting), we degrade gracefully — return empty connectors[]
  // with an error message rather than 500'ing the whole response.
  let connectors: ConnectorInstanceDigest[] = [];
  let connectorsError: string | undefined;

  try {
    const updaterUrl =
      process.env.PHANTOM_UPDATER_URL?.replace(/\/$/, '') ||
      'http://phantom-updater:8090';
    const mcpToken = process.env.MCP_TOKEN || '';
    const r = await fetch(`${updaterUrl}/api/v1/connectors/digests`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${mcpToken}`,
        Accept: 'application/json',
      },
      // Short timeout — the updater is on the same docker network,
      // any roundtrip beyond ~3s is likely a hung-container scenario
      // we should surface as an error rather than wait on.
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) {
      throw new Error(`updater returned ${r.status}`);
    }
    const body = (await r.json()) as { connectors?: ConnectorInstanceDigest[] };
    if (Array.isArray(body.connectors)) {
      connectors = body.connectors;
    }
  } catch (e) {
    connectorsError =
      e instanceof Error ? e.message : 'unknown updater error';
  }

  const response: DigestsResponse = {
    version,
    generated_at: new Date().toISOString(),
    stack,
    connectors,
  };
  if (connectorsError) {
    response.connectors_error = connectorsError;
  }
  return NextResponse.json(response);
}
