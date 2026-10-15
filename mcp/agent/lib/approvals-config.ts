/**
 * Lazy-cached lookup of `manifest.approvals.humanRequired[]` for the
 * chat route. The set tells the chat handler which MCP tools require
 * a human approval before execution — when the agent calls one of
 * these, the chat stream emits an `approval_pending` SSE event so
 * the UI can render an inline approval card while the tool call
 * blocks on the bus's wait_async.
 *
 * Sources (tried in order):
 *   1. /app/bundle/manifest.yaml         (containerized deploy)
 *   2. process.env.PHANTOM_BUNDLE_ROOT/manifest.yaml
 *   3. MCP /api/v1/manifest_approvals    (future — not yet exposed
 *                                          as REST; today the manifest
 *                                          file is always reachable)
 *
 * Cache lifetime: process. The manifest is immutable at runtime per
 * spec.md §7.3 — the bundle's contract doesn't change between
 * redeploys, and a redeploy spawns a fresh process. So caching for
 * the lifetime of the Next.js worker is safe.
 *
 * Risk-tier mapping is duplicated here from manifest semantics:
 * keys whose names match the self-modification patterns get classified as
 * "soft" / "destructive" / "credential" so the chat-route SSE event
 * carries the right tier without fetching it from each approval row.
 * (The MCP-side bus authoritatively records `risk_tier`; this helper's
 * classification is for the chat route's pre-execution UI hint.)
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';

import yaml from 'js-yaml';

let _cache:
  | { humanRequired: Set<string>; loadedAt: number }
  | null = null;

/** What the install gates, read from the manifest. `known` is false
 *  when no manifest could be read — an unreadable manifest is NOT the
 *  same as an empty list, and callers that describe the gate to the
 *  operator or the model must not report "nothing is gated" for it. */
export interface ApprovalGating {
  gated: string[];
  known: boolean;
}

// Tools the UI should render with the "soft" risk-tier styling
// (yellow/amber). Mirrors the manifest's humanRequired list, since
// the same gate is what makes a tool "soft" in operator perception.
//
// caldera_create_operation + xsiam_send_webhook_log are not listed, to match the
// manifest — approval is self-mod-only, so caldera ops
// and xsiam log pushes shouldn't render as "this needs approval".
const SOFT_TOOLS = new Set([
  'jobs_create',
  'jobs_update',
  'jobs_run_now',
  'personality_update',
  // personality_patch is the agent-facing name for the
  // atomic-merge variant of personality_update. classifyRiskTier()
  // reads the tool name as Gemini called it, which is
  // `personality_patch`. Without this entry, classify would return
  // 'unknown' for patches and the approval card would fall back to
  // neutral styling instead of the soft-tier yellow banner.
  // Manifest's humanRequired lists `personality_patch` explicitly;
  // SOFT_TOOLS mirrors it here.
  'personality_patch',
  'organization_update',
  'organization_activate',
  'settings_update',
  'notifications_dismiss',
  'notifications_dismiss_all',
  'approvals_resolve',
]);

const DESTRUCTIVE_TOOLS = new Set([
  'jobs_delete',
  'skills_delete',
  'personality_reset',
  'settings_reset',
  'instances_delete',
  'providers_delete',
]);

const CREDENTIAL_TOOLS = new Set([
  'api_keys_create',
  'api_keys_rotate',
  'api_keys_revoke',
]);

export type RiskTier = 'soft' | 'destructive' | 'credential' | 'unknown';

export function classifyRiskTier(toolName: string): RiskTier {
  if (CREDENTIAL_TOOLS.has(toolName)) return 'credential';
  if (DESTRUCTIVE_TOOLS.has(toolName)) return 'destructive';
  if (SOFT_TOOLS.has(toolName)) return 'soft';
  return 'unknown';
}

const CANDIDATE_PATHS = [
  '/app/bundle/manifest.yaml',
  // Inside the agent container the bundle is also reachable via the
  // BUNDLE_ROOT env var the MCP uses — same convention.
  process.env.PHANTOM_BUNDLE_ROOT
    ? path.join(process.env.PHANTOM_BUNDLE_ROOT, 'manifest.yaml')
    : null,
  // Local dev: workspace root.
  path.resolve(process.cwd(), '../../bundles/spark/manifest.yaml'),
  path.resolve(process.cwd(), 'bundles/spark/manifest.yaml'),
].filter(Boolean) as string[];

async function _readHumanRequired(): Promise<{ set: Set<string>; known: boolean }> {
  for (const p of CANDIDATE_PATHS) {
    try {
      const raw = await readFile(p, 'utf-8');
      const doc = yaml.load(raw) as
        | { approvals?: { humanRequired?: string[] } }
        | null
        | undefined;
      const list = doc?.approvals?.humanRequired ?? [];
      if (Array.isArray(list)) {
        return { set: new Set(list.filter((s) => typeof s === 'string')), known: true };
      }
    } catch {
      // try next path
    }
  }
  // No manifest reachable — fail-OPEN for the chat route's hint
  // logic. The MCP-side gate is still enforced; the worst case is
  // the chat UI doesn't surface an inline card and the operator has
  // to navigate to /approvals manually. Better than refusing to
  // chat.
  console.warn(
    '[approvals-config] manifest.approvals.humanRequired not found in any of:',
    CANDIDATE_PATHS,
  );
  return { set: new Set<string>(), known: false };
}

export async function getHumanRequiredSet(): Promise<Set<string>> {
  if (_cache !== null) {
    return _cache.humanRequired;
  }
  const { set, known } = await _readHumanRequired();
  // An unreadable manifest is not cached, so the next turn retries
  // instead of treating one failed read as "nothing is gated" for the
  // life of the process.
  if (known) _cache = { humanRequired: set, loadedAt: Date.now() };
  return set;
}

/** The gated tool names (sorted, so the prompt that lists them stays
 *  byte-stable for caching) plus whether the manifest was readable. */
export async function getApprovalGating(): Promise<ApprovalGating> {
  if (_cache !== null) {
    return { gated: [..._cache.humanRequired].sort(), known: true };
  }
  const { set, known } = await _readHumanRequired();
  if (known) _cache = { humanRequired: set, loadedAt: Date.now() };
  return { gated: [...set].sort(), known };
}

export async function isToolGated(toolName: string): Promise<boolean> {
  const set = await getHumanRequiredSet();
  return set.has(toolName);
}
