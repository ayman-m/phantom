/**
 * Internal hook fire-site.
 *
 * MCP-side code paths (notification publish, approval request) can't
 * call the TS-side `dispatchHooks()` directly. This endpoint bridges:
 * MCP POSTs `{event, payload}` here; we run the dispatcher and return
 * the aggregate result. Fire-and-forget on the MCP side, so the
 * response is mostly informational.
 *
 * Authentication: MCP_TOKEN bearer (same loopback-trust pattern the
 * agent uses for every other MCP-to-agent call).
 *
 * Why "internal" in the path: this route is for in-cluster
 * loopback calls only — never reachable from the operator's browser
 * (NextAuth gates the `/api/agent/*` surface; the bearer auth here
 * is independent). The path name is the contract that lets future
 * routing layers (e.g. an ingress that filters internal paths)
 * distinguish the loopback surface from the operator-facing one.
 */

import { NextRequest, NextResponse } from "next/server";

import {
  dispatchHooks,
  type HookAggregateResult,
} from "@/lib/hook-runner";
import { HOOK_EVENTS, type HookEvent, type HookPayload } from "@/lib/hooks";
import { getEffectiveRuntimeConfig } from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest): Promise<NextResponse> {
  // Auth: bearer == MCP_TOKEN. The MCP carries this in its callback.
  const auth = req.headers.get("authorization") ?? "";
  const expected = (
    await getEffectiveRuntimeConfig()
  ).MCP_TOKEN || process.env.MCP_TOKEN || "";
  if (!expected || auth !== `Bearer ${expected}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  let body: { event?: string; payload?: HookPayload };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return NextResponse.json(
      { error: "body must be JSON" },
      { status: 400 },
    );
  }
  const event = body.event;
  if (!event || !HOOK_EVENTS.includes(event as HookEvent)) {
    return NextResponse.json(
      { error: `event must be one of ${HOOK_EVENTS.join(", ")}` },
      { status: 400 },
    );
  }
  const payload = body.payload;
  if (!payload || typeof payload !== "object") {
    return NextResponse.json(
      { error: "payload must be an object" },
      { status: 400 },
    );
  }

  let result: HookAggregateResult;
  try {
    result = await dispatchHooks(event as HookEvent, payload);
  } catch (err) {
    return NextResponse.json(
      {
        error: "dispatch failed",
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 500 },
    );
  }
  return NextResponse.json({
    dispatched: true,
    decision: result.decision,
    decisions: result.decisions,
  });
}
