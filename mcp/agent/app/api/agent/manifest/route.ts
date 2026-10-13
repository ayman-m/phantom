import { NextResponse } from 'next/server';

import { agentContract } from '@/lib/agent-contract';

export const dynamic = 'force-dynamic';

export async function GET() {
  return NextResponse.json({
    ...agentContract,
    runtime: {
      mode: 'standalone-or-orchestrated',
      // There is no setup page. setupRequired stays in the payload
      // as a constant `false` for API back-compat.
      setupRequired: false,
    },
    generatedAt: new Date().toISOString(),
  });
}
