import { NextResponse } from 'next/server';

import { getApprovalGating } from '@/lib/approvals-config';

export const dynamic = 'force-dynamic';

/**
 * GET /api/agent/approvals/gating — which tools this install gates on a
 * human approval: the bundle manifest's `approvals.humanRequired`, the
 * same list the chat route reads for the system prompt and the inline
 * cards. `count: 0` means nothing waits for a card. `known: false`
 * means the manifest could not be read, which is not the same as an
 * empty list: callers must not report "nothing is gated" for it.
 *
 * Read-only; the list is bundle-shipped and immutable at runtime.
 */
export async function GET() {
  const { gated, known } = await getApprovalGating();
  return NextResponse.json({ gated, count: gated.length, known });
}
