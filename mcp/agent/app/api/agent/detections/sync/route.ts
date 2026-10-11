/**
 * Detections bulk-upsert proxy.
 *
 * POST /api/agent/detections/sync
 *   Body (JSON): {
 *     issues: [
 *       { rule_id, rule_name, severity, technique?, last_fired, ... },
 *       ...
 *     ]
 *   }
 *
 * Used by external tooling that pre-fetches issues from XSIAM/SIEM
 * outside the standard coverage_cycle_run flow (see
 * usecase/builtin_components/coverage_tools.py). Most operators won't
 * hit this directly — asking the agent to run the coverage cycle, or
 * the continuous-coverage-cycle recurring job, is the canonical path.
 */

import { proxyToMcp } from '@/lib/mcp-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  return proxyToMcp(request, '/api/v1/detections/sync');
}
