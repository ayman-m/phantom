import { NextResponse } from 'next/server';

import { agentContract } from '@/lib/agent-contract';
import { getEffectiveRuntimeConfig } from '@/lib/runtime-config';

export const dynamic = 'force-dynamic';

export async function GET() {
  const runtimeConfig = await getEffectiveRuntimeConfig();
  return NextResponse.json({
    ...agentContract,
    runtime: {
      mode: 'standalone-or-orchestrated',
      model: runtimeConfig.GEMINI_MODEL,
      // There is no setup page. setupRequired stays in the payload
      // as a constant `false` for API back-compat.
      setupRequired: false,
    },
    generatedAt: new Date().toISOString(),
  });
}
