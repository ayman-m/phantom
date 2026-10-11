import { NextRequest, NextResponse } from 'next/server';

import { agentContract, agentWorkflows } from '@/lib/agent-contract';

export const dynamic = 'force-dynamic';

export async function GET() {
  return NextResponse.json({
    agentId: agentContract.metadata.id,
    workflows: agentWorkflows,
  });
}

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => ({}))) as {
    workflowId?: string;
    variables?: Record<string, string>;
  };
  const workflow = agentWorkflows.find((item) => item.id === body.workflowId);

  if (!workflow) {
    return NextResponse.json(
      {
        error: 'Unknown workflow',
        validWorkflowIds: agentWorkflows.map((item) => item.id),
      },
      { status: 404 }
    );
  }

  let prompt = workflow.prompt;
  for (const [key, value] of Object.entries(body.variables || {})) {
    prompt = prompt.replaceAll(`<${key}>`, value);
  }

  return NextResponse.json({
    agentId: agentContract.metadata.id,
    workflowId: workflow.id,
    prompt,
    requiredTools: workflow.requiredTools,
    expectedOutputs: workflow.outputs,
  });
}
