import { NextRequest } from 'next/server';
import { PhantomMCPClient, MCPTool } from '@/lib/mcp-client';
import { callMcpServer } from '@/lib/mcp-proxy';
import { getEffectiveRuntimeConfig } from '@/lib/runtime-config';
import type { EffectiveRuntimeConfig } from '@/lib/runtime-config';
import { classifyRiskTier, getApprovalGating, isToolGated } from '@/lib/approvals-config';
// System-prompt text extracted to its own
// module. ActionPolicy interface + renderActionPolicyBlock helper +
// the ~680 lines of stable prompt content all live there now. This
// route imports the type + the builder; renderActionPolicyBlock
// stays internal to the system-prompt module.
import {
  buildSystemPromptText,
  DEFAULT_ACTION_POLICY,
  type ActionPolicy,
  type ApprovalMode,
  type SkillSummary,
} from '@/lib/system-prompt';
// Live skills registry → <available_skills> block in the
// system prompt. Fetched once per chat turn before we call into the
// model loop, then threaded through the turn's single system prompt so the
// same registry view is consistent across every model call in the turn.
import { fetchSkillsForPrompt } from '@/lib/skills-registry';
// Token-aware budgeting helpers.
import { estimateMessageTokens, estimateTokens } from '@/lib/tokens';
import {
  computeInputBudget,
  resolveContextCap,
  DEFAULT_RESERVED_OUTPUT_TOKENS,
} from '@/lib/model-context-caps';
// Operator-triggered conversation compaction.
import {
  compactMessages,
  COMPACTION_CHECKPOINT_KIND,
  isCompactionCheckpoint,
  type CompactionInputMessage,
} from '@/lib/compaction';
// Every model call goes through the provider-neutral dispatch in
// lib/providers: the route builds neutral requests (TurnMessage[], ToolSpec[])
// and the adapter for the resolved provider owns the wire format. Gemini's
// payload assembly, schema conversion and transports (API key, Vertex AI incl.
// the Vertex context-cache swap) live in lib/providers/gemini.
import {
  callModel,
  capabilitiesFor,
  credsFromRuntimeConfig,
  estimateToolsJson,
  summarizeText,
  type DispatchDeps,
} from '@/lib/providers/dispatch';
// A model call cancelled because the client went away is not a failure: the
// turn ends quietly and no failure row is written.
import { isAbortedError } from '@/lib/providers/errors';
import { mcpBlockedHosts } from '@/lib/mcp-host';
import { createTurnAbort } from '@/lib/turn-abort';
// Which model a turn runs on: header, session preference, the install default
// (settings key `defaultModel`), else the derived default. A model that was
// named and cannot be used fails the turn (MODEL_UNAVAILABLE); it is never
// replaced by another.
import {
  describeInstallDefault,
  interpretModelCommand,
  renderModelStatus,
  type ModelRejection,
  type TurnModelResult,
} from '@/lib/providers/model-resolution';
import { createProviderEventSink } from '@/lib/providers/event-sink';
import type { ModelEntry } from '@/lib/providers/registry/types';
import { resolveModelForRequest } from '@/lib/model-registry-server';
import {
  reconcileToolResults,
  requestBudgetSummary,
  runModelLoop,
  type LoopCall,
} from '@/lib/providers/turn-loop';
import type {
  AssistantTurn,
  FinishReason,
  ModelRef,
  ProviderEvent,
  ToolResultItem,
  ToolSpec,
  TurnMessage,
} from '@/lib/providers/types';
// Slash command parse-and-dispatch framework.
// Adding a new command becomes one entry in SLASH_COMMANDS below.
import {
  parseSlashCommand,
  dispatchSlashCommand,
  renderSlashHelp,
  type SlashCommand,
} from '@/lib/slash-commands';
// Per-turn cost accounting (lib/cost-rows.ts). Reads the normalized usage of
// each model call, prices it with the registry's rates for the exact
// provider/model, and writes one audit row per call plus one SSE event per turn.
import {
  addCallToTally,
  auditResponseRows,
  buildTurnCostMetadata,
  cacheReadSavings,
  newTurnTally,
  renderCostSummary,
  sumCostRows,
  turnCostSummary,
  type CallCost,
  type CallKind,
} from '@/lib/cost-rows';
// Per-tool metadata (readOnly / destructive /
// concurrencySafe / openWorld). Powers approval-card visuals and
// future parallel-batch execution.
import {
  resolveToolMetadata,
  type ToolMetadata,
} from '@/lib/tool-metadata';
// Explicit run-status reasons. Every chat
// turn ends with a `RunStatusReason` on the done event so
// operators get a clear "why" instead of silent cutoffs.
import type { RunStatusReason } from '@/lib/run-status';
// Subagent runner. The model invokes
// `subagent_create` as a synthetic tool; the chat-route intercepts,
// resolves the agent definition from MCP, and runs a tightly-
// scoped sub-loop. Reuses callModel + the hook framework
// (PreToolUse/PostToolUse fire inside subagents too) + the task
// registry (each subagent run is a task).
import { globMatch } from '@/lib/hooks';
import {
  evaluatePermissionPolicy,
  validatePermissionPolicy,
} from '@/lib/permission-policy';
import { applyTruncation, policyFromEnv as truncationPolicyFromEnv } from '@/lib/evidence-truncation';
// Operator-registered lifecycle hooks. Loaded
// fresh from the MCP at every event fire-site (PreToolUse,
// PostToolUse, etc.) and dispatched in priority order. A hook may
// deny / allow / ask, replace tool I/O, or inject context.
import { dispatchHooks } from '@/lib/hook-runner';
import type { HookEvent, HookPayload } from '@/lib/hooks';

/**
 * Best-effort write of an audit row to the MCP.
 * Never throws; failure logs a warning. Called by the chat handler at
 * compaction lifecycle (start / end / failed), context-window warnings,
 * and Vertex cache hits — events that are visible live but had no
 * persisted footprint until now.
 *
 * Action-name conventions (kept in sync with the chat route's emit
 * sites and the observability /events page filter chips):
 *
 *   chat_compaction_start    — operator /compress kicked off
 *   chat_compaction_end      — checkpoint written, summary length etc.
 *   chat_compaction_failed   — summarizer errored or returned empty
 *   chat_context_warning     — guard fired at >=90% utilization
 *   chat_cache_hit           — Vertex cachedContents reused
 *   chat_model_rejected      — the model a turn, command or subagent asked
 *                              for cannot serve (MODEL_UNAVAILABLE)
 */
async function safeAudit(
  action: string,
  args: {
    target?: string;
    status?: 'success' | 'failure';
    durationMs?: number;
    metadata?: Record<string, unknown>;
    trigger?: string;
  } = {},
): Promise<void> {
  try {
    await callMcpServer('/api/v1/audit', {
      method: 'POST',
      body: {
        action,
        target: args.target,
        status: args.status,
        duration_ms: args.durationMs,
        metadata: args.metadata ?? {},
      },
      headers: args.trigger ? { 'X-Phantom-Trigger': args.trigger } : undefined,
    });
  } catch (err) {
    console.warn(
      `chat: audit write for action=${action} failed:`,
      err instanceof Error ? err.message : err,
    );
  }
}

/**
 * The sink a model call gets as `onEvent`: the adapter's non-fatal observations
 * (a downgraded tool choice, a dropped tool call, a refusal, an unknown tool
 * name) go to the SSE `debug` stream and the audit log, never into the thread.
 * See lib/providers/event-sink.ts.
 */
function providerEventSink(args: {
  ref: ModelRef;
  purpose: Parameters<typeof createProviderEventSink>[0]['purpose'];
  sessionId: string;
  trigger: string | undefined;
  sendEvent: ((kind: string, data: unknown) => void) | undefined;
}) {
  return createProviderEventSink({
    ref: args.ref,
    purpose: args.purpose,
    sessionId: args.sessionId,
    sendEvent: args.sendEvent,
    audit: (action, row) =>
      safeAudit(action, { target: row.target, status: row.status, metadata: row.metadata, trigger: args.trigger }),
  });
}

/**
 * The model a turn, command or subagent asked for cannot serve. Writes the
 * `chat_model_rejected` audit row and, when the caller has a stream, sends the
 * `error` event the chat UI shows and a job run records as its failure:
 * `code: 'MODEL_UNAVAILABLE'`, a message that says why, and refs that would
 * work. The caller ends the stream; no `done` follows, so a scheduled job
 * counts the run as failed.
 */
async function reportModelRejected(args: {
  sessionId: string;
  trigger: string | undefined;
  rejection: ModelRejection;
  surface: 'chat' | 'compress' | 'plan' | 'model_command' | 'subagent';
  sendEvent: ((kind: string, data: unknown) => void) | undefined;
}): Promise<void> {
  const { rejection } = args;
  args.sendEvent?.('error', {
    error: rejection.message,
    code: rejection.code,
    reason: rejection.reason,
    source: rejection.source,
    requested: rejection.requested,
    suggestions: rejection.suggestions,
    ...(rejection.options ? { options: rejection.options } : {}),
  });
  await safeAudit('chat_model_rejected', {
    target: `session:${args.sessionId}`,
    status: 'failure',
    metadata: {
      requested: rejection.requested.slice(0, 200),
      source: rejection.source,
      reason: rejection.reason,
      suggestions: rejection.suggestions,
      surface: args.surface,
    },
    trigger: args.trigger,
  });
}

/**
 * Record a cost audit row from one model call. Best-effort; never blocks the
 * stream. A call with no usage records nothing and returns null.
 *
 * The row is built by lib/cost-rows.ts from the call's normalized usage and
 * the registry's price for the exact `provider/model`; an unpriced model
 * writes `cost_usd: null`. The returned `CallCost` lets the caller sum across
 * the follow-up calls of a multi-tool turn (the chat route accumulates and
 * sends a single `turn_cost` SSE event per turn at done time, rather than a
 * separate event per model call).
 */
function extractAndRecordCost(
  turn: Pick<AssistantTurn, 'usage' | 'requestId' | 'finish'>,
  args: {
    sessionId: string;
    ref: ModelRef;
    trigger: string | undefined;
    /** 'initial' for the first model call in a turn; 'followup'
     *  for tool-result follow-ups; 'budget_summary' for the
     *  partial-summary fallback that fires when the 20-turn loop
     *  exhausts without producing text. Surfaces in audit metadata
     *  so the operator can see how many round-trips a turn cost. */
    callKind: CallKind;
  },
): CallCost | null {
  if (!turn.usage) return null;
  const record = buildTurnCostMetadata({
    usage: turn.usage,
    provider: args.ref.provider,
    model: args.ref.model,
    callKind: args.callKind,
    requestId: turn.requestId,
    finish: turn.finish,
  });
  // Audit one row per model call. Fine-grained (vs. one per
  // turn) because a turn can rack up 5-10 calls when tools fire,
  // and operators want per-call cost breakdown for tool-cost
  // attribution. Not high-volume in absolute terms.
  void safeAudit('chat_turn_cost', {
    target: `session:${args.sessionId}`,
    status: 'success',
    metadata: record.metadata,
    trigger: args.trigger,
  });
  return record.call;
}

/**
 * Synthetic tool name the model calls to
 * spawn a subagent. The chat-route's tool-dispatch loop recognizes
 * this name and routes to `runSubagent` instead of MCP dispatch.
 * Listed in the model's tool catalog as a regular function with
 * a documented schema (see SUBAGENT_CREATE_TOOL_SPEC below).
 */
const SUBAGENT_CREATE_TOOL = 'subagent_create';

/** OpenAPI-style schema for `subagent_create`. The model sees this
 *  alongside the regular MCP tools. Args:
 *    agent_name  — required. Resolved against the MCP agent-
 *                  definition store (origin: operator | plugin |
 *                  builtin). Empty/missing returns an error.
 *    prompt      — required. The task the subagent should perform.
 *    parent_id   — optional. The current session id; the chat-route
 *                  fills this in automatically from the loop
 *                  context if absent. */
const SUBAGENT_CREATE_TOOL_SPEC: ToolSpec = {
  name: SUBAGENT_CREATE_TOOL,
  description:
    'Spawn a scoped subagent to perform a focused task. The subagent ' +
    'runs with its own system prompt and a curated tool subset (e.g. ' +
    'red-team subagent only sees caldera_*, blue-team only xsiam_*). ' +
    'Use when a task needs a different operating posture than this ' +
    "session — don't use it for trivial sub-questions you can answer " +
    'directly. Available agent_name values come from /api/v1/' +
    'agent-definitions; common builtins: red-team-emulator, ' +
    'blue-team-validator, coverage-reporter.',
  inputSchema: {
    type: 'object' as const,
    properties: {
      agent_name: {
        type: 'string' as const,
        description:
          'Name of the agent definition (e.g. "red-team-emulator"). ' +
          'Must exist + be enabled in /api/v1/agent-definitions.',
      },
      prompt: {
        type: 'string' as const,
        description:
          'The task for the subagent. Self-contained — the subagent ' +
          "won't see the parent's prior context.",
      },
    },
    required: ['agent_name', 'prompt'],
  },
};

/**
 * What the dispatcher needs beyond the request: the MCP host, which a provider
 * base URL must never name. Every model call in this route passes it
 * (scripts/test-chat-abort.mjs checks the sites), the same list the Providers
 * page and the connection tests use.
 */
function modelDispatchDeps(): DispatchDeps {
  return { blockedHosts: mcpBlockedHosts() };
}

/** Result of one subagent run, returned to the parent's tool-call
 *  loop as the tool result text. */
interface SubagentRunResult {
  subagent_session_id: string;
  agent_name: string;
  agent_id: string;
  status: 'completed' | 'max_turns_exceeded' | 'failed' | 'denied' | 'cancelled';
  final_response: string;
  tool_calls_made: Array<{ tool: string; args: Record<string, unknown> }>;
  tool_calls_count: number;
  turns_used: number;
  duration_ms: number;
  error?: string;
}

/** Filter the parent's tool catalog through an agent definition's
 *  tools_allowed / tools_denied globs. Deny wins when both match.
 *  Empty allow list means "no restriction" (still subject to denies). */
function filterToolsForAgent(
  parentTools: ToolSpec[],
  toolsAllowed: string[],
  toolsDenied: string[],
): ToolSpec[] {
  const allowGlob = toolsAllowed.length > 0
    ? toolsAllowed.join(',')
    : null;
  const denyGlob = toolsDenied.length > 0
    ? toolsDenied.join(',')
    : null;
  return parentTools.filter((tool) => {
    const name = tool.name;
    if (!name) return false;
    if (denyGlob && globMatch(name, denyGlob)) return false;
    if (allowGlob && !globMatch(name, allowGlob)) return false;
    return true;
  });
}

/**
 * Run a subagent end-to-end. Foreground execution: blocks the
 * caller until the subagent completes, errors, or hits max_turns.
 * Returns the synthesized result the parent's tool-call loop feeds
 * back to the parent model.
 *
 * Reuses existing substrates:
 *   - Lifecycle hooks: SubagentStart fires before, SubagentEnd after.
 *     PreToolUse/PostToolUse fire INSIDE the subagent's tool loop too.
 *   - Tasks: each subagent run is a Task with progress.
 *   - Cost tracking: subagent's model calls write
 *     chat_turn_cost rows tagged with the subagent session id.
 *
 * Architecture note: the subagent gets its OWN MCP session
 * (parent_session_id linkage in metadata). Its transcript is
 * persistent and queryable separately, so /sessions can show
 * subagent runs as sidechain transcripts of the parent.
 */
async function runSubagent(args: {
  agentName: string;
  prompt: string;
  parentSessionId: string;
  parentMessage: string;
  trigger: string | undefined;
  parentTools: ToolSpec[];
  runtimeConfig: EffectiveRuntimeConfig;
  /** The parent turn's canonical model ref; a subagent without its own model runs on it. */
  parentModel: string;
  mcpClient: PhantomMCPClient;
  sendEvent: (kind: string, data: unknown) => void;
  /** Fires when the client goes away; cancels the subagent's model call. */
  signal: AbortSignal;
}): Promise<SubagentRunResult> {
  const startedAt = Date.now();

  // SubagentStart hook fire-site. A hook
  // can deny ("block any subagent in tenant-X") or no-op.
  const startHook = await fireHookEvent(
    'SubagentStart',
    {
      event: 'SubagentStart',
      sessionId: args.parentSessionId,
      agentName: args.agentName,
      prompt: args.prompt,
      trigger: args.trigger,
    } as never, // HookPayload union extension; cast is benign
    // because the dispatcher only reads `event` from the
    // payload to filter, not field-by-field
    args.trigger,
  );
  if (startHook.decision === 'deny') {
    return {
      subagent_session_id: '',
      agent_name: args.agentName,
      agent_id: '',
      status: 'denied',
      final_response: '',
      tool_calls_made: [],
      tool_calls_count: 0,
      turns_used: 0,
      duration_ms: Date.now() - startedAt,
      error:
        startHook.reason ??
        'Subagent dispatch blocked by a SubagentStart hook.',
    };
  }

  // Resolve the agent definition by name from MCP.
  let agentDef: {
    id: string;
    name: string;
    system_prompt: string;
    tools_allowed: string[];
    tools_denied: string[];
    model: string | null;
    max_turns: number;
    isolation: string;
    enabled: boolean;
  };
  try {
    const resp = await callMcpServer<{
      agent_definition?: typeof agentDef;
    }>(
      `/api/v1/agent-definitions/by-name/${encodeURIComponent(args.agentName)}`,
      {
        method: 'GET',
        headers: args.trigger
          ? { 'X-Phantom-Trigger': args.trigger }
          : undefined,
      },
    );
    if (!resp?.agent_definition) {
      return {
        subagent_session_id: '',
        agent_name: args.agentName,
        agent_id: '',
        status: 'failed',
        final_response: '',
        tool_calls_made: [],
        tool_calls_count: 0,
        turns_used: 0,
        duration_ms: Date.now() - startedAt,
        error: `Agent definition '${args.agentName}' not found.`,
      };
    }
    agentDef = resp.agent_definition;
  } catch (err) {
    return {
      subagent_session_id: '',
      agent_name: args.agentName,
      agent_id: '',
      status: 'failed',
      final_response: '',
      tool_calls_made: [],
      tool_calls_count: 0,
      turns_used: 0,
      duration_ms: Date.now() - startedAt,
      error: `Agent lookup failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
  if (!agentDef.enabled) {
    return {
      subagent_session_id: '',
      agent_name: args.agentName,
      agent_id: agentDef.id,
      status: 'failed',
      final_response: '',
      tool_calls_made: [],
      tool_calls_count: 0,
      turns_used: 0,
      duration_ms: Date.now() - startedAt,
      error: `Agent '${args.agentName}' is disabled.`,
    };
  }

  // The subagent's model: its definition's, else the parent turn's. One that
  // cannot serve ends the run; nothing is substituted.
  const subagentChoice = (
    await resolveModelForRequest({ header: agentDef.model || args.parentModel }, args.runtimeConfig)
  ).result;
  if (!subagentChoice.ok) {
    await reportModelRejected({
      sessionId: args.parentSessionId,
      trigger: args.trigger,
      rejection: subagentChoice,
      surface: 'subagent',
      sendEvent: undefined,
    });
    return {
      subagent_session_id: '',
      agent_name: args.agentName,
      agent_id: agentDef.id,
      status: 'failed',
      final_response: '',
      tool_calls_made: [],
      tool_calls_count: 0,
      turns_used: 0,
      duration_ms: Date.now() - startedAt,
      error: `MODEL_UNAVAILABLE: ${subagentChoice.message}`,
    };
  }
  const subagentRef = subagentChoice.ref;
  const subagentModel = subagentRef.model;

  // Create a fresh MCP session for the subagent. parent_session_id
  // in metadata is the linkage that lets the chat UI render the
  // subagent transcript as a sidechain of the parent.
  let subagentSessionId: string;
  try {
    const created = await callMcpServer<{
      session?: { id?: string };
    }>('/api/v1/sessions', {
      method: 'POST',
      body: {
        user: 'agent',
        title: `[subagent:${args.agentName}] ${args.prompt.slice(0, 60)}`,
        meta: {
          parent_session_id: args.parentSessionId,
          subagent_origin: 'parent_session',
          agent_name: args.agentName,
          agent_id: agentDef.id,
        },
      },
      headers: args.trigger
        ? { 'X-Phantom-Trigger': args.trigger }
        : undefined,
    });
    subagentSessionId =
      created?.session?.id ?? `s_subagent_${crypto.randomUUID()}`;
  } catch (err) {
    return {
      subagent_session_id: '',
      agent_name: args.agentName,
      agent_id: agentDef.id,
      status: 'failed',
      final_response: '',
      tool_calls_made: [],
      tool_calls_count: 0,
      turns_used: 0,
      duration_ms: Date.now() - startedAt,
      error: `Subagent session create failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }

  // Open a task entry for this subagent run.
  // The /tasks UI shows it under kind='subagent' with parent
  // session linkage. Failure to create the task is non-fatal.
  let taskId: string | undefined;
  try {
    const taskResp = await callMcpServer<{
      task?: { id?: string };
    }>('/api/v1/tasks', {
      method: 'POST',
      body: {
        kind: 'subagent',
        title: `${args.agentName}: ${args.prompt.slice(0, 80)}`,
        parent_session_id: args.parentSessionId,
        initial_status: 'running',
        meta: {
          agent_name: args.agentName,
          agent_id: agentDef.id,
          subagent_session_id: subagentSessionId,
        },
      },
      headers: args.trigger
        ? { 'X-Phantom-Trigger': args.trigger }
        : undefined,
    });
    taskId = taskResp?.task?.id;
  } catch {
    // best-effort
  }

  // Persist the subagent's user-message (the prompt the parent gave it).
  await safePersist(
    subagentSessionId,
    { role: 'user', content: args.prompt },
    args.trigger,
  );

  // Audit row for the subagent start.
  void safeAudit('chat_subagent_started', {
    target: `session:${subagentSessionId}`,
    metadata: {
      parent_session_id: args.parentSessionId,
      agent_name: args.agentName,
      agent_id: agentDef.id,
      max_turns: agentDef.max_turns,
      tools_allowed_count: agentDef.tools_allowed.length,
      tools_denied_count: agentDef.tools_denied.length,
    },
    trigger: args.trigger,
  });

  // Filter tools to the agent's scope. The model in the subagent
  // loop only SEES tools that match — it can't even call denied
  // tools because they're not in the catalog.
  const scopedTools = filterToolsForAgent(
    args.parentTools,
    agentDef.tools_allowed,
    agentDef.tools_denied,
  );

  // Stream a `subagent_started` SSE event so the parent's chat UI
  // can render a sidechain progress indicator.
  args.sendEvent('subagent_started', {
    parent_session_id: args.parentSessionId,
    subagent_session_id: subagentSessionId,
    agent_name: args.agentName,
    agent_id: agentDef.id,
    prompt: args.prompt,
    max_turns: agentDef.max_turns,
    tools_count: scopedTools.length,
    task_id: taskId,
  });

  // Tool catalog scoped + system instruction overridden — run the loop.
  const subagentMessages: TurnMessage[] = [{ role: 'user', text: args.prompt }];
  const subagentCreds = credsFromRuntimeConfig(args.runtimeConfig);
  // Monotonic per-run call counter: adapters derive call ids from it.
  let subagentCallStep = 0;
  const subagentProviderEvents = providerEventSink({
    ref: subagentRef,
    purpose: 'subagent',
    sessionId: subagentSessionId,
    trigger: args.trigger,
    sendEvent: args.sendEvent,
  });
  const callSubagentModel = () =>
    callModel(
      {
        ref: subagentRef,
        system: agentDef.system_prompt,
        messages: subagentMessages,
        tools: scopedTools,
        // A scope that matches no tool sends an empty tool list, as it always has.
        toolChoice: scopedTools.length === 0 ? 'none' : 'auto',
        thinking: false,
        purpose: 'subagent',
        cacheKey: subagentSessionId,
      },
      { creds: subagentCreds, step: subagentCallStep++, onEvent: subagentProviderEvents, signal: args.signal },
      modelDispatchDeps(),
    );
  const finalText: string[] = [];
  const toolCallsMade: Array<{ tool: string; args: Record<string, unknown> }> = [];
  let turnsUsed = 0;
  let status: SubagentRunResult['status'] = 'completed';
  let errorMessage: string | undefined;

  try {
    let turn = await callSubagentModel();

    // Track cost — per-model-call rows tagged with subagent session.
    extractAndRecordCost(turn, {
      sessionId: subagentSessionId,
      ref: subagentRef,
      trigger: args.trigger,
      callKind: 'initial',
    });

    for (let step = 0; step < agentDef.max_turns; step++) {
      turnsUsed = step + 1;
      const functionCalls = turn.toolCalls;
      finalText.push(...turn.text);
      if (functionCalls.length === 0) break;

      // Update task progress.
      if (taskId) {
        void callMcpServer<unknown>(
          `/api/v1/tasks/${encodeURIComponent(taskId)}/progress`,
          {
            method: 'PATCH',
            body: {
              progress: turnsUsed / agentDef.max_turns,
              progress_label: `turn ${turnsUsed}/${agentDef.max_turns}: ${functionCalls.length} tool(s)`,
            },
            headers: args.trigger
              ? { 'X-Phantom-Trigger': args.trigger }
              : undefined,
          },
        ).catch(() => {});
      }

      subagentMessages.push({ role: 'assistant_turn', turn });
      const responseItems: ToolResultItem[] = [];
      for (const call of functionCalls) {
        const toolName = call.name;
        const toolArgs = call.args || {};

        // Defense in depth: re-check scope. The model shouldn't
        // even see denied tools, but if a hook injected a tool
        // call with a different name (rare), reject here.
        const denyGlob = agentDef.tools_denied.length > 0
          ? agentDef.tools_denied.join(',')
          : null;
        const allowGlob = agentDef.tools_allowed.length > 0
          ? agentDef.tools_allowed.join(',')
          : null;
        if (
          (denyGlob && globMatch(toolName, denyGlob)) ||
          (allowGlob && !globMatch(toolName, allowGlob))
        ) {
          const reason = `Tool '${toolName}' is outside the subagent's scope.`;
          args.sendEvent('subagent_tool_blocked', {
            subagent_session_id: subagentSessionId,
            tool: toolName,
            reason,
          });
          responseItems.push({
            kind: 'result',
            callId: call.id,
            name: toolName,
            payload: {
              error: reason,
              blocked_by: 'subagent_scope',
            },
          });
          continue;
        }

        // Stream a sub-tool-call event so the parent UI can show
        // what the subagent's doing in real time.
        args.sendEvent('subagent_tool_call', {
          subagent_session_id: subagentSessionId,
          tool: toolName,
          args: toolArgs,
        });

        let toolResult: { content: Array<{ text?: string }> } | null = null;
        let toolError: Error | null = null;
        try {
          toolResult = await args.mcpClient.callTool(toolName, toolArgs);
        } catch (err) {
          toolError = err instanceof Error ? err : new Error(String(err));
        }

        // Evidence truncation (mirrors the main loop's block in the
        // tool-dispatch switch below) — without this, a subagent tool
        // like xsiam_run_xql_query with a large result accumulates raw, untruncated
        // output in subagentContents across every turn (up to
        // max_turns), the exact context/cost blowup this mechanism
        // exists to prevent on the main loop.
        if (toolResult && Array.isArray(toolResult.content) && !toolError) {
          const truncationPolicy = truncationPolicyFromEnv();
          for (let ci = 0; ci < toolResult.content.length; ci++) {
            const part = toolResult.content[ci];
            if (typeof part?.text !== 'string') continue;
            const truncation = applyTruncation(toolName, part.text, truncationPolicy);
            if (truncation.truncated) {
              // applyTruncation() only mutates string inputs (guarded
              // above by the typeof check) and always returns a
              // string in that case — output is typed `unknown`
              // because the function also accepts structured input.
              toolResult.content[ci] = { ...part, text: truncation.output as string };
              void callMcpServer('/api/v1/audit', {
                method: 'POST',
                body: {
                  action: 'tool_output_truncated',
                  target: `tool:${toolName}`,
                  status: 'success',
                  metadata: {
                    session_id: subagentSessionId,
                    parent_session_id: args.parentSessionId,
                    tool_name: toolName,
                    bytes_dropped: truncation.bytesDropped,
                    bytes_kept: truncation.bytesKept,
                    head_kept: truncation.headKept,
                    tail_kept: truncation.tailKept,
                    max_bytes: truncationPolicy.maxBytes,
                    content_index: ci,
                    source: 'subagent',
                  },
                },
              }).catch(() => {});
            }
          }
        }

        const resultText = toolError
          ? `Error: ${toolError.message}`
          : toolResult?.content[0]?.text ||
            JSON.stringify(toolResult?.content ?? '');

        toolCallsMade.push({
          tool: toolName,
          args: toolArgs as Record<string, unknown>,
        });

        // Persist to subagent session.
        await safePersist(
          subagentSessionId,
          {
            role: 'tool',
            content: resultText,
            tool_call_id: toolName,
            meta: {
              tool: toolName,
              args: toolArgs,
              status: toolError ? 'error' : 'success',
            },
          },
          args.trigger,
        );

        args.sendEvent('subagent_tool_result', {
          subagent_session_id: subagentSessionId,
          tool: toolName,
          status: toolError ? 'error' : 'success',
          result: resultText.slice(0, 500),
        });

        responseItems.push({
          kind: 'result',
          callId: call.id,
          name: toolName,
          payload: toolError
            ? { error: toolError.message }
            : { result: resultText },
        });
      }
      if (responseItems.length > 0) {
        subagentMessages.push({
          role: 'tool_results',
          items: reconcileToolResults(functionCalls, responseItems, (message) =>
            console.warn(`chat: subagent ${message}`),
          ),
        });
      }

      // Continue the loop.
      turn = await callSubagentModel();
      extractAndRecordCost(turn, {
        sessionId: subagentSessionId,
        ref: subagentRef,
        trigger: args.trigger,
        callKind: 'followup',
      });
    }

    if (turnsUsed >= agentDef.max_turns) {
      // Check whether the FINAL response had text; if not, the
      // last turn was tools-only and we hit the cap mid-flight.
      if (turn.text.length === 0) {
        status = 'max_turns_exceeded';
      } else {
        // Drain final text from the last turn.
        finalText.push(...turn.text);
      }
    }
  } catch (err) {
    if (isAbortedError(err) || args.signal.aborted) {
      status = 'cancelled';
      errorMessage = 'cancelled: the client disconnected';
    } else {
      status = 'failed';
      errorMessage = err instanceof Error ? err.message : String(err);
    }
  }

  const finalResponse = finalText.join('').trim();

  // Persist subagent's final assistant response so the sidechain
  // transcript is complete.
  if (finalResponse) {
    await safePersist(
      subagentSessionId,
      {
        role: 'assistant',
        content: finalResponse,
        meta: {
          model: subagentModel,
          provider: subagentRef.provider,
          model_ref: `${subagentRef.provider}/${subagentRef.model}`,
          subagent: true,
          parent_session_id: args.parentSessionId,
        },
      },
      args.trigger,
    );
  }

  // Close out the task.
  if (taskId) {
    void callMcpServer<unknown>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/transition`,
      {
        method: 'POST',
        body: {
          // 'denied' / 'failed' / 'max_turns_exceeded' all map to
          // failure or aborted at the task layer. 'denied' returns
          // early before we get here so it's unreachable; the
          // explicit check would be a TS narrowing error.
          status:
            status === 'completed' ? 'succeeded'
            : status === 'cancelled' ? 'aborted'
            : 'failed', // failed, max_turns_exceeded
          output: errorMessage ?? finalResponse,
        },
        headers: args.trigger
          ? { 'X-Phantom-Trigger': args.trigger }
          : undefined,
      },
    ).catch(() => {});
  }

  // Audit row for the subagent end.
  const auditAction =
    status === 'completed'
      ? 'chat_subagent_completed'
      : 'chat_subagent_failed';
  // A cancelled run (the client closed the browser) is not a failure, so it
  // writes no failure row; the task row above is marked aborted instead.
  if (status !== 'cancelled') {
    void safeAudit(auditAction, {
      target: `session:${subagentSessionId}`,
      status: status === 'completed' ? 'success' : 'failure',
      durationMs: Date.now() - startedAt,
      metadata: {
        parent_session_id: args.parentSessionId,
        agent_name: args.agentName,
        agent_id: agentDef.id,
        turns_used: turnsUsed,
        tool_calls_count: toolCallsMade.length,
        max_turns_exceeded: status === 'max_turns_exceeded',
        error: errorMessage,
      },
      trigger: args.trigger,
    });
  }

  // SubagentEnd hook (non-decisional).
  void fireHookEvent(
    'SubagentEnd',
    {
      event: 'SubagentEnd',
      sessionId: args.parentSessionId,
      subagentSessionId,
      agentName: args.agentName,
      status,
      finalResponseChars: finalResponse.length,
      toolCallCount: toolCallsMade.length,
      durationMs: Date.now() - startedAt,
      trigger: args.trigger,
    } as never,
    args.trigger,
  );

  args.sendEvent('subagent_completed', {
    parent_session_id: args.parentSessionId,
    subagent_session_id: subagentSessionId,
    agent_name: args.agentName,
    status,
    final_response: finalResponse,
    tool_calls_count: toolCallsMade.length,
    turns_used: turnsUsed,
    duration_ms: Date.now() - startedAt,
    error: errorMessage,
  });

  return {
    subagent_session_id: subagentSessionId,
    agent_name: args.agentName,
    agent_id: agentDef.id,
    status,
    final_response: finalResponse,
    tool_calls_made: toolCallsMade,
    tool_calls_count: toolCallsMade.length,
    turns_used: turnsUsed,
    duration_ms: Date.now() - startedAt,
    error: errorMessage,
  };
}

/**
 * Derive the connector_id from an agent-facing tool name.
 * Returns null for tools that don't belong to any connector (built-in
 * MCP tools like instances_list, audit_recent, etc.).
 *
 * Handles both modern dotted form ("cortex-xdr.get_cases_and_issues" →
 * "cortex-xdr") and legacy flat aliases ("xdr_get_cases_and_issues" →
 * "cortex-xdr").
 *
 * A naive inline `toolName.split('_', 1)[0]` would produce wrong
 * connector_ids for connectors whose function prefix differs from
 * their id:
 *   xdr_get_cases_and_issues  → "xdr"      WRONG (id is "cortex-xdr")
 *   phantom_create_data_worker→ "phantom"  WRONG (id is "xlog")
 *   phantom_web_navigate      → "phantom"  WRONG (id is "web")
 *   cortex_search             → "cortex"   WRONG (id is "cortex-docs")
 *
 * Resulting bug: connector failures + successes recorded against
 * non-existent connector_ids ("xdr", "phantom", "cortex"); the
 * connector_auth_required UI event fired with the wrong id; the
 * /observability/connectors state machine missed real failures for
 * cortex-xdr, cortex-docs, cortex-content, xlog, and web.
 *
 * The prefix-to-id mapping below is hardcoded against bundles/spark/
 * connectors/*\/connector.yaml's `functionPrefix` field. When a new
 * connector ships with a non-identity prefix mapping, this function
 * needs an entry. Long-term: the MCPTool interface should carry
 * connector_id explicitly so we don't need this lookup.
 */
function deriveConnectorId(toolName: string): string | null {
  // Modern dotted form: "<connector>.<tool>"
  if (toolName.includes('.')) {
    return toolName.split('.', 2)[0];
  }
  // Legacy flat aliases — order matters (longer prefixes first).
  if (toolName.startsWith('phantom_web_')) return 'web';
  if (toolName.startsWith('phantom_')) return 'xlog';
  if (toolName.startsWith('xdr_')) return 'cortex-xdr';
  if (toolName.startsWith('caldera_')) return 'caldera';
  if (toolName.startsWith('xsiam_')) return 'xsiam';
  if (toolName.startsWith('cortex_')) {
    // cortex-content + cortex-docs both use the `cortex_` prefix.
    // Disambiguate by checking against cortex-docs's small, stable
    // __all__ set. Everything else falls to cortex-content.
    const CORTEX_DOCS_TOOLS = new Set([
      'cortex_search',
      'cortex_suggest',
      'cortex_xql_lookup',
      'cortex_fetch_topic',
      'cortex_fetch_toc',
      'cortex_deep_research',
    ]);
    return CORTEX_DOCS_TOOLS.has(toolName) ? 'cortex-docs' : 'cortex-content';
  }
  // Tools that aren't connector-namespaced (e.g. instances_list,
  // audit_recent, jobs_create, marketplace_install — built-in MCP
  // tools that don't belong to any connector). Caller should skip
  // connector state updates for these.
  return null;
}

/**
 * Record a connector failure in the MCP-side
 * state store. Best-effort; never blocks the stream. The chat-
 * route uses message-string heuristics to classify auth vs. other
 * errors because the MCP tool wrapper doesn't yet expose typed
 * errors.
 */
async function recordConnectorFailure(
  connectorId: string,
  args: { error: string; isAuthError: boolean; trigger: string | undefined },
): Promise<void> {
  try {
    await callMcpServer<unknown>(
      `/api/v1/connectors/${encodeURIComponent(connectorId)}/_record_failure`,
      {
        method: 'POST',
        body: { error: args.error, is_auth_error: args.isAuthError },
        headers: args.trigger
          ? { 'X-Phantom-Trigger': args.trigger }
          : undefined,
      },
    );
  } catch {
    // The internal record endpoint may not exist on older deploys;
    // that's fine — the connector API surface already provides probe/
    // disable/enable, and the state will refresh on the next
    // operator action.
  }
}

/** Record a successful tool call. */
async function recordConnectorSuccess(
  connectorId: string,
  trigger: string | undefined,
): Promise<void> {
  try {
    await callMcpServer<unknown>(
      `/api/v1/connectors/${encodeURIComponent(connectorId)}/_record_success`,
      {
        method: 'POST',
        body: {},
        headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
      },
    );
  } catch {
    // Same rationale as recordConnectorFailure.
  }
}

/**
 * Fire a hook event and emit a single
 * `hook_dispatched` audit row summarizing the per-hook decisions.
 *
 * The chat-route shape is "fire-and-forget for non-decisional events"
 * (PostToolUse, PostCompact, RunEnd) and "fire-and-await for
 * decisional events" (PreToolUse, UserPromptSubmit, PreCompact,
 * RunStart). Callers pass `awaitDecision: true` for the latter.
 *
 * Failure is swallowed; a broken hook can't crash the chat. The
 * dispatcher itself applies each hook's `failurePolicy` for transport
 * errors; this helper handles the meta-failure of the dispatcher
 * itself failing (network blip to MCP, malformed hook records).
 */
async function fireHookEvent(
  event: HookEvent,
  payload: HookPayload,
  trigger: string | undefined,
): Promise<{
  decision: 'allow' | 'deny' | 'ask' | undefined;
  reason?: string;
  replace?: unknown;
  injectContext?: string;
}> {
  try {
    const result = await dispatchHooks(event, payload);
    if (result.decisions.length > 0) {
      // Best-effort audit of the dispatch itself. We log the per-
      // hook decisions in metadata so an operator can answer "which
      // hook denied this turn?" without re-running.
      void safeAudit('hook_dispatched', {
        target: payload.event,
        status: result.decision === 'deny' ? 'failure' : 'success',
        metadata: {
          event,
          // Not all payloads have sessionId (Notification +
          // PermissionRequest carry related.sessionId optionally
          // instead). Narrow before reading.
          session_id:
            'sessionId' in payload && typeof payload.sessionId === 'string'
              ? payload.sessionId
              : undefined,
          hooks_fired: result.decisions.length,
          decision: result.decision ?? 'no-op',
          reason: result.reason,
          per_hook: result.decisions.map((d) => ({
            id: d.hookId,
            name: d.name,
            decision: d.decision,
            duration_ms: d.durationMs,
            error: d.error,
          })),
        },
        trigger,
      });
    }
    return {
      decision: result.decision,
      reason: result.reason,
      replace: result.replace,
      injectContext: result.injectContext,
    };
  } catch (err) {
    console.warn(
      `chat: dispatchHooks(${event}) failed:`,
      err instanceof Error ? err.message : err,
    );
    return { decision: undefined };
  }
}

/**
 * Best-effort persistence to the MCP session store. Each call swallows
 * its own errors with a console warning so a session-store outage
 * never blocks the chat stream from reaching the user.
 *
 * Persistence shape (matches Spark's chat-history convention):
 *   - role='user' ............... the inbound message
 *   - role='tool' (one each) .... each tool_call/result pair, with
 *                                 meta={ tool, args } and
 *                                 tool_call_id={ tool name }
 *   - role='assistant' .......... the final composed text response
 *
 * On a brand-new session (no incoming session_id), we PATCH the title
 * to a 60-char preview of the first user message after the turn
 * completes, so the sidebar shows something meaningful.
 */
async function safePersist(
  sessionId: string,
  payload: {
    role: 'user' | 'assistant' | 'tool' | 'system';
    content: string;
    tool_call_id?: string;
    meta?: Record<string, unknown>;
  },
  trigger?: string,
): Promise<void> {
  try {
    await callMcpServer(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: 'POST',
        body: payload,
        // Forward X-Phantom-Trigger so the MCP-side audit row that
        // gets written for this message append carries the same
        // trigger tag as the originating chat turn (e.g. `job:foo`).
        headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
      },
    );
  } catch (err) {
    console.warn(
      `chat: failed to persist ${payload.role} message to session ${sessionId}:`,
      err instanceof Error ? err.message : err,
    );
  }
}

interface PersistedMessage {
  role: string;
  content: string;
  tool_call_id?: string;
  created_at?: string;
  // meta carries `kind: 'compaction-checkpoint'` and the
  // covers-until timestamp on synthesized checkpoint messages. Other
  // persisted messages may also use meta (model name on assistant
  // rows, tool args on tool rows) but those are read elsewhere.
  meta?: Record<string, unknown>;
}

/**
 * Render a persisted message into the exact text that will end up in
 * the prompt. Used both for cost estimation (token-budget
 * walk) and for the final emit pass below. Centralizing the
 * truncation rules in one helper means the cost estimate can never
 * drift from what we actually send.
 *
 * Returns `null` for messages we'd drop (system rows, empty content).
 */
function renderMessageForReplay(
  m: PersistedMessage,
): { kind: 'tool' | 'turn'; text: string } | null {
  if (m.role === 'system') return null;
  const content = (m.content ?? '').trim();
  if (!content) return null;
  if (m.role === 'tool') {
    // Tool results are replayed in full rather than cut to a small
    // per-result cap, because replay cost is low and truncation hurts:
    //   - Vertex cachedContent.create() caches the system prompt
    //     (lib/system-prompt.ts), cutting input billing on the stable
    //     prefix to ~25%.
    //   - Gemini 2.5/3 implicit prefix caching bills any turn whose
    //     prompt-prefix bytes match the previous turn's at the cached
    //     rate automatically. Append-only chat history (which this
    //     codebase always is) qualifies for free.
    // So replayed tool results bill at roughly the cached rate on every
    // turn except the first after cache expiry. A small cap would save
    // little, and it would cut large results such as
    // `phantom_get_field_info` (17KB) to a fraction of their content,
    // leaving the model to
    // relay the truncation stub back to the operator instead of
    // synthesizing an answer.
    //
    // 1 MiB ceiling here is a SAFETY VALVE, not a budget cap: catches
    // pathological "tool returns a 100 MB blob" cases without
    // affecting any real phantom workload. Phantom's largest known
    // tool output (`phantom_get_field_info` field catalog) is ~17 KB,
    // ~62x under this cap.
    //
    // If you find yourself wanting to LOWER this, instead first check:
    //   1. Is your turn paying full price? Look at chat_turn_cost
    //      audit rows — if `cached_input_tokens` is a healthy fraction
    //      of `input_tokens`, caching is working and the cap isn't
    //      the lever.
    //   2. Is one specific tool actually returning multi-MB outputs?
    //      Cap that tool's output at the source, not here.
    const TOOL_REPLAY_HARD_CAP_BYTES = 1_048_576; // 1 MiB
    const toolName = m.tool_call_id ?? '<unknown tool>';
    let body = content;
    if (body.length > TOOL_REPLAY_HARD_CAP_BYTES) {
      const elided = body.length - TOOL_REPLAY_HARD_CAP_BYTES;
      body =
        `${body.slice(0, TOOL_REPLAY_HARD_CAP_BYTES).trimEnd()}` +
        `…[truncated +${elided.toLocaleString()} bytes; this tool's full ` +
        `result was visible to the model in the original turn, only the ` +
        `head is retained on replay because the result exceeded the 1 MiB ` +
        `safety ceiling]`;
      // Rare path — every fire is worth a log line so we can see in
      // production whether the ceiling ever actually engages.
      console.warn(
        `chat: tool replay ceiling fired for ${toolName} ` +
          `(content was ${content.length.toLocaleString()} bytes, ` +
          `kept first ${TOOL_REPLAY_HARD_CAP_BYTES.toLocaleString()})`,
      );
    }
    return { kind: 'tool', text: `[Tool ${toolName} returned: ${body}]` };
  }
  return { kind: 'turn', text: content };
}

// Session-history fetch fallback.
//
// Module-level memo keyed by sessionId. On a fetch success, we store
// the raw chronological messages with a 5s expiry. On a fetch failure,
// we fall back to the cached value (if any) so a transient MCP blip
// doesn't drop the agent's memory of the conversation mid-turn.
//
// 5s is the right TTL window: long enough to absorb back-to-back
// turns without re-fetching (a typical chat-pace round-trip is
// ~3-5s including model think time), short enough that
// freshly-persisted messages from the in-flight turn show up on the
// next call. Bigger TTLs would risk staleness; smaller TTLs would
// barely help during clustered turns.
//
// Cache key is sessionId only — message content is the same regardless
// of model, so two turns of the same session with different models
// share the cache. The budget walk runs per-turn against `raw`, so
// per-model differences materialize at the rendering layer, not the
// fetch layer.
//
// Note: this is a per-process cache. Phantom runs as a single Next.js
// server, so per-process is per-instance. If we ever scale-out the
// agent (multiple replicas behind a load balancer), this cache will
// silently de-dup per-replica, not globally — fine for short-TTL data
// like this.
interface HistoryCacheEntry {
  raw: PersistedMessage[];
  expiresAt: number;
}
const HISTORY_CACHE_TTL_MS = 5_000;
const historyCache = new Map<string, HistoryCacheEntry>();

/** Fetch raw persisted messages for a session, with in-process memo
 *  + fallback-on-failure. Returns the chronological message array
 *  (oldest-first) or [] if no cache and fetch fails.
 */
async function fetchSessionMessagesWithCache(
  sessionId: string,
  trigger: string | undefined,
): Promise<PersistedMessage[]> {
  const now = Date.now();
  const cached = historyCache.get(sessionId);
  if (cached && cached.expiresAt > now) {
    return cached.raw;
  }

  try {
    // Paginate the GET. We ask for newest-first
    // (`ascending=false`) so a long session never loses its most
    // recent turns; reversed client-side for the budget walk.
    const data = await callMcpServer<{ messages?: PersistedMessage[] }>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=300&ascending=false`,
      {
        method: 'GET',
        headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
      },
    );
    const newestFirst = Array.isArray(data?.messages) ? data.messages : [];
    const raw = newestFirst.length === 0 ? [] : [...newestFirst].reverse();
    historyCache.set(sessionId, { raw, expiresAt: now + HISTORY_CACHE_TTL_MS });
    return raw;
  } catch (err) {
    // Fall back to the cached snapshot if any. An intermittent MCP blip
    // would otherwise wipe the agent's memory of the conversation for
    // that one turn; using the slightly-stale snapshot keeps continuity.
    if (cached) {
      console.warn(
        `chat: history fetch for ${sessionId} failed; using cached snapshot:`,
        err instanceof Error ? err.message : err,
      );
      return cached.raw;
    }
    console.warn(
      `chat: failed to load session history for ${sessionId} — proceeding without context:`,
      err instanceof Error ? err.message : err,
    );
    return [];
  }
}

/**
 * Read the session's persisted `preferred_model`
 * (set via the `/model <name>` slash command). Memoized for 30s per
 * session so the read doesn't add an MCP round-trip to every turn —
 * the operator only changes models once per cluster of turns, so the
 * TTL is generous without risking visible staleness.
 *
 * The chat handler resolves the effective model as:
 *   header-dropdown override (requestedModel)
 *   ?? session.metadata.preferred_model
 *   ?? the install default (settings key `defaultModel`)
 *   ?? the derived default (first configured provider's recommended model)
 *
 * Returns undefined when no preference is set (or the fetch fails —
 * the resolution chain just falls through to the install default).
 */
interface PreferredModelCacheEntry {
  value: string | undefined;
  expiresAt: number;
}
const PREFERRED_MODEL_CACHE_TTL_MS = 30_000;
const preferredModelCache = new Map<string, PreferredModelCacheEntry>();

async function loadSessionPreferredModel(
  sessionId: string,
  trigger: string | undefined,
): Promise<string | undefined> {
  const now = Date.now();
  const cached = preferredModelCache.get(sessionId);
  if (cached && cached.expiresAt > now) return cached.value;
  try {
    const data = await callMcpServer<{
      session?: { meta?: Record<string, unknown> };
    }>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'GET',
      headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
    });
    const raw = data?.session?.meta?.['preferred_model'];
    const value =
      typeof raw === 'string' && raw.trim().length > 0 ? raw.trim() : undefined;
    preferredModelCache.set(sessionId, {
      value,
      expiresAt: now + PREFERRED_MODEL_CACHE_TTL_MS,
    });
    return value;
  } catch (err) {
    // Best-effort. A failure just means we use the runtime default.
    if (cached) return cached.value;
    console.warn(
      `chat: failed to read preferred_model for ${sessionId}:`,
      err instanceof Error ? err.message : err,
    );
    return undefined;
  }
}

/**
 * Read the session's persisted `approval_mode` (set via the
 * chat-header dropdown or the /approval slash command). Mirrors the
 * preferred_model cache pattern: 30s TTL, best-effort fall-through.
 *
 * Values:
 *   'manual' (default): every gated tool call shows an inline approval
 *     card and blocks until the operator clicks Approve.
 *   'bypass': the chat handler attaches X-Phantom-Approval-Bypass: 1
 *     to every MCP call, so gated tools auto-approve (still recording
 *     audit rows with auto_approved=true).
 *
 * Anything other than 'bypass' resolves to manual — the default-secure
 * posture. Empty / missing metadata = manual.
 *
 * The type itself lives in lib/system-prompt.ts so the
 * prompt builder and the chat handler agree on the literal union.
 * Imported from there at the top of this file.
 */

interface ApprovalModeCacheEntry {
  value: ApprovalMode;
  expiresAt: number;
}
const APPROVAL_MODE_CACHE_TTL_MS = 30_000;
const approvalModeCache = new Map<string, ApprovalModeCacheEntry>();

async function loadSessionApprovalMode(
  sessionId: string,
  trigger: string | undefined,
): Promise<ApprovalMode> {
  const now = Date.now();
  const cached = approvalModeCache.get(sessionId);
  if (cached && cached.expiresAt > now) return cached.value;
  try {
    const data = await callMcpServer<{
      session?: { meta?: Record<string, unknown> };
    }>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'GET',
      headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
    });
    const raw = data?.session?.meta?.['approval_mode'];
    const value: ApprovalMode = raw === 'bypass' ? 'bypass' : 'manual';
    approvalModeCache.set(sessionId, {
      value,
      expiresAt: now + APPROVAL_MODE_CACHE_TTL_MS,
    });
    return value;
  } catch (err) {
    if (cached) return cached.value;
    console.warn(
      `chat: failed to read approval_mode for ${sessionId}:`,
      err instanceof Error ? err.message : err,
    );
    return 'manual';
  }
}

/** Invalidate the approval-mode cache for a session. Currently unused
 *  externally — the dropdown PATCHes via the proxy route, then the
 *  next chat turn naturally re-reads after the 30s TTL elapses. Kept
 *  as a non-exported helper in case the dropdown needs immediate
 *  consistency in a future patch (e.g. "switch to bypass NOW for the
 *  in-flight turn"). Cannot be `export`ed from a Next.js route file —
 *  the App Router rejects non-method exports. */
function invalidateSessionApprovalModeCache(sessionId: string): void {
  approvalModeCache.delete(sessionId);
}
// Suppress "unused" lint until a caller materializes; harmless.
void invalidateSessionApprovalModeCache;

/** Invalidate the preferred-model cache for a session. Called by the
 *  /model handler after a PATCH so the same turn (or the next one)
 *  reads the freshly-set value instead of the stale cached one. */
function invalidateSessionPreferredModelCache(sessionId: string): void {
  preferredModelCache.delete(sessionId);
}

/** What a slash command needs to know about the session's model. */
interface SessionModelState {
  result: TurnModelResult;
  entries: ModelEntry[];
  /** The session's stored `/model` preference, as written. */
  session: string | undefined;
  installDefault: string | undefined;
}

/**
 * Resolve the model a slash command runs on: header, session preference,
 * install default, derived default. The same chain a normal turn uses.
 */
async function resolveSessionModel(args: {
  sessionId: string;
  isNewSession: boolean;
  trigger: string | undefined;
  requestedModel: string | undefined;
  requestedProvider: string | undefined;
  runtimeConfig: EffectiveRuntimeConfig;
}): Promise<SessionModelState> {
  const session = args.isNewSession
    ? undefined
    : await loadSessionPreferredModel(args.sessionId, args.trigger);
  const { result, entries, installDefault } = await resolveModelForRequest(
    { header: args.requestedModel, headerProvider: args.requestedProvider, session },
    args.runtimeConfig,
  );
  return { result, entries, session, installDefault };
}

/** Fetch the prior persisted messages for a session and convert them to
 *  provider-neutral messages. Returns [] if the session is
 *  brand-new or the fetch fails (best-effort — a missing history
 *  shouldn't block the turn).
 *
 *  Replaying messages here is what lets the agent remember what was
 *  just discussed. The replay is token-budgeted: instead of a fixed
 *  N-message slice, we walk newest-to-oldest accumulating estimated
 *  tokens until we hit the model's input budget (computed from its
 *  context cap minus output reserve, with a 30% safety margin for
 *  tokenizer drift). A 5s in-process cache with fallback-on-failure
 *  sits underneath, so
 *  intermittent MCP blips don't wipe the agent's memory mid-turn.
 *
 *  Why budget-walk instead of message-count: with a message count, a
 *  single 50k-token tool result would silently consume the entire
 *  history slice. With a token budget it just consumes its
 *  proportional share and the rest of the conversation continues to
 *  fit. Long sessions with mostly small turns get *more* context,
 *  not less.
 */
/**
 * Auto-compaction hooks. Optional callbacks that
 * loadSessionHistory uses to summarize the dropped portion of history
 * when the budget walk would otherwise discard it. If `summarize` is
 * absent, behavior falls through to the budget walk's hard truncation.
 */
interface AutoCompactionHooks {
  /** Wraps an LLM call. Receives instructions + transcript, returns
   *  the model's summary text. Provider-agnostic; caller wires this
   *  to its summarizer of choice. */
  summarize?: (instructions: string, transcript: string) => Promise<string>;
  /** Persists the auto-compaction checkpoint so subsequent turns
   *  honor it via the existing checkpoint-aware path.
   *  Skip if you only want this turn to benefit (e.g., dry-run). */
  persistCheckpoint?: (
    summary: string,
    coversUntil: string,
    messagesSummarized: number,
  ) => Promise<void>;
  /** Live-telemetry hook. The chat route wires this to sendEvent so
   *  /observability/pipeline + the live-telemetry panel surface
   *  compaction activity in real-time. */
  onCompactionEvent?: (
    kind: 'start' | 'end' | 'failed',
    stats?: Record<string, unknown>,
  ) => void;
}

/** Threshold for auto-compaction: only fire if we'd otherwise drop
 *  this many messages. Below this, hard truncation is fine —
 *  summarizing 2-3 messages costs more than it saves. */
const AUTO_COMPACT_MIN_DROPPED = 5;

async function loadSessionHistory(
  sessionId: string,
  trigger: string | undefined,
  modelName: string | undefined,
  hooks?: AutoCompactionHooks,
): Promise<TurnMessage[]> {
  // Cached fetch with fallback. Pure data-shape conversion
  // happens below.
  const fetched = await fetchSessionMessagesWithCache(sessionId, trigger);
  if (fetched.length === 0) return [];

  // Checkpoint awareness. Find the LATEST compaction-
  // checkpoint message; if present, slice the replay from it forward.
  // The checkpoint's content is the summary, persisted as role=system
  // with meta.kind=compaction-checkpoint. We render it as a single
  // user-role observation so the user/assistant alternation stays
  // valid and the model treats the summary as "what happened before
  // this turn." Anything BEFORE the checkpoint is conceptually
  // already-summarized and gets dropped from replay; the disk
  // transcript is unchanged.
  let raw: PersistedMessage[] = fetched;
  let priorCheckpointSummary: string | null = null;
  for (let i = fetched.length - 1; i >= 0; i--) {
    if (isCompactionCheckpoint(fetched[i])) {
      priorCheckpointSummary = fetched[i].content;
      raw = fetched.slice(i + 1); // everything after the checkpoint
      break;
    }
  }

  try {
    // Token-budgeted walk. Compute the input budget for
    // this turn's model (cap × 0.7 - output reserve, with an 8k floor
    // for very small models). Walk raw newest-to-oldest, estimate
    // each message's rendered cost via renderMessageForReplay() so
    // tool-row truncation is reflected, and stop accumulating when
    // we'd exceed budget. Slice from there.
    //
    // If a compaction checkpoint exists, pre-allocate
    // its token cost from the budget and emit it as the first
    // user-role message in `contents`. The budget walk over `raw`
    // (the post-checkpoint tail) gets a shrunk budget so the
    // checkpoint + replay together fit.
    let checkpointText = priorCheckpointSummary
      ? `[Earlier in this conversation, summarized via /compress: ${priorCheckpointSummary}]`
      : null;
    let checkpointTokens = checkpointText
      ? estimateMessageTokens(checkpointText)
      : 0;
    const budget = Math.max(
      0,
      computeInputBudget(modelName) - checkpointTokens,
    );
    let usedTokens = 0;
    let firstKeptIdx = raw.length;
    for (let i = raw.length - 1; i >= 0; i--) {
      const rendered = renderMessageForReplay(raw[i]);
      if (!rendered) continue;
      const cost = estimateMessageTokens(rendered.text);
      if (usedTokens + cost > budget) break;
      usedTokens += cost;
      firstKeptIdx = i;
    }

    // ── Auto-compaction at the budget edge ──────────
    //
    // If the budget walk would drop AT LEAST AUTO_COMPACT_MIN_DROPPED
    // messages AND we have a summarizer hook, summarize the dropped
    // portion into a checkpoint instead of letting it fall off.
    //
    // Tool-pair preservation: snap firstKeptIdx forward
    // past any consecutive tool rows so the cut point lands on a
    // user/assistant boundary. Otherwise the replay would start with
    // tool results whose `[Tool X returned: ...]` rendering would
    // imply preceding context the model has no record of.
    while (
      firstKeptIdx < raw.length &&
      firstKeptIdx > 0 &&
      raw[firstKeptIdx - 1].role === 'tool'
    ) {
      // The message AT firstKeptIdx is what we keep; the message
      // BEFORE it is the one that just got dropped. If that dropped
      // message is a tool row, push the cut earlier (smaller
      // firstKeptIdx) so the tool burst is fully in the summary.
      firstKeptIdx--;
    }

    const droppedCount = firstKeptIdx;
    if (
      droppedCount >= AUTO_COMPACT_MIN_DROPPED &&
      hooks?.summarize !== undefined
    ) {
      hooks.onCompactionEvent?.('start', {
        kind: 'auto',
        messages_to_summarize: droppedCount,
      });

      try {
        // Build the summarizer input. If a /compress checkpoint
        // already exists for this session, prepend it as a synthetic
        // "earlier summary" so the new auto-checkpoint covers
        // EVERYTHING from the conversation start through firstKeptIdx
        // — the new checkpoint then supersedes the prior one cleanly.
        const summaryInput: CompactionInputMessage[] = [];
        if (priorCheckpointSummary) {
          summaryInput.push({
            role: 'system',
            content: `[Prior compaction summary]\n${priorCheckpointSummary}`,
            created_at: undefined,
          });
        }
        summaryInput.push(...raw.slice(0, firstKeptIdx));

        const result = await compactMessages(
          summaryInput,
          hooks.summarize,
        );
        if (!result) {
          throw new Error('summarizer returned empty');
        }

        // Fire-and-forget persist. The next turn picks up
        // this checkpoint via the checkpoint discovery loop, so the
        // amortization kicks in on the FOLLOWING request, not this
        // one. await is best-effort: persist failure logs but doesn't
        // block the current turn.
        if (hooks.persistCheckpoint) {
          try {
            await hooks.persistCheckpoint(
              result.summary,
              result.coversUntil,
              result.messagesSummarized,
            );
          } catch (persistErr) {
            console.warn(
              `chat: auto-compaction checkpoint persist failed:`,
              persistErr instanceof Error ? persistErr.message : persistErr,
            );
          }
        }

        // Replace this turn's checkpointText with the freshly-
        // produced summary so it takes effect immediately. Drop the
        // dropped portion from raw (firstKeptIdx becomes 0).
        checkpointText = `[Compaction summary covering ${result.messagesSummarized} prior messages: ${result.summary}]`;
        checkpointTokens = estimateMessageTokens(checkpointText);
        raw = raw.slice(firstKeptIdx);
        firstKeptIdx = 0;

        hooks.onCompactionEvent?.('end', {
          kind: 'auto',
          messages_summarized: result.messagesSummarized,
          summary_chars: result.summary.length,
        });
      } catch (err) {
        // The client went away mid-summary: end the turn, do not fall back to
        // truncation or report a compaction failure.
        if (isAbortedError(err)) throw err;
        // Fallback. Summarizer failure shouldn't block
        // the chat turn. Log + emit a `failed` event + fall through
        // to the hard-truncation behavior (the
        // dropped messages just don't get replayed).
        console.warn(
          `chat: auto-compaction failed; falling back to hard truncation:`,
          err instanceof Error ? err.message : err,
        );
        hooks?.onCompactionEvent?.('failed', {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }

    const slice = raw.slice(firstKeptIdx);
    const contents: TurnMessage[] = [];

    if (checkpointText) {
      contents.push({ role: 'user', text: checkpointText });
    }

    // Tool rows (rendered via renderMessageForReplay) are
    // INCLUDED in the replay, truncated, wrapped as
    // `[Tool <name> returned: <truncated>]`. Consecutive tool rows
    // coalesce into one user-role message via flushToolNotes() below.
    let pendingToolNotes: string[] = [];
    const flushToolNotes = () => {
      if (pendingToolNotes.length === 0) return;
      contents.push({ role: 'user', text: pendingToolNotes.join('\n') });
      pendingToolNotes = [];
    };

    for (const m of slice) {
      const rendered = renderMessageForReplay(m);
      if (!rendered) continue;
      if (rendered.kind === 'tool') {
        pendingToolNotes.push(rendered.text);
        continue;
      }
      // Non-tool: flush any pending tool notes before us so they
      // appear in the right narrative position, then emit.
      flushToolNotes();
      contents.push({
        role: m.role === 'assistant' ? 'assistant' : 'user',
        text: rendered.text,
      });
    }
    // Trailing tool notes (rare — turn ended mid-tool) still flushed.
    flushToolNotes();
    return contents;
  } catch (err) {
    // Don't fail the turn — a missing history just means the agent
    // operates statelessly for this turn. Log so we can detect
    // patterns of failure.
    console.warn(
      `chat: failed to load session history for ${sessionId} — proceeding without context:`,
      err instanceof Error ? err.message : err,
    );
    return [];
  }
}

type DebugStep = {
  time: string;
  stage: string;
  detail: string;
};

// Cache the BASE tool specs (MCP tools only). The synthetic
// `subagent_create` tool is appended per-request based on the operator's
// `chat_subagents_enabled` preference. Caching the full set including
// subagent_create would make toggling impossible without a TTL-based
// cache flush. The spec objects are never mutated, and each adapter caches
// its rendered form per spec object (Gemini's sanitized declarations), so
// keeping the same objects across requests keeps the per-call cost low.
let cachedBaseTools: ToolSpec[] | null = null;
let cachedBaseToolsAt = 0;
let cachedBaseToolsCount = 0;

/**
 * Read the operator's `chat_subagents_enabled` preference from operator-state.
 * Defaults to `true` (subagents enabled).
 * Operator can flip via the chat header toggle (UI) or PUT
 * /api/v1/operator-state/chat_subagents_enabled directly (API).
 *
 * Failures fall back to enabled — the toggle is an opt-out, so if the
 * read fails (operator_state.db not yet seeded, network blip, etc.)
 * we preserve the documented default behavior.
 */
async function readSubagentsEnabled(): Promise<boolean> {
  try {
    const result = await callMcpServer<{ value?: unknown }>(
      `/api/v1/operator-state/${encodeURIComponent('chat_subagents_enabled')}`,
    );
    const raw = result?.value;
    // operator_state stores the value as the JSON-decoded shape the
    // hook chose. The UI persists either `true` / `false` directly
    // or `{ enabled: <bool> }`; accept both. Any other shape (or
    // missing) → default true.
    if (typeof raw === 'boolean') return raw;
    if (raw && typeof raw === 'object' && 'enabled' in (raw as Record<string, unknown>)) {
      const v = (raw as Record<string, unknown>).enabled;
      return typeof v === 'boolean' ? v : true;
    }
    return true;
  } catch {
    return true;
  }
}

// ─── Empty-response fallback ──────────────────────────────────────────
//
// Build a context-aware message when the model finishes a turn without
// emitting any text (only function calls). Replaces the earlier
// hard-coded "No model response was returned. Review the tool results
// above or try a smaller request." string — that text was unhelpful in
// the most common case (model called tools successfully but didn't
// narrate, e.g. after an approval-gated jobs_create where the post-
// approval response is sometimes a bare functionCall with no text).
//
// Distinguishes the finish reasons that matter (neutral FinishReason):
//   stop / tool_use  — the model chose to stop (most common when text is
//                      empty after tools succeed). We summarize what ran.
//   max_tokens       — output got truncated. We say so explicitly so the
//                      operator knows to ask a smaller question.
//   safety           — content was blocked. Surface that vs. silent.
//   recitation       — same family; surface explicitly.
//   refusal          — the model declined; context_exceeded — the history
//                      no longer fits. Neither occurs on Gemini today.
/**
 * Pre-tool-call preamble synthesis.
 *
 * Render a one-line "I'll run <tool> with <key args>" string for the
 * chat thread when the model emitted a function call without any
 * accompanying text. Goal: the operator never sees an approval card
 * pop out of nowhere; there's always at least a server-synthesized
 * sentence above it explaining what's about to happen.
 *
 * Argument summarization rules (kept simple on purpose):
 *   - Pick at most 4 args to surface inline (the rest live in the
 *     approval card's expandable "Raw arguments").
 *   - Prefer human-meaningful keys when present: name, prompt,
 *     description, cron, instance_id, connector_id, url, query —
 *     anything that gives the operator a clue about the action.
 *   - Truncate any single value to 80 chars so the preamble stays
 *     readable; never show secret-looking keys (api_key, password,
 *     token, secret) — those go to the args expander, not the
 *     plain-text chat history.
 *   - For `subagent_create` and other meta-tools, prefer their
 *     `task` / `goal` field when present.
 *
 * Returns null when there's nothing useful to say (e.g. no args at
 * all). The caller skips the sendEvent in that case rather than
 * emit "I'll run X with no arguments."
 */
const _PREFERRED_ARG_KEYS = [
  'name', 'task', 'goal', 'prompt', 'description', 'cron',
  'connector_id', 'instance_id', 'instance_name',
  'url', 'query', 'pattern', 'format', 'destination',
  'scenario', 'rate_per_second', 'duration_seconds',
  'session_id', 'tool_name', 'reason',
];
const _SECRET_LOOKING_KEYS = /^(api_?key|password|secret|token|bearer|kek|jwt)$/i;

function _summarizeArgValue(value: unknown): string {
  if (value === null || value === undefined) return '∅';
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 80 ? `${trimmed.slice(0, 77)}…` : trimmed;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const inner = value.length === 0 ? '' : `${value.length} item${value.length === 1 ? '' : 's'}`;
    return `[${inner}]`;
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value as Record<string, unknown>);
    return keys.length === 0 ? '{}' : `{${keys.slice(0, 3).join(', ')}${keys.length > 3 ? ', …' : ''}}`;
  }
  return String(value).slice(0, 80);
}

function formatToolPreamble(
  toolName: string,
  args: Record<string, unknown>,
): string | null {
  const allKeys = Object.keys(args);
  if (allKeys.length === 0) {
    // No args — just announce the tool. Useful for things like
    // approvals_list_pending, list_workers, etc., where the act of
    // calling IS the entire intent.
    return `I'll call \`${toolName}\`.`;
  }
  // Filter out secret-looking keys before deciding what to surface.
  const safeKeys = allKeys.filter((k) => !_SECRET_LOOKING_KEYS.test(k));
  // Order: preferred keys first (in their declared order), then
  // remaining safe keys alphabetically. Cap at 4.
  const preferred = _PREFERRED_ARG_KEYS.filter((k) => safeKeys.includes(k));
  const remaining = safeKeys
    .filter((k) => !preferred.includes(k))
    .sort();
  const surface = [...preferred, ...remaining].slice(0, 4);
  if (surface.length === 0) {
    // Everything was secret-looking. Don't leak through the preamble.
    return `I'll call \`${toolName}\` (arguments hidden — credentials).`;
  }
  const parts = surface.map((k) => `${k}=\`${_summarizeArgValue(args[k])}\``);
  const more = safeKeys.length > surface.length
    ? ` (+ ${safeKeys.length - surface.length} more)`
    : '';
  return `I'll call \`${toolName}\` with ${parts.join(', ')}${more}.`;
}

function synthesizeFallbackText(
  toolCalls: Array<{ tool: string; args: Record<string, unknown>; result: string; error?: string }>,
  finish: FinishReason | undefined,
): string {
  // Tool-flow specific: certain tool names map cleanly to "X happened"
  // confirmations. Operators care most about whether the side-effecting
  // call (jobs_create, marketplace_install, …) succeeded; everything else
  // is preamble (memory_search, *_get).
  const SIDE_EFFECT_TOOLS = new Set([
    'jobs_create', 'jobs_update', 'jobs_delete', 'jobs_run_now',
    'personality_update', 'personality_reset',
    'settings_update', 'settings_reset',
    'memory_store', 'notifications_dismiss', 'approvals_resolve',
    // Simulation + catalog/data-source mutations the operator
    // cares about confirming. Omitting them would let a "simulate Okta to
    // XSIAM" turn that started a data worker recap only `memory_store`,
    // hiding the actual action. This set is hand-maintained — when a new
    // operator-meaningful side-effecting tool ships, add it here so the
    // no-text fallback recap names it.
    'phantom_create_data_worker', 'phantom_kill_worker',
    'marketplace_install', 'marketplace_uninstall', 'connector_upload',
    'data_sources_edit', 'data_sources_rollback',
  ]);

  const sideEffects = toolCalls.filter((tc) => SIDE_EFFECT_TOOLS.has(tc.tool));

  // Truncation / safety prefixes — these go FIRST so the operator sees
  // the limit cause before the recap.
  if (finish === 'max_tokens') {
    if (sideEffects.length > 0) {
      const list = sideEffects.map((tc) => `\`${tc.tool}\``).join(', ');
      return `✓ Completed ${list} but my reply was cut off by the token limit. Ask me to summarize what was done if you need more detail.`;
    }
    return '⚠ My response hit the token limit before I could finish. Try a more focused request.';
  }
  if (finish === 'safety' || finish === 'recitation') {
    return `⚠ My response was blocked (\`${finish.toUpperCase()}\`). Try rephrasing your request.`;
  }
  if (finish === 'refusal') {
    return '⚠ The model declined to answer. Try rephrasing your request.';
  }
  if (finish === 'context_exceeded') {
    return '⚠ This conversation no longer fits the model\'s context window. Run /compress or start a new chat, then try again.';
  }

  // Normal STOP-with-no-text case: model finished cleanly but had nothing
  // to say. Recap what actually ran.
  if (sideEffects.length > 0) {
    const list = sideEffects.map((tc) => `\`${tc.tool}\``).join(', ');
    const verb = sideEffects.length === 1 ? 'change' : 'changes';
    return `✓ Done. Applied ${sideEffects.length} ${verb}: ${list}. Let me know if you need a summary or next steps.`;
  }
  if (toolCalls.length > 0) {
    // Read-only flow: the agent looked things up but didn't act. Most
    // often this means the model had no follow-up (e.g. the lookup was
    // its own answer to a previous question that already got responded
    // to). Less alarming phrasing than the original.
    return `I checked ${toolCalls.length} tool${toolCalls.length === 1 ? '' : 's'} but didn't generate a follow-up message. Let me know what you'd like next.`;
  }
  // No tools, no text — genuinely empty turn. Likely a transient model
  // hiccup. Ask the user to retry.
  return 'I didn\'t generate a response this turn. Please try again or rephrase your request.';
}

// ─── Approval-poll helpers (chat-driven self-mod UX) ────

interface ApprovalRow {
  id: string;
  tool: string;
  namespaced: string;
  actor: string | null;
  risk_tier?: string;
  created_at: string;
  args: Record<string, unknown>;
  status: string;
}

/**
 * Get current pending approval IDs from the MCP. Used as a snapshot
 * just before a gated tool call so the polling loop can detect the
 * NEW row created by that call (rather than reacting to unrelated
 * pending rows).
 */
/**
 * Fetch the set of currently-pending approval IDs.
 *
 * Accepts an optional sessionId and scopes the listing to
 * `origin=chat:<sessionId>` so the chat-side poll loop only sees
 * approvals THIS chat session created. Without the filter, a
 * job-fired approval (origin=job:<name>) landing concurrently would
 * appear in the snapshot diff and the chat UI would render an
 * inline card for an approval the operator can't actually act on
 * from this surface.
 *
 * Falls back to unfiltered listing when sessionId is omitted —
 * keeps the fast-path callers working unchanged.
 */
async function fetchPendingApprovalIds(
  sessionId?: string,
): Promise<Set<string>> {
  try {
    const params = new URLSearchParams({ status: 'pending' });
    if (sessionId) params.set('origin', `chat:${sessionId}`);
    const resp = await callMcpServer<{ approvals?: ApprovalRow[] }>(
      `/api/v1/approvals?${params.toString()}`,
      { method: 'GET', timeoutMs: 5000 },
    );
    return new Set((resp.approvals ?? []).map((a) => a.id));
  } catch {
    return new Set<string>();
  }
}

/**
 * Race against the bus.wait_async block: poll /api/v1/approvals every
 * 250ms looking for a new pending row matching the just-called tool.
 * Calls onFound(row) at most ONCE then exits. Also exits on signal
 * abort (tool call resolved, no need to keep polling) or after
 * MAX_POLL_MS (the operator never approved; the chat will see the
 * timeout via the original tool call's wait_async).
 */
async function pollForNewApproval({
  signal,
  snapshot,
  toolName,
  onFound,
  sessionId,
}: {
  signal: AbortSignal;
  snapshot: Set<string>;
  toolName: string;
  onFound: (row: ApprovalRow) => void;
  /** Scopes the poll to chat:<sessionId> so a job-fired
   *  approval landing concurrently doesn't trigger a spurious card
   *  in the wrong chat thread. */
  sessionId?: string;
}): Promise<void> {
  const MAX_POLL_MS = 6_000; // ~24 polls. The MCP gate would fire by then.
  const POLL_INTERVAL_MS = 250;
  const deadline = Date.now() + MAX_POLL_MS;
  let found = false;
  // Server-side origin filter when sessionId is known.
  // Falls back to unfiltered ?status=pending for backwards-compat
  // (older callers that don't have a session in scope).
  const params = new URLSearchParams({ status: 'pending' });
  if (sessionId) params.set('origin', `chat:${sessionId}`);
  const url = `/api/v1/approvals?${params.toString()}`;
  while (!signal.aborted && Date.now() < deadline && !found) {
    try {
      const resp = await callMcpServer<{ approvals?: ApprovalRow[] }>(
        url,
        { method: 'GET', timeoutMs: 2000 },
      );
      for (const row of resp.approvals ?? []) {
        if (snapshot.has(row.id)) continue;
        // Match by tool name (and bare-name forms): the gate uses
        // tool=bare in self_mod_tools.py, so the pending row's
        // `tool` field will equal the toolName the chat passed.
        if (row.tool === toolName || row.namespaced === toolName) {
          onFound(row);
          found = true;
          break;
        }
      }
    } catch {
      // Transient — retry on next tick.
    }
    if (found || signal.aborted) break;
    await new Promise((resolve) => {
      const t = setTimeout(resolve, POLL_INTERVAL_MS);
      signal.addEventListener('abort', () => {
        clearTimeout(t);
        resolve(undefined);
      });
    });
  }
}

async function getTurnTools(
  mcpClient: PhantomMCPClient,
  runtimeConfig: EffectiveRuntimeConfig,
  logDebug: (stage: string, detail: string) => void,
  subagentsEnabled: boolean,
): Promise<ToolSpec[]> {
  const parsedToolCacheTtl = Number(runtimeConfig.MCP_TOOL_CACHE_TTL_MS || 300000);
  const mcpToolCacheTtlMs = Number.isFinite(parsedToolCacheTtl) && parsedToolCacheTtl > 0
    ? parsedToolCacheTtl
    : 300000;
  const now = Date.now();

  // Base specs are cached (TTL-bound). The synthetic
  // `subagent_create` tool is appended PER REQUEST based on
  // `subagentsEnabled` so the toggle takes effect immediately on the
  // next turn without waiting for cache eviction.
  let baseTools = cachedBaseTools;
  if (baseTools && now - cachedBaseToolsAt < mcpToolCacheTtlMs) {
    logDebug('mcp', `Loaded ${cachedBaseToolsCount} cached base tool schemas`);
  } else {
    const mcpTools = await mcpClient.listTools();
    logDebug('mcp', `Loaded ${mcpTools.length} tools from MCP`);
    baseTools = mcpTools.map((tool: MCPTool): ToolSpec => ({
      name: tool.name,
      description: tool.description || '',
      inputSchema: (tool.inputSchema || {}) as Record<string, unknown>,
    }));
    cachedBaseTools = baseTools;
    cachedBaseToolsAt = now;
    cachedBaseToolsCount = baseTools.length;
    logDebug('mcp', `Cached ${cachedBaseToolsCount} base tool schemas`);
  }

  // Append the synthetic `subagent_create`
  // function so the model sees it as just-another-tool. The
  // chat-route's tool dispatch loop intercepts calls to this
  // name and routes them to runSubagent (no MCP round-trip).
  // Gated by the operator's `chat_subagents_enabled`
  // preference. When false, the spec is omitted and the model
  // sees a catalog without subagent_create.
  const tools = subagentsEnabled
    ? [...baseTools, SUBAGENT_CREATE_TOOL_SPEC]
    : [...baseTools];

  logDebug(
    'mcp',
    `Tool catalog: ${tools.length} schemas` +
      (subagentsEnabled ? ' (incl. subagent_create)' : ' (subagents disabled)'),
  );
  return tools;
}

/**
 * Operator-tunable routing policy. The chat handler
 * fetches it once per request from /api/v1/personality and passes it
 * into the turn's system prompt so it reflects the operator's
 * current configuration. Falls back to sensible defaults when the
 * personality store doesn't yet have the field (older blobs that
 * pre-date this commit).
 */
// ActionPolicy interface + DEFAULT_ACTION_POLICY + renderActionPolicyBlock
// + the static system prompt text all live in lib/system-prompt.ts (a clean
// cache boundary, and the static narrative stays out of route.ts).

/**
 * Returns the two pieces of personality the system prompt
 * builder needs — actionPolicy (safety rails) + personalityMd
 * (operator-defined persona markdown). One MCP fetch, both consumers
 * use the result.
 */
interface PersonalityForPrompt {
  policy: ActionPolicy;
  personalityMd: string | null;
}

async function fetchPersonalityForPrompt(): Promise<PersonalityForPrompt> {
  try {
    const resp = await callMcpServer<{ personality?: Record<string, unknown> }>(
      '/api/v1/personality',
      { method: 'GET', timeoutMs: 4000 },
    );
    const blob = (resp?.personality ?? {}) as Record<string, unknown>;
    const raw = blob['actionPolicy'];
    let policy: ActionPolicy = DEFAULT_ACTION_POLICY;
    if (raw && typeof raw === 'object') {
      const p = raw as Partial<ActionPolicy>;
      policy = {
        localCategories: Array.isArray(p.localCategories) ? p.localCategories : DEFAULT_ACTION_POLICY.localCategories,
        externalCategories: Array.isArray(p.externalCategories) ? p.externalCategories : DEFAULT_ACTION_POLICY.externalCategories,
        askWhenUnsure: typeof p.askWhenUnsure === 'boolean' ? p.askWhenUnsure : DEFAULT_ACTION_POLICY.askWhenUnsure,
        confirmLocalActions: ['approve-card', 'soft', 'off'].includes(p.confirmLocalActions as string)
          ? (p.confirmLocalActions as ActionPolicy['confirmLocalActions'])
          : DEFAULT_ACTION_POLICY.confirmLocalActions,
        confirmExternalActions: ['approve-card', 'soft', 'off'].includes(p.confirmExternalActions as string)
          ? (p.confirmExternalActions as ActionPolicy['confirmExternalActions'])
          : DEFAULT_ACTION_POLICY.confirmExternalActions,
      };
    }
    const md = blob['personalityMd'];
    const personalityMd = typeof md === 'string' && md.trim() ? md : null;
    return { policy, personalityMd };
  } catch {
    return { policy: DEFAULT_ACTION_POLICY, personalityMd: null };
  }
}

/** Back-compat shim: callers that only need the policy can keep calling
 *  fetchActionPolicy() — internally goes through the same fetch.  */
async function fetchActionPolicy(): Promise<ActionPolicy> {
  return (await fetchPersonalityForPrompt()).policy;
}


/**
 * One-shot summarization for /compress, /plan and auto-compaction. No tools,
 * no system memory/KB instructions, no chat history, no thinking: just the
 * summarization prompt + transcript, answered with text on the given model
 * (else the install default).
 *
 * Deliberately not a parameterization of the chat turn, which sets up the
 * full agent persona and fetches MCP tools: inlining that would inflate the
 * compaction request to ~15kb of system prompt for no benefit and waste
 * tokens that should be going to the summary.
 */
function summarizeViaModel(
  systemInstructionText: string,
  userContent: string,
  runtimeConfig: EffectiveRuntimeConfig,
  modelRef: ModelRef,
  purpose: 'summarize' | 'plan' = 'summarize',
  onEvent?: (event: ProviderEvent) => void,
  // Every call site passes the request's signal (scripts/test-chat-abort.mjs
  // checks each one); a missing signal would let a closed browser keep paying
  // for the call.
  signal?: AbortSignal,
): Promise<string> {
  return summarizeText(
    modelRef,
    systemInstructionText,
    userContent,
    purpose,
    { creds: credsFromRuntimeConfig(runtimeConfig), onEvent, signal },
    modelDispatchDeps(),
  );
}

/**
 * System prompt for /plan mode.
 *
 * Instructs the model to enumerate the steps it would take WITHOUT
 * actually invoking any tools. The output goes into the chat thread
 * verbatim so the operator can review before approving.
 *
 * Format requirements:
 *
 *   - Numbered steps (1., 2., 3., ...).
 *   - Each step names the tool it would invoke and the args.
 *   - Each step has a one-line "why" explaining the operator's
 *     intent (not a tool-doc paste).
 *   - Risk callouts on destructive steps (CALDERA operations,
 *     scenarios against shared destinations, XSIAM PAPI writes).
 *
 * Patterned on SnowAgent's plan-mode instructions
 * (snow-agent-complete/snow-agent/06-tools-permissions/),
 * adapted for Phantom's SOC vocabulary.
 */
const PLAN_MODE_INSTRUCTIONS = `You are in PLAN MODE. The operator
asked you to enumerate the steps you would take WITHOUT actually
calling any tools. Output a numbered plan in plain markdown.

Each step MUST include:

  1. The tool name you'd invoke (use Phantom's actual tool names —
     xlog.create_scenario_worker, caldera.create_operation,
     xsiam.run_xql_query, data_sources_installed_as_vendors, etc).
  2. The key arguments you'd pass (don't paste full schemas; just
     the operator-relevant fields like scenario name, destination,
     operation duration).
  3. One sentence explaining WHY this step is part of the plan.
  4. A risk callout if the step is destructive (writes to a real
     SOC tool, fires real synthetic logs against a real SIEM,
     starts a real CALDERA operation). Use **Risk:** prefix.

Format:

\`\`\`
## Proposed plan

1. **xlog.create_scenario_worker** — scenario "fortigate-auth-spray",
   duration 4h, destination udp:10.0.0.8:514
   *Why: produces 4h of synthetic FortiGate auth-spray events that
   the SOC can use for detection tuning.*
   **Risk:** writes ~1k events/min to the real syslog destination.
   Stop early with /tasks abort if the volume is wrong.

2. **xsiam.run_xql_query** — query "dataset = ngfw_logs |
   filter source_ip in (10.0.0.0/8) | summarize count() by user",
   tenant default
   *Why: confirms the spray events landed and lets us baseline how
   many our existing rules surfaced.*

... (etc)

## Notes

- Estimated duration: 4h 5m
- Tools that might require approval: 1 (caldera.create_operation if added)
- Recommended: review step 1's destination before approving — the
  events will hit a shared SIEM tenant.
\`\`\`

Do NOT call any tools. Do NOT emit text outside the structured plan.
Do NOT include code blocks for the plan content itself (just the
Format example shows a code block; YOUR output is the markdown
inside the example, not wrapped).`;

/**
 * Slash command registry.
 *
 * Each entry's handler receives a SlashCommandContext with everything
 * the chat handler exposes (sessionId, trigger, sendEvent, controller,
 * runtimeConfig, requestedModel/Provider). Handlers MUST close the
 * controller before returning — the framework doesn't auto-close so
 * a handler that wants to leave the stream open can do so.
 *
 * Adding a new command: append a SlashCommand here. Both the dispatch
 * (parseSlashCommand → dispatchSlashCommand inside POST) and the help
 * listing (`/help` reading SLASH_COMMANDS via renderSlashHelp) pick it
 * up automatically.
 */
const SLASH_COMMANDS: readonly SlashCommand[] = [
  // ── /compress ──────────────────────────────────────────────────
  // Operator-triggered compaction. Reads its dependencies from
  // `ctx` rather than POST-handler locals.
  {
    name: 'compress',
    description: 'Summarize prior turns into a checkpoint to free up context budget.',
    handler: async (ctx) => {
      const { sessionId, trigger, runtimeConfig, sendEvent, controller } = ctx;
      // The summary is written by the session's own model.
      const sessionModel = (await ctx.resolveSessionModel()).result;
      if (!sessionModel.ok) {
        await reportModelRejected({
          sessionId, trigger, rejection: sessionModel, surface: 'compress', sendEvent,
        });
        controller.close();
        return;
      }
      // PreCompact hook fire-site. A hook may
      // veto compaction (e.g. "audit policy: don't compact this
      // session, the full transcript is needed").
      const preCompact = await fireHookEvent(
        'PreCompact',
        {
          event: 'PreCompact',
          sessionId,
          kind: 'manual',
          messageCount: 0,
          trigger,
        },
        trigger,
      );
      if (preCompact.decision === 'deny') {
        sendEvent('text_delta', {
          text:
            preCompact.reason ??
            'Compaction blocked by a PreCompact hook.',
        });
        sendEvent('done', { session_id: sessionId });
        controller.close();
        return;
      }
      sendEvent('compaction_start', { session_id: sessionId });
      // Persist a chat_compaction_start audit
      // row so /observability/events captures the lifecycle even if
      // the SSE stream gets disconnected before compaction_end fires.
      await safeAudit('chat_compaction_start', {
        target: `session:${sessionId}`,
        metadata: { kind: 'manual', trigger: 'slash:/compress' },
        trigger,
      });
      const compactStartedAt = Date.now();
      try {
        // Fetch full prior history (up to 1000 messages — far more
        // than the 300-msg replay cap, since we WANT to compact the
        // long-tail). This is the only path that asks for >300.
        let priorMessages: CompactionInputMessage[] = [];
        try {
          const data = await callMcpServer<{
            messages?: CompactionInputMessage[];
          }>(
            `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=1000&ascending=true`,
            {
              method: 'GET',
              headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
            },
          );
          priorMessages = Array.isArray(data?.messages) ? data.messages : [];
        } catch (err) {
          console.warn(
            `chat: /compress fetch history failed for ${sessionId}:`,
            err instanceof Error ? err.message : err,
          );
        }

        // Drop the just-persisted '/compress' user message itself
        // and any earlier checkpoint messages from the input —
        // they shouldn't be summarized (the checkpoint IS the
        // prior summary, and /compress isn't conversation).
        const summarizable = priorMessages.filter((m) => {
          if (m.role === 'user' && m.content.trim() === '/compress') return false;
          if (isCompactionCheckpoint(m)) return false;
          return true;
        });

        if (summarizable.length === 0) {
          sendEvent('text_delta', {
            text: 'Nothing to compact yet — the session has no prior turns.',
          });
          sendEvent('compaction_end', {
            session_id: sessionId,
            messages_summarized: 0,
            skipped: true,
          });
          // Record the no-op as well so the operator can
          // see /compress invocations even when they didn't compact
          // anything. The skipped flag lets observability filters
          // distinguish "operator pressed it but nothing happened"
          // from "real compactions".
          await safeAudit('chat_compaction_end', {
            target: `session:${sessionId}`,
            status: 'success',
            durationMs: Date.now() - compactStartedAt,
            metadata: { skipped: true, messages_summarized: 0, kind: 'manual' },
            trigger,
          });
          sendEvent('done', {
            session_id: sessionId,
            status_reason: 'compaction_completed' satisfies RunStatusReason,
            skipped: true,
          });
          controller.close();
          return;
        }

        const compressProviderEvents = providerEventSink({
          ref: sessionModel.ref, purpose: 'summarize', sessionId, trigger, sendEvent,
        });
        const result = await compactMessages(summarizable, (instructions, transcript) =>
          summarizeViaModel(instructions, transcript, runtimeConfig, sessionModel.ref, 'summarize', compressProviderEvents, ctx.signal),
        );

        if (!result) throw new Error('summarizer returned empty');

        // Persist the checkpoint as a system-role message with
        // meta.kind=compaction-checkpoint. loadSessionHistory's
        // checkpoint-aware slicing kicks in on the next turn.
        await safePersist(
          sessionId,
          {
            role: 'system',
            content: result.summary,
            meta: {
              kind: COMPACTION_CHECKPOINT_KIND,
              covers_until: result.coversUntil,
              messages_summarized: result.messagesSummarized,
            },
          },
          trigger,
        );

        sendEvent('text_delta', {
          text:
            `**Compacted ${result.messagesSummarized} prior message(s).** ` +
            `Future turns in this session will start from this summary:\n\n` +
            result.summary +
            `\n\n*The full transcript is preserved in the session ` +
            `record and remains exportable; only the in-memory replay ` +
            `is shortened.*`,
        });
        sendEvent('compaction_end', {
          session_id: sessionId,
          messages_summarized: result.messagesSummarized,
          summary_chars: result.summary.length,
          covers_until: result.coversUntil,
        });
        // Durable audit row for the successful compaction.
        // metadata.summary_chars + messages_summarized give the
        // observability page enough to compute "tokens saved" without
        // re-fetching the checkpoint message.
        await safeAudit('chat_compaction_end', {
          target: `session:${sessionId}`,
          status: 'success',
          durationMs: Date.now() - compactStartedAt,
          metadata: {
            kind: 'manual',
            messages_summarized: result.messagesSummarized,
            summary_chars: result.summary.length,
            covers_until: result.coversUntil,
          },
          trigger,
        });
        // PostCompact hook fire-site.
        // Non-decisional (the compaction already landed). Hooks
        // typically forward summary text to an external archive or
        // emit notifications.
        void fireHookEvent(
          'PostCompact',
          {
            event: 'PostCompact',
            sessionId,
            kind: 'manual',
            messagesSummarized: result.messagesSummarized,
            summaryChars: result.summary.length,
            durationMs: Date.now() - compactStartedAt,
            trigger,
          },
          trigger,
        );
        sendEvent('done', {
          session_id: sessionId,
          status_reason: 'compaction_completed' satisfies RunStatusReason,
          messages_summarized: result.messagesSummarized,
        });
      } catch (err) {
        if (isAbortedError(err) || ctx.signal.aborted) {
          // The client closed the browser: nothing to report, no failure row.
          controller.close();
          return;
        }
        console.error(
          `chat: /compress failed for ${sessionId}:`,
          err instanceof Error ? err.message : err,
        );
        sendEvent('error', {
          error: `Compaction failed: ${err instanceof Error ? err.message : String(err)}`,
          code: 'COMPACTION_FAILED',
        });
        // Failure rows so the operator can see
        // compaction_failed cases when looking at observability.
        await safeAudit('chat_compaction_failed', {
          target: `session:${sessionId}`,
          status: 'failure',
          durationMs: Date.now() - compactStartedAt,
          metadata: {
            kind: 'manual',
            error: err instanceof Error ? err.message : String(err),
          },
          trigger,
        });
      }
      controller.close();
    },
  },

  // ── /clear ─────────────────────────────────────────────────────
  // End the current session (preserves transcript + audit history)
  // and create a fresh one. Emits `session_cleared` with the new
  // session_id so the chat UI can swap its active session pointer
  // without a full reload. On a brand-new session (operator just
  // opened the chat), it's a no-op — there's nothing to clear.
  {
    name: 'clear',
    description: 'End this session and start a fresh one. Transcript stays exportable.',
    handler: async (ctx) => {
      const { sessionId, isNewSession, trigger, sendEvent, controller } = ctx;
      if (isNewSession) {
        sendEvent('text_delta', {
          text: 'This session is brand-new — nothing to clear yet.',
        });
        sendEvent('done', { session_id: sessionId });
        controller.close();
        return;
      }

      // End the current session. Failure is non-fatal: even if the
      // end call doesn't land, the new session will still be created
      // and the operator gets the desired effect (fresh context).
      try {
        await callMcpServer(
          `/api/v1/sessions/${encodeURIComponent(sessionId)}/end`,
          {
            method: 'POST',
            body: {},
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
      } catch (err) {
        console.warn(
          `chat: /clear: end-session failed for ${sessionId}:`,
          err instanceof Error ? err.message : err,
        );
      }

      // Create a fresh session. If MCP is unreachable we synthesize
      // a local id so the UI still gets a clean slate; subsequent
      // turns will lazy-create properly when MCP recovers.
      let newSessionId: string;
      try {
        const created = await callMcpServer<{ session?: { id?: string } }>(
          '/api/v1/sessions',
          {
            method: 'POST',
            body: { user: 'operator', title: null, meta: {} },
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
        newSessionId = created?.session?.id ?? `s_${crypto.randomUUID()}`;
      } catch (err) {
        console.warn(
          'chat: /clear: failed to create replacement session:',
          err instanceof Error ? err.message : err,
        );
        newSessionId = `s_${crypto.randomUUID()}`;
      }

      sendEvent('session_cleared', {
        previous_session_id: sessionId,
        session_id: newSessionId,
      });
      sendEvent('text_delta', {
        text: `Started a fresh session. The previous transcript is still in the sidebar and exportable.`,
      });
      sendEvent('done', { session_id: newSessionId });
      controller.close();
    },
  },

  // ── /help ──────────────────────────────────────────────────────
  // List the available commands. Built from the SLASH_COMMANDS
  // table itself so it stays in sync without a separate doc.
  {
    name: 'help',
    description: 'Show this list of slash commands.',
    handler: async (ctx) => {
      const { sessionId, sendEvent, controller } = ctx;
      sendEvent('text_delta', { text: renderSlashHelp(SLASH_COMMANDS) });
      sendEvent('done', { session_id: sessionId });
      controller.close();
    },
  },

  // ── /cost ──────────────────────────────────────────────────────
  // Show token + USD cost rollups. Aggregates
  // chat_turn_cost audit rows for THIS session and today's
  // overall total. The /observability/cost page has the full
  // multi-dimensional view; this is the in-chat quick check.
  {
    name: 'cost',
    description:
      'Show token + USD cost for this session and today.',
    handler: async (ctx) => {
      const { sessionId, trigger, sendEvent, controller } = ctx;
      try {
        // Pull two windows: this session, and today (since
        // midnight UTC).
        const sessionRowsP = callMcpServer<{
          events?: Array<{ metadata?: Record<string, unknown> }>;
        }>(
          `/api/v1/audit?action=chat_turn_cost&target=session:${encodeURIComponent(sessionId)}&limit=1000`,
          {
            method: 'GET',
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
        const todayMidnight = new Date();
        todayMidnight.setUTCHours(0, 0, 0, 0);
        const todayIso = todayMidnight.toISOString();
        const todayRowsP = callMcpServer<{
          events?: Array<{ metadata?: Record<string, unknown> }>;
        }>(
          `/api/v1/audit?action=chat_turn_cost&since=${encodeURIComponent(todayIso)}&limit=1000`,
          {
            method: 'GET',
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
        const [sessionData, todayData] = await Promise.all([
          sessionRowsP,
          todayRowsP,
        ]);
        const sessionTotals = sumCostRows(auditResponseRows(sessionData));
        const todayTotals = sumCostRows(auditResponseRows(todayData));
        sendEvent('text_delta', { text: renderCostSummary(sessionTotals, todayTotals) });
        sendEvent('done', { session_id: sessionId });
      } catch (err) {
        sendEvent('error', {
          error: `Cost lookup failed: ${err instanceof Error ? err.message : String(err)}`,
          code: 'COST_LOOKUP_FAILED',
        });
      }
      controller.close();
    },
  },

  // ── /tasks ─────────────────────────────────────────────────────
  // List active and recent tasks for THIS
  // session. Operator can also visit /tasks for the full registry.
  // No args today; future args could filter by kind ("/tasks
  // scenario_worker" → only worker tasks).
  {
    name: 'tasks',
    description: 'Show active background tasks (log generators, CALDERA ops, etc).',
    handler: async (ctx) => {
      const { sessionId, trigger, sendEvent, controller } = ctx;
      try {
        const data = await callMcpServer<{ tasks?: Array<{
          id: string;
          kind: string;
          status: string;
          title: string;
          progress: number;
          progress_label: string | null;
          parent_session_id: string | null;
          created_at: string;
        }> }>(
          `/api/v1/tasks?active_only=1&limit=50`,
          {
            method: 'GET',
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
        const tasks = data.tasks ?? [];
        // Running log generators live in xlog, not in the task registry; the
        // /tasks page lists them, so the slash command does too. A failure
        // to reach xlog only drops that section.
        let generatorLines: string[] = [];
        try {
          const w = await callMcpServer<{ workers?: Array<{
            worker: string;
            type: string;
            status: string;
            count: string;
            interval: string;
            destination: string;
          }> }>(`/api/v1/workers`, {
            method: 'GET',
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          });
          generatorLines = (w.workers ?? [])
            .filter((x) => x.status.toLowerCase() === 'running')
            .map(
              (x) =>
                `  \`log generator\` **${x.type} to ${x.destination}** — ` +
                `${x.count} events every ${x.interval}s (worker ${x.worker.slice(0, 8)})`,
            );
        } catch {
          generatorLines = [];
        }
        if (tasks.length === 0 && generatorLines.length === 0) {
          sendEvent('text_delta', {
            text:
              'No active background tasks.\n\n' +
              '_Tasks appear here when long-running work is spawned ' +
              "(log generators, scenario emulation, CALDERA operations, etc). See [/tasks](/tasks) for the full list including completed and failed tasks._",
          });
        } else {
          // Render a table-style summary the operator can act on.
          // Tasks tied to THIS session bubble to the top.
          tasks.sort((a, b) => {
            const aMine = a.parent_session_id === sessionId ? 0 : 1;
            const bMine = b.parent_session_id === sessionId ? 0 : 1;
            return aMine - bMine || a.created_at.localeCompare(b.created_at);
          });
          const lines = tasks.map((t) => {
            const pct = Math.round(t.progress * 100);
            const own = t.parent_session_id === sessionId ? '★ ' : '  ';
            const label = t.progress_label
              ? ` — ${t.progress_label}`
              : '';
            return `${own}\`${t.kind}\` **${t.title}** — ${t.status} (${pct}%)${label}`;
          });
          const total = tasks.length + generatorLines.length;
          sendEvent('text_delta', {
            text:
              `**${total} active task${total === 1 ? '' : 's'}** ` +
              `(★ = spawned by this session)\n\n` +
              [...lines, ...generatorLines].join('\n') +
              `\n\nVisit [/tasks](/tasks) to see completed tasks, stop log generators or abort running tasks.`,
          });
        }
        sendEvent('done', { session_id: sessionId });
      } catch (err) {
        sendEvent('error', {
          error: `Failed to fetch tasks: ${err instanceof Error ? err.message : String(err)}`,
          code: 'TASKS_LIST_FAILED',
        });
      }
      controller.close();
    },
  },

  // ── /plan <prompt> ─────────────────────────────────────────────
  // Plan mode. The operator types
  // "/plan run a 4h FortiGate scenario emulation"; the agent
  // composes a step-by-step plan WITHOUT executing any tools.
  // The operator then sees the plan, can approve it (executes the
  // run), revise it, or cancel.
  //
  // Why: per-tool inline approval cards
  // work great for ONE tool, but a 4h workflow that fires 12 tools
  // across xlog + CALDERA + XSIAM is 12 prompt cards. Plan mode
  // collapses that to ONE: agent presents the plan, operator
  // approves once, all 12 tools execute without further prompts.
  //
  // Implementation: this handler emits a `plan_proposed` SSE event
  // with the model's plan text. The chat UI renders an inline
  // PlanCard that the operator can approve. Approval re-sends the
  // ORIGINAL prompt with a session-flag that signals "skip
  // per-tool approvals — the plan was approved." See
  // `lib/system-prompt.ts` for the planning instructions appended
  // to the system prompt.
  {
    name: 'plan',
    argHint: '<prompt>',
    description:
      'Plan a multi-step workflow without executing tools. Approve once to run the whole plan.',
    handler: async (ctx) => {
      const {
        args,
        sessionId,
        trigger,
        runtimeConfig,
        sendEvent,
        controller,
      } = ctx;
      const prompt = args.trim();
      if (!prompt) {
        sendEvent('text_delta', {
          text:
            'Usage: `/plan <prompt>` — e.g. `/plan run a 4h FortiGate auth-spray scenario and verify with XQL`. ' +
            'The agent will propose the steps it would take; you can approve to run.',
        });
        sendEvent('done', { session_id: sessionId });
        controller.close();
        return;
      }
      const sessionModel = (await ctx.resolveSessionModel()).result;
      if (!sessionModel.ok) {
        await reportModelRejected({
          sessionId, trigger, rejection: sessionModel, surface: 'plan', sendEvent,
        });
        controller.close();
        return;
      }
      sendEvent('plan_started', { session_id: sessionId, prompt });
      try {
        // The planning system prompt instructs the model to enumerate
        // its anticipated tool calls in a structured form. We use a
        // separate summarizer-style call (no tools wired) so the
        // model can't accidentally execute anything mid-plan.
        const planText = await summarizeViaModel(
          PLAN_MODE_INSTRUCTIONS,
          prompt,
          runtimeConfig,
          sessionModel.ref,
          'plan',
          providerEventSink({ ref: sessionModel.ref, purpose: 'plan', sessionId, trigger, sendEvent }),
          ctx.signal,
        );
        if (!planText) {
          throw new Error('plan generation returned empty');
        }
        // Persist the plan as a system message so it shows in the
        // chat thread + transcript. Tagged `kind: 'plan-proposed'`
        // for future filtering.
        await safePersist(
          sessionId,
          {
            role: 'system',
            content: planText,
            meta: {
              kind: 'plan-proposed',
              source_prompt: prompt,
              proposed_at: new Date().toISOString(),
            },
          },
          trigger,
        );
        sendEvent('plan_proposed', {
          session_id: sessionId,
          plan_text: planText,
          source_prompt: prompt,
        });
        sendEvent('text_delta', { text: planText });
        sendEvent('text_delta', {
          text:
            '\n\n---\n\n' +
            '**To execute this plan**: send the original prompt without `/plan` ' +
            '(e.g. `' +
            (prompt.length > 60 ? prompt.slice(0, 60) + '…' : prompt) +
            '`). ' +
            "I'll run the steps; tier-2+ tools may still surface individual approval cards.\n\n" +
            '**To revise**: tell me what to change ("plan again but skip step 3").\n\n' +
            '**To cancel**: just send a different prompt; the plan goes away.',
        });
        // Audit: durable record of the plan for /observability
        // queries. Stored separately from the persisted system
        // message so operators don't need to reconstruct from
        // transcripts.
        await safeAudit('chat_plan_proposed', {
          target: `session:${sessionId}`,
          status: 'success',
          metadata: {
            source_prompt: prompt,
            plan_chars: planText.length,
            model: sessionModel.canonical,
            provider: sessionModel.ref.provider,
            model_ref: sessionModel.canonical,
          },
          trigger,
        });
        sendEvent('done', { session_id: sessionId });
      } catch (err) {
        if (isAbortedError(err) || ctx.signal.aborted) {
          controller.close();
          return;
        }
        console.error(
          `chat: /plan failed for ${sessionId}:`,
          err instanceof Error ? err.message : err,
        );
        sendEvent('error', {
          error: `Plan generation failed: ${err instanceof Error ? err.message : String(err)}`,
          code: 'PLAN_FAILED',
        });
        await safeAudit('chat_plan_failed', {
          target: `session:${sessionId}`,
          status: 'failure',
          metadata: {
            source_prompt: prompt,
            error: err instanceof Error ? err.message : String(err),
          },
          trigger,
        });
      }
      controller.close();
    },
  },

  // ── /model <name> ──────────────────────────────────────────────
  // Persist a per-session preferred model. Persists into
  // session.metadata.preferred_model via PATCH; the chat handler
  // reads it on subsequent turns via loadSessionPreferredModel.
  //   /model            → report the session's model, preference, install default
  //   /model auto       → clear the preference
  //   /model <name>     → check <name> against the registry, store its
  //                       canonical ref (e.g. vertex/gemini-3.7-flash)
  // A name the registry does not accept is refused with suggestions and
  // nothing is stored.
  {
    name: 'model',
    argHint: '<name>',
    description: 'Override the model for this session. `/model auto` clears.',
    handler: async (ctx) => {
      const { args, sessionId, trigger, sendEvent, controller } = ctx;
      const state = await ctx.resolveSessionModel();
      const command = interpretModelCommand(args, state.entries);

      if (command.kind === 'show') {
        sendEvent('text_delta', {
          text: renderModelStatus(
            { session: state.session, installDefault: state.installDefault, header: ctx.requestedModel },
            state.entries,
          ),
        });
        sendEvent('done', { session_id: sessionId });
        controller.close();
        return;
      }

      if (command.kind === 'reject') {
        sendEvent('text_delta', { text: command.message });
        void safeAudit('chat_model_rejected', {
          target: `session:${sessionId}`,
          status: 'failure',
          metadata: {
            requested: args.trim().slice(0, 200),
            source: 'session',
            reason: 'MODEL_COMMAND_REFUSED',
            suggestions: command.suggestions,
            surface: 'model_command',
          },
          trigger,
        });
        sendEvent('done', { session_id: sessionId });
        controller.close();
        return;
      }

      const newValue = command.kind === 'clear' ? null : command.canonical;
      try {
        await callMcpServer(
          `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
          {
            method: 'PATCH',
            body: { metadata: { preferred_model: newValue } },
            headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
          },
        );
        invalidateSessionPreferredModelCache(sessionId);
        sendEvent('model_preference_changed', {
          session_id: sessionId,
          preferred_model: newValue,
        });
        const installDefault = describeInstallDefault(state.installDefault, state.entries);
        sendEvent('text_delta', {
          text: command.kind === 'clear'
            ? `Cleared model override. Future turns will use the install default (${
                installDefault.ref ? `\`${installDefault.ref}\`` : 'currently unavailable'
              }).`
            : `Set model preference to \`${command.canonical}\` for this session. Takes effect on the next turn.`,
        });
        sendEvent('done', { session_id: sessionId });
      } catch (err) {
        console.error(
          `chat: /model failed for ${sessionId}:`,
          err instanceof Error ? err.message : err,
        );
        sendEvent('error', {
          error: `Failed to update model preference: ${err instanceof Error ? err.message : String(err)}`,
          code: 'MODEL_PREFERENCE_FAILED',
        });
      }
      controller.close();
    },
  },
];

// Turn-scoped tool-result memoization.
//
// The system prompt asks the model to "call data_sources_list at most once
// per turn", but the model can still re-list the catalog (and re-run
// knowledge_search) several times within a single user turn. A prose nudge
// can't *guarantee* the model
// obeys, so this is the mechanical backstop — a per-turn cache that returns the
// already-fetched result for an identical (tool, args) call instead of
// re-dispatching to the MCP.
//
// Scope: ONE user message (the cache is declared inside the POST handler, NOT
// module-level — it must never leak a catalog snapshot across turns or users).
//
// Semantics: REPEATABLE-READ within a turn. The allowlist below is static
// platform metadata whose value cannot change mid-turn *except* via an explicit
// catalog/config mutation — and `invalidatesTurnCache()` clears the snapshot the
// moment such a mutation runs, so a same-turn install→re-list still sees fresh
// data. Different args ⇒ different key ⇒ both calls dispatch (e.g. schema for
// source A then source B), so no capability is lost — only verbatim repeats are
// short-circuited.
const TURN_CACHEABLE_TOOLS = new Set<string>([
  'data_sources_list',
  'data_sources_get_schema',
  'data_sources_installed_as_vendors',
  'marketplace_list',
  'log_destinations_list',
  'settings_get',
  'skills_read',
  'knowledge_search',
  'phantom_get_field_info',
]);

// Catalog / config / credential mutations change what the cacheable reads
// return, so they invalidate the whole turn snapshot. The explicit names
// cover every agent-reachable mutation that touches the static-read surface
// above (a false positive would only cost a cache clear). The agent has no
// provider, instance or API-key write tools, so none are listed. Every name
// here must be a registered tool; tests/test_shipped_tool_references.py checks.
function invalidatesTurnCache(toolName: string): boolean {
  return /^(marketplace_(install|uninstall)|connector_upload|data_sources_(install|uninstall|edit|rollback)|log_destinations_create|settings_(update|reset)|skills_(create|update|delete))$/.test(
    toolName,
  );
}

// Deterministic JSON for cache keys: object keys sorted so {a,b} and {b,a} hash
// identically; arrays keep order; primitives pass through. Avoids treating two
// semantically-identical arg objects as distinct calls.
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value) ?? 'null';
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  return `{${Object.keys(obj)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`)
    .join(',')}}`;
}

// Detect the {ok:false} failure envelope Phantom MCP tools
// return on a SOFT failure (not an exception). data_sources_install and many
// others report "not found" / "already exists" / "extraction failed" this way,
// so a model that retries the identical failing call loops invisibly past the
// toolError path (observed: data_sources_install ×7 on a not-found pack). Only
// the explicit "ok": false envelope counts — never a tool whose output merely
// contains the word "error" — to avoid false-positive loop-breaking.
function resultFailureText(result: unknown): string | null {
  try {
    const content = (result as { content?: Array<{ text?: unknown }> })?.content;
    if (!Array.isArray(content)) return null;
    for (const part of content) {
      const text = typeof part?.text === 'string' ? part.text : '';
      if (!text || !/"ok"\s*:\s*false/.test(text)) continue;
      const m = text.match(/"error"\s*:\s*"((?:[^"\\]|\\.)*)"/);
      return (m ? m[1] : text).slice(0, 280);
    }
  } catch {
    /* non-JSON / unexpected shape — treat as non-failure */
  }
  return null;
}

// Poll/wait tools legitimately re-issue the SAME (tool, args) call many times
// (e.g. caldera_wait_for_operation_progress) and may transiently report a
// not-yet-ready state — they must never be short-circuited by the failed-call
// loop-breaker below.
function isPollTool(toolName: string): boolean {
  return /_wait|wait_for|_poll/i.test(toolName);
}

export async function POST(request: NextRequest) {
  const encoder = new TextEncoder();

  // Trigger attribution — set by upstream callers (today: the
  // job_scheduler when it fires a chat-action job; future: per-
  // operator session attribution). Forwarded to every downstream
  // MCP call so audit rows tag with the same trigger.
  //
  // This also drives the approvals bus's `origin` column
  // (so chat-origin approvals can resolve via inline card; job
  // and other origins land in /approvals). For interactive chat
  // turns, we default to "chat:<sessionId>" right after sessionId
  // is resolved below — that way the operator typing in the UI
  // also gets a stable origin in audit + approvals tables.
  let trigger = request.headers.get('x-phantom-trigger') || undefined;

  // One signal for the whole turn, fired when the client goes away: by the
  // request's own signal or by the response stream being cancelled (see
  // lib/turn-abort.ts). Every model call below takes `turnSignal`, and an abort
  // ends the turn quietly.
  const turnAbort = createTurnAbort(request.signal);
  const turnSignal = turnAbort.signal;

  const stream = new ReadableStream({
    cancel() {
      turnAbort.cancel();
    },
    async start(controller) {
      // SSE wire format aligned with Spark's parseSSEEvent (lib/api/chat.ts):
      // each frame is a named event with a JSON-encoded `data:` line.
      // Spark's parser returns null if the `event:` line is absent, so a
      // bare "data: {type, ...}" frame would be silently dropped by the
      // chat UI. Send named events here; the hook reads `event.type` to
      // switch.
      let eventCounter = 0;
      const sendEvent = (type: string, dataObj: unknown) => {
        eventCounter += 1;
        const dataLine = `data: ${typeof dataObj === 'string' ? dataObj : JSON.stringify(dataObj)}`;
        controller.enqueue(
          encoder.encode(`id: ${eventCounter}\nevent: ${type}\n${dataLine}\n\n`),
        );
      };

      try {
        const {
          message,
          session_id: incomingSessionId,
          model: requestedModel,
          provider: requestedProvider,
          permission_policy: requestedPolicy,
          thinking: requestedThinking,
        } = (await request.json()) as {
          message?: string;
          session_id?: string;
          model?: string;
          provider?: string;
          // Per-request permission policy. The
          // scheduler attaches this on job-driven dispatches; chat
          // header has no UI for it today (operators set it on the
          // job; chat turns are unrestricted by default).
          permission_policy?: unknown;
          // Extended thinking. The scheduler attaches `thinking: true`
          // when the job's thinking_enabled is set; the route threads
          // it into the model request's `thinking` flag.
          thinking?: unknown;
        };
        // Normalize the policy through the validator. Bad shapes
        // degrade to `null` (no policy) rather than throw — the
        // validator's lenient mode matches the rest of the route's
        // best-effort discipline.
        const turnPolicy = validatePermissionPolicy(requestedPolicy);
        // Thinking is ON by default: an unset field means enabled, and
        // only an explicit `thinking: false` from the caller disables
        // it. The scheduler sends `thinking: true` for jobs that turn
        // the toggle on and omits the field otherwise, so an
        // unset field also gets the default.
        //
        // Effect (Gemini): the request carries generationConfig.thinkingConfig
        // with thinkingBudget = -1 ("use what you need") + includeThoughts
        // = true. Models with thinking support engage their
        // extended-reasoning path with an auto budget; models without
        // it ignore the setting. The marginal cost is the output-side
        // reasoning tokens, since the prompt prefix is served from the
        // Vertex context cache when it is enabled.
        const turnThinking = requestedThinking !== false;

        if (!message) {
          sendEvent('error', { error: 'Message is required' });
          controller.close();
          return;
        }

        // Resolve the session id: if the client supplied one, reuse it
        // (subsequent turns of an existing chat). Otherwise lazy-create
        // a session in the MCP store so the chat shows up in the
        // sidebar / sessions list and is exportable.
        //
        // The session-store call is best-effort: if MCP is unreachable
        // we still synthesize a local id so the stream completes and
        // the user sees a response — they just won't get persistence
        // for that turn (and a warning is logged server-side).
        let sessionId: string;
        let isNewSession = false;
        if (incomingSessionId) {
          sessionId = incomingSessionId;
        } else {
          try {
            const created = await callMcpServer<{
              session?: { id?: string };
            }>('/api/v1/sessions', {
              method: 'POST',
              body: { user: 'operator', title: null, meta: {} },
              headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
            });
            const id = created?.session?.id;
            if (id) {
              sessionId = id;
              isNewSession = true;
            } else {
              sessionId = `s_${crypto.randomUUID()}`;
            }
          } catch (err) {
            console.warn(
              'chat: failed to create session in MCP store, using local id:',
              err instanceof Error ? err.message : err,
            );
            sessionId = `s_${crypto.randomUUID()}`;
          }
        }

        // Default trigger to chat:<sessionId> for interactive
        // chats. Job-triggered chats already have trigger set by the
        // upstream scheduler ("job:<name>"); we only fill in the chat
        // origin if no upstream trigger was provided.
        if (!trigger) {
          trigger = `chat:${sessionId}`;
        }

        const turnStartedAt = Date.now();
        sendEvent('meta', {
          run_id: `r_${crypto.randomUUID()}`,
          session_id: sessionId,
          agent_id: 'phantom-soc-simulation',
        });

        // RunStart hook fire-site. Hooks can
        // abort the entire turn (`decision: 'deny'`) before the
        // user message is persisted, keeping the audit trail clean.
        // Common use: "block all chat in tenant-X during a freeze
        // window."
        const runStartHook = await fireHookEvent(
          'RunStart',
          { event: 'RunStart', sessionId, trigger },
          trigger,
        );
        if (runStartHook.decision === 'deny') {
          sendEvent('error', {
            error:
              runStartHook.reason ??
              'Chat turn blocked by a RunStart hook.',
            code: 'HOOK_DENIED_RUN_START',
          });
          controller.close();
          return;
        }

        // UserPromptSubmit hook fire-site. Hooks
        // can inject context (e.g. "the active incident is INC-1234"),
        // replace the message (rare; mostly redaction), or deny.
        // Fires BEFORE persistence so a denied prompt isn't
        // permanently archived.
        const userPromptHook = await fireHookEvent(
          'UserPromptSubmit',
          { event: 'UserPromptSubmit', sessionId, message, trigger },
          trigger,
        );
        if (userPromptHook.decision === 'deny') {
          sendEvent('error', {
            error:
              userPromptHook.reason ??
              'Prompt blocked by a UserPromptSubmit hook.',
            code: 'HOOK_DENIED_PROMPT',
          });
          controller.close();
          return;
        }
        // If a hook returned `replace`, swap it in. Useful for
        // redaction: "scrub UUIDs before sending to the model."
        const effectiveMessage =
          typeof userPromptHook.replace === 'string'
            ? userPromptHook.replace
            : message;

        // Persist the user's inbound message before we start the model
        // loop. Doing it here (vs after the turn) means a partial /
        // crashed turn still leaves a record of what was asked.
        // We persist the EFFECTIVE message (post-hook-replace) so
        // the transcript matches what the model sees.
        await safePersist(sessionId, { role: 'user', content: effectiveMessage }, trigger);

        // Stash hook-injected context for the model loop to append
        // to the system instruction on this turn. Empty string when
        // no hooks contributed.
        const hookInjectedContext = userPromptHook.injectContext ?? '';

        // ── Slash command dispatch ────────────
        //
        // Framework-routed table lookup. Adding a new command is one
        // entry in SLASH_COMMANDS (above this function) — no plumbing
        // here. Handlers own their own controller lifetime; the
        // framework only catches uncaught errors and emits a fallback
        // `error` event so a crashed handler can't leave the UI
        // hanging.
        //
        // Slash commands always short-circuit the normal chat-turn
        // path: there's no "/compress AND keep chatting" — the
        // command IS the turn.
        const parsed = parseSlashCommand(message);
        if (parsed) {
          const runtimeConfig = await getEffectiveRuntimeConfig();
          await dispatchSlashCommand(parsed, SLASH_COMMANDS, {
            args: parsed.args,
            sessionId,
            isNewSession,
            trigger,
            runtimeConfig,
            requestedModel,
            requestedProvider,
            resolveSessionModel: () =>
              resolveSessionModel({
                sessionId,
                isNewSession,
                trigger,
                requestedModel,
                requestedProvider,
                runtimeConfig,
              }),
            signal: turnSignal,
            sendEvent,
            controller,
          });
          return;
        }

        const logDebug = (_stage: string, _detail: string) => {
          // Debug events were a phantom-specific concept (the old chat
          // page rendered them in a "Live telemetry" sidecar). Spark's
          // chat UI has its own thinking-section component; suppress
          // these for now rather than emit them as malformed Spark events.
        };

        const runtimeConfig = await getEffectiveRuntimeConfig();

        // Read the operator's `chat_subagents_enabled`
        // preference for this turn. Defaults to true. When false:
        //   - SUBAGENT_CREATE_TOOL_SPEC is omitted from the catalog
        //     the model sees, so it shouldn't even try to spawn.
        //   - As defense in depth, the dispatcher intercepts any
        //     `subagent_create` call (in case the model somehow still
        //     issues it from training) and synthesizes a denied
        //     response explaining the policy.
        const subagentsEnabled = await readSubagentsEnabled();

        // Resolve approval bypass for this turn. Two sources:
        //   (a) the inbound request already carries
        //       `X-Phantom-Approval-Bypass` (a job dispatch from the
        //       scheduler with bypass_approvals=true), OR
        //   (b) session.metadata.approval_mode === 'bypass' (the chat
        //       UI dropdown set it).
        // Either source activates bypass for this turn. Stored on every
        // downstream MCP call so the trigger_context middleware on the
        // MCP side flips the contextvar gate_and_execute reads.
        const bypassFromInbound =
          (request.headers.get('x-phantom-approval-bypass') || '')
            .trim()
            .toLowerCase() === '1' ||
          (request.headers.get('x-phantom-approval-bypass') || '')
            .trim()
            .toLowerCase() === 'true';
        const sessionApprovalMode = isNewSession
          ? 'manual'
          : await loadSessionApprovalMode(sessionId, trigger);
        const approvalBypass = bypassFromInbound || sessionApprovalMode === 'bypass';
        // Derive the narration mode passed to the system
        // prompt. Mirrors `approvalBypass` exactly so the agent's
        // promised UX (card vs. immediate-execute) matches what the
        // MCP-side gate will actually do this turn. Without it, an
        // agent in bypass mode would tell the operator "Pending your
        // approval — the card should appear below" while the
        // destructive calls had already executed.
        const approvalMode: ApprovalMode = approvalBypass ? 'bypass' : 'manual';

        logDebug('mcp', `Connecting to MCP at ${runtimeConfig.MCP_URL}`);
        // Compose the extraHeaders dict so the MCP client attaches it
        // to every tool dispatch. Reserved-name precedence inside
        // PhantomMCPClient.headers() ensures Content-Type / Authorization
        // / mcp-* aren't accidentally clobbered if extras collide.
        const mcpExtraHeaders: Record<string, string> = {};
        if (trigger) mcpExtraHeaders['X-Phantom-Trigger'] = trigger;
        if (approvalBypass) mcpExtraHeaders['X-Phantom-Approval-Bypass'] = '1';
        const mcpClient = new PhantomMCPClient(
          runtimeConfig.MCP_URL,
          runtimeConfig.MCP_TOKEN,
          // Forward X-Phantom-Trigger + (when active)
          // X-Phantom-Approval-Bypass to every MCP tool dispatch so
          // audit rows for tools called during this chat inherit the
          // trigger tag AND so the MCP-side gate_and_execute reads the
          // bypass contextvar. The MCP's trigger_context middleware
          // sets both contextvars.
          Object.keys(mcpExtraHeaders).length > 0 ? mcpExtraHeaders : undefined,
        );
        if (approvalBypass) {
          // Surface the bypass status to the UI as a meta-event so the
          // chat UI can render the "Bypass ON" badge for this turn.
          // Idempotent — UI tracks the per-turn flag and updates the
          // badge accordingly.
          sendEvent('approval_mode', { mode: 'bypass' });
        }
        // Resolve the model for this turn before anything is fetched for it.
        // Priority chain:
        //   1. Header / request body (`model`, optionally qualified by
        //      `provider`) — the operator or the job picked this model.
        //   2. Session preference (set via /model <name> on a prior
        //      turn, persisted in session.metadata.preferred_model).
        //   3. The install default (settings key `defaultModel`).
        //   4. The derived default: the recommended model of the first
        //      configured provider (vertex, anthropic, openai).
        //
        // The session pref is only read when no header model was sent, so the
        // header always wins, and not on brand-new sessions (nothing to read
        // yet; the round-trip matters on the cold-start path). A model that was
        // named at 1-3 and cannot serve ENDS the turn with MODEL_UNAVAILABLE:
        // there is no fallback to another model, so a retired or unconfigured
        // model is never silently swapped for one the operator did not choose.
        const sessionModelPref: string | undefined =
          requestedModel || isNewSession
            ? undefined
            : await loadSessionPreferredModel(sessionId, trigger);
        const { result: turnModel } = await resolveModelForRequest(
          { header: requestedModel, headerProvider: requestedProvider, session: sessionModelPref },
          runtimeConfig,
        );
        if (!turnModel.ok) {
          await reportModelRejected({
            sessionId, trigger, rejection: turnModel, surface: 'chat', sendEvent,
          });
          controller.close();
          return;
        }
        const modelRef = turnModel.ref;
        // Adapter observations (a downgraded tool choice, a dropped tool call, a
        // refusal) for this turn's model calls and for auto-compaction's summary.
        const turnProviderEvents = providerEventSink({
          ref: modelRef, purpose: 'chat', sessionId, trigger, sendEvent,
        });
        const compactionProviderEvents = providerEventSink({
          ref: modelRef, purpose: 'summarize', sessionId, trigger, sendEvent,
        });
        // header / session picks displace the install default; `override` and
        // the ref handed to subagents keep that meaning.
        const effectiveRequestedModel: string | undefined =
          turnModel.source === 'header' || turnModel.source === 'session'
            ? turnModel.canonical
            : undefined;
        // `none` is the install default serving, as it always was; `derived`
        // means no usable default was set and the first configured provider's
        // recommended model serves.
        const overrideSource: 'header' | 'session' | 'none' | 'derived' =
          turnModel.source === 'default' ? 'none' : turnModel.source;

        const tools = await getTurnTools(
          mcpClient,
          runtimeConfig,
          logDebug,
          subagentsEnabled,
        );

        // Build conversation context from prior persisted
        // messages so Gemini sees the running thread, not just the
        // latest user turn. For brand-new sessions or fetch failures,
        // history is empty and we fall back to single-turn behavior.
        // The user's CURRENT message was already persisted (line above
        // via safePersist) — so the load typically returns it as the
        // last entry. Two defensive cases below:
        //  1. New sessions: skip the history load (the persist may not
        //     have committed yet for our just-created session).
        //  2. The persist may have failed silently (safePersist swallows
        //     errors), in which case history won't have the current
        //     message — we manually append.
        // Pass the resolved model so the history walk knows the
        // input-token budget. turnModel already collapses header,
        // session preference, install default and derived default.
        const historyModelName = turnModel.canonical;
        const history = isNewSession
          ? []
          : await loadSessionHistory(sessionId, trigger, historyModelName, {
              // Auto-compaction hooks. If history would
              // exceed the model's input budget, summarize the
              // dropped portion via Gemini, persist as a checkpoint
              // for amortization, and surface activity to live
              // telemetry.
              summarize: (instructions, transcript) =>
                summarizeViaModel(instructions, transcript, runtimeConfig, modelRef, 'summarize', compactionProviderEvents, turnSignal),
              persistCheckpoint: async (
                summary,
                coversUntil,
                messagesSummarized,
              ) => {
                await safePersist(
                  sessionId,
                  {
                    role: 'system',
                    content: summary,
                    meta: {
                      kind: COMPACTION_CHECKPOINT_KIND,
                      covers_until: coversUntil,
                      messages_summarized: messagesSummarized,
                      // Tag distinguishes auto-compaction from
                      // operator-triggered /compress in the audit log.
                      trigger: 'auto',
                    },
                  },
                  trigger,
                );
              },
              onCompactionEvent: (kind, stats) => {
                // Mirror /compress's SSE events; the live-telemetry
                // panel surfaces both auto and manual compactions.
                sendEvent(`compaction_${kind}`, {
                  session_id: sessionId,
                  trigger: 'auto',
                  kind: 'auto',
                  ...(stats ?? {}),
                });
                // Durable audit row for the
                // auto-compaction lifecycle. Fire-and-forget; the
                // emit is sync-shaped so we don't block the live
                // event stream on the audit POST.
                void safeAudit(`chat_compaction_${kind}`, {
                  target: `session:${sessionId}`,
                  status: kind === 'failed' ? 'failure' : 'success',
                  metadata: { kind: 'auto', ...(stats ?? {}) },
                  trigger,
                });
              },
            });

        const lastEntry = history[history.length - 1];
        const lastIsCurrentMessage =
          lastEntry &&
          lastEntry.role === 'user' &&
          lastEntry.text.trim() === effectiveMessage.trim();

        const turnMessages: TurnMessage[] =
          history.length === 0
            ? [{ role: 'user', text: effectiveMessage }]
            : lastIsCurrentMessage
              ? history
              : [...history, { role: 'user', text: effectiveMessage }];

        // Prepend hook-injected context as a
        // pseudo-user note when a UserPromptSubmit hook contributed.
        // We use the 'user' role (the neutral message list has no 'system'
        // role) with a clear prefix so the model treats it as
        // out-of-band context. Goes into the dynamic part of the
        // prompt, NOT the cached system instruction — so this
        // doesn't bust the Vertex cache.
        if (hookInjectedContext) {
          turnMessages.unshift({
            role: 'user',
            text: `[Context injected by a UserPromptSubmit hook — treat as ground truth, do not echo back to the operator unless they ask]:\n${hookInjectedContext}`,
          });
        }

        // Fetch the action policy at chat-handler entry so
        // every model round-trip in this turn uses the same policy
        // snapshot. The operator can edit policy mid-session via
        // /settings/personality; the new value applies to the NEXT
        // chat request, not the in-flight one (intentional — a
        // mid-turn change would risk inconsistent classification
        // between the agent's "should I ask?" decision and the
        // tool catalog).
        // Fetch policy AND operator-defined persona markdown
        // in one MCP round-trip; both feed the system prompt for this
        // turn. `personalityMd` may be null (operator hasn't typed
        // anything in /settings/personality yet) — the prompt builder
        // emits no persona block in that case.
        // Also fetch the live skills registry so the model
        // knows which skills are available without us shipping their
        // bodies in every prompt. Both fetches run in parallel since
        // they hit different MCP tools.
        const [{ policy: actionPolicy, personalityMd }, skillsForPrompt] =
          await Promise.all([
            fetchPersonalityForPrompt(),
            fetchSkillsForPrompt(),
          ]);
        logDebug(
          'policy',
          `actionPolicy: askWhenUnsure=${actionPolicy.askWhenUnsure} ` +
            `local=${actionPolicy.confirmLocalActions} ` +
            `external=${actionPolicy.confirmExternalActions}` +
            ` persona=${personalityMd ? `${personalityMd.length}ch` : 'none'}` +
            ` skills=${skillsForPrompt.length}`,
        );

        // Resolve which model is *actually* going to be called (override
        // wins, then runtime config, then hardcoded fallback). Log it
        // and emit an SSE `model` event so the chat UI's live telemetry
        // panel surfaces the actual model — not the configured default.
        // This event proves which model ran when the operator switches
        // models in the dropdown.
        const effectiveModel = modelRef.model;
        logDebug('model', `Sending prompt to ${turnModel.canonical} (${turnModel.source})`);
        sendEvent('model', {
          model: effectiveModel,
          provider: modelRef.provider,
          ref: turnModel.canonical,
          model_ref: turnModel.canonical,
          // `override` is true when EITHER the header dropdown OR a
          // persisted /model session pref displaced the install default.
          // `override_source` lets the UI distinguish without changing
          // the boolean's existing meaning: header, session, none (the
          // install default serves) or derived (no usable default is set).
          override: Boolean(effectiveRequestedModel),
          override_source: overrideSource,
        });

        // ── Context-window guard ─────────────────────
        //
        // Estimate total request token cost (input + reserved output)
        // and compare to the model's context cap. Fail fast with a
        // structured error if we'd overflow; warn via debug event if
        // we're near the edge so the operator can act before the next
        // turn (start a new session, run compaction, etc).
        //
        // The estimates are conservative — see lib/tokens.ts notes —
        // so the >99% threshold is unlikely to over-block. Real
        // overflows still get caught at the provider; this is just
        // earlier, with a clearer error.
        const ctxCap = resolveContextCap(effectiveModel);
        // The system prompt and the tool catalog are built ONCE per turn and
        // reused by every model call in it (retries and follow-ups included),
        // so the estimate below measures exactly what is sent. Some providers
        // bind earlier thinking blocks to the system prompt and tools that
        // preceded them, so they must not change mid-turn. approvalMode is
        // part of the prompt: the bypass block is the longer variant, so a
        // mode-blind estimate would under-count by ~50 tokens in bypass
        // sessions. What the install gates is read from the manifest: the
        // prompt names those tools (or says none are gated) instead of
        // promising a card for every mutation. Undefined = manifest unreadable.
        const approvalGating = await getApprovalGating();
        const systemText = buildSystemPromptText(
          actionPolicy,
          personalityMd,
          skillsForPrompt,
          approvalMode,
          approvalGating.known ? approvalGating.gated : undefined,
          turnModel.canonical,
        );
        const systemTokens = estimateTokens(systemText);
        const modelCapabilities = capabilitiesFor(modelRef);
        const turnCreds = credsFromRuntimeConfig(runtimeConfig);
        const callTurnModel: LoopCall = (messages, options) =>
          callModel(
            {
              ref: modelRef,
              system: systemText,
              messages,
              tools,
              toolChoice: options.toolChoice,
              thinking: options.thinking,
              purpose: options.toolChoice === 'none' ? 'budget_summary' : 'chat',
              // Providers that route prompt-cache lookups by key hash it; the
              // session id itself never leaves the install.
              cacheKey: sessionId,
            },
            { creds: turnCreds, step: options.step, onEvent: turnProviderEvents, signal: turnSignal },
            modelDispatchDeps(),
          );
        const toolsTokens = estimateTokens(estimateToolsJson(modelRef, tools));
        const contentsTokens = turnMessages.reduce(
          (acc, msg) =>
            acc +
            estimateMessageTokens(
              msg.role === 'user' || msg.role === 'assistant' ? msg.text : '',
            ),
          0,
        );
        // There is no `maxOutputTokens` cap below, so the
        // model can output up to its natural ceiling (~65,536 for
        // gemini-3.1-pro-preview). We reserve THAT much room in the
        // input-side context budget so the model never gets squeezed
        // by an oversize prompt that leaves no room to respond. This
        // is INPUT-side accounting (how much we trim the prompt to
        // fit), NOT an output cap. Gemini still writes as much as the
        // response naturally needs. Shared with the history
        // budget walk's computeInputBudget() default via one export
        // (lib/model-context-caps.ts), so the two cannot drift.
        const reservedOutput = DEFAULT_RESERVED_OUTPUT_TOKENS;
        const totalRequired =
          systemTokens + toolsTokens + contentsTokens + reservedOutput;
        const utilization = totalRequired / ctxCap;

        if (utilization >= 0.99) {
          // Hard block — Vertex would error out anyway, this gives a
          // structured signal the chat UI can surface.
          sendEvent('error', {
            error:
              `Context window full: estimated ${totalRequired.toLocaleString()} ` +
              `tokens vs cap ${ctxCap.toLocaleString()} (${(utilization * 100).toFixed(1)}%). ` +
              `Start a new chat or wait for compaction to land.`,
            code: 'CONTEXT_NEAR_FULL',
            tokens_estimated: totalRequired,
            tokens_cap: ctxCap,
            tokens_breakdown: {
              system: systemTokens,
              tools: toolsTokens,
              contents: contentsTokens,
              output_reserve: reservedOutput,
            },
          });
          controller.close();
          return;
        }
        if (utilization >= 0.90) {
          // Soft warn — emit a debug event so the live-telemetry
          // panel can surface it without blocking the turn.
          logDebug(
            'context',
            `near-cap: ${(utilization * 100).toFixed(1)}% ` +
              `(${totalRequired.toLocaleString()} / ${ctxCap.toLocaleString()})`,
          );
          sendEvent('context_warning', {
            tokens_estimated: totalRequired,
            tokens_cap: ctxCap,
            utilization,
          });
          // Durable audit row. The
          // observability page can grep for action:chat_context_warning
          // to see "which sessions are crowding their context window."
          // Fire-and-forget so the audit POST doesn't add latency to
          // the in-flight turn.
          void safeAudit('chat_context_warning', {
            target: `session:${sessionId}`,
            metadata: {
              tokens_estimated: totalRequired,
              tokens_cap: ctxCap,
              utilization: Number(utilization.toFixed(4)),
              model: effectiveModel,
              provider: modelRef.provider,
              model_ref: turnModel.canonical,
            },
            trigger,
          });
        }

        const initialTurn = await callTurnModel(turnMessages, {
          step: 0,
          thinking: turnThinking,
          toolChoice: 'auto',
        });
        logDebug('model', 'Received initial response');

        // Record cost for the initial model
        // call. Subsequent tool-result follow-ups (the loop below) record
        // their own rows. We accumulate the total in
        // `turnTally` and emit a single turn_cost SSE event
        // at done time so the chat UI can show "this turn cost $X"
        // without having to sum events.
        const turnTally = newTurnTally();
        {
          const c = extractAndRecordCost(initialTurn, {
            sessionId,
            ref: modelRef,
            trigger,
            callKind: 'initial',
          });
          if (c) addCallToTally(turnTally, c);
        }

        // Surface cache hits to live telemetry. Any provider that
        // reports cache-read tokens on a response (Gemini cached
        // content, Claude cache reads, OpenAI cached tokens) lands here;
        // zero / absent means the prompt was billed in full. Operators
        // see this in the live-telemetry panel as proof the optimization
        // is engaged.
        const cachedTokens = initialTurn.usage?.cacheRead ?? 0;
        if (cachedTokens > 0 && initialTurn.usage) {
          const promptTokens = initialTurn.usage.inputTotal;
          // What the hit saved comes from the model's own registry price
          // (null when the model is unpriced), not a fixed factor.
          const saved = cacheReadSavings({
            usage: initialTurn.usage,
            provider: modelRef.provider,
            model: modelRef.model,
          });
          sendEvent('cache_hit', {
            cached_tokens: cachedTokens,
            prompt_tokens: promptTokens,
            // The prompt token count includes cached + uncached input;
            // subtract to surface what we actually paid full-price
            // for this turn.
            full_price_input_tokens: promptTokens - cachedTokens,
            savings_usd_est: saved?.usd ?? null,
            model: effectiveModel,
            provider: modelRef.provider,
            model_ref: turnModel.canonical,
          });
          // Durable cache-hit audit row so operators can chart prompt
          // caching ROI over time, per provider. `savings_tokens_est` is
          // the cached tokens' worth of full-price input that the
          // cache-read discount saved (null for an unpriced model).
          void safeAudit('chat_cache_hit', {
            target: `session:${sessionId}`,
            metadata: {
              cached_tokens: cachedTokens,
              prompt_tokens: promptTokens,
              full_price_input_tokens: promptTokens - cachedTokens,
              savings_tokens_est: saved?.tokensEquivalent ?? null,
              savings_usd_est: saved?.usd ?? null,
              model: effectiveModel,
              provider: modelRef.provider,
              model_ref: turnModel.canonical,
            },
            trigger,
          });
        }

        let finalText: string[] = [];
        let toolCalls: Array<{ tool: string; args: Record<string, unknown>; result: string; error?: string }> = [];

        // Per-turn xdr_run_xql_query consecutive-failure counter.
        // The skill prompt says "max 3 iterations" but that's advisory,
        // and a model under pressure can thrash through many retries.
        // The cap is binding: after 3
        // consecutive FAIL responses from xdr_run_xql_query (resets on
        // any SUCCESS), the route injects a synthetic STOP directive
        // into the next functionResponse. The LLM sees "you've hit the
        // 3-iteration cap; stop retrying + summarize what you learned"
        // and breaks out of the thrash loop.
        let xdrConsecutiveFailures = 0;
        const XDR_FAIL_CAP = 3;

        // Turn-scoped memo for idempotent reads. Declared
        // OUTSIDE the step loop so a catalog/schema/knowledge result fetched in
        // an early agent step is reused by later steps in THIS user message
        // instead of re-dispatching to the MCP. Per-message scope (never
        // module-level) so no snapshot leaks across turns or operators. See
        // TURN_CACHEABLE_TOOLS / invalidatesTurnCache above the POST handler.
        const turnToolCache = new Map<string, unknown>();

        // Per-message failure ledger: identical (tool, args)
        // call key -> { count, error }. After MAX_IDENTICAL_FAILS failures of the
        // SAME call this turn, further identical dispatches are short-circuited
        // with a "change approach" payload, breaking deterministic retry loops.
        const turnFailedCalls = new Map<string, { count: number; error: string }>();
        const MAX_IDENTICAL_FAILS = 2;

        // Default 30 turns, configurable via env. A 20-step Caldera
        // kill-chain at ~2 tool calls per turn (poll + XDR pulse) needs
        // ~15-20 turns for the wait phase alone, plus 5-10 turns for
        // prereqs + setup + final sweep. The
        // caldera_wait_for_operation_progress tool internalizes the
        // 30-60s wait per ability, so each turn advances the chain by
        // 1-2 abilities (vs a noop poll). 30 turns covers a 20-step
        // Caldera chain with room to spare. Operators can tune via env
        // var.
        const MAX_AGENT_TURNS = (() => {
          const raw = process.env.PHANTOM_CHAT_MAX_TURNS;
          if (!raw) return 30;
          const n = parseInt(raw, 10);
          return Number.isFinite(n) && n >= 5 && n <= 200 ? n : 30;
        })();

        // Present one model turn to the operator: thinking goes out as its own
        // event, and the turn's text goes out as answer text unless it is pure
        // read-tool narration.
        const presentTurn = async (turn: AssistantTurn): Promise<void> => {
            // Suppress read-tool narration in the chat stream.
            // Models habitually emit "I'll call `log_destinations_list`." as
            // response text right before a tool call. Every call + its result
            // is already in the live telemetry, so that prose only duplicates
            // what the operator already sees. Pre-scan this turn's tool calls:
            // if the turn makes calls and ALL of them are non-gated (read /
            // auto-approved), drop the accompanying text parts — they're pure
            // narration. Gated calls keep their text (the why-line for the
            // approval card); plain-answer turns (no calls) keep their text.
            // Deterministic: does NOT depend on the model obeying a
            // "don't narrate" system-prompt rule (which it ignores — a
            // prompt carve-out alone does not suppress this).
          let suppressReadNarration = false;
          if (turn.toolCalls.length > 0) {
            const gatedFlags = await Promise.all(
              turn.toolCalls.map((c) => isToolGated(c.name).catch(() => false)),
            );
            suppressReadNarration = gatedFlags.every((g) => g === false);
          }
          for (const text of turn.thinking) {
            // Reasoning is streamed as `thinking` so the UI's ThinkingSection
            // renders it collapsed above the answer. It is excluded from
            // finalText, so the saved .content stays the clean answer-only transcript.
            sendEvent('thinking', { text });
          }
          if (suppressReadNarration) return; // dropped: the call is already in the live telemetry
          for (const text of turn.text) {
            finalText.push(text);
            // Spark's hook switches on `event.type === 'text_delta'`.
            sendEvent('text_delta', { text });
          }
        };

        // Run one turn's tool calls and return their results in call order.
        // The loop (lib/providers/turn-loop.ts) has already added the turn to
        // the message list and will check that every call got a result.
        const executeToolCalls = async (turn: AssistantTurn): Promise<ToolResultItem[]> => {
          const functionCalls = turn.toolCalls;
          const responseItems: ToolResultItem[] = [];

          // Server-side fallback preamble.
          //
          // The system prompt instructs the model to narrate every
          // gated tool call ("I'll do X with these args, approval
          // below") but Gemini doesn't always comply — sometimes it
          // emits a function call with zero accompanying text. When
          // that happens, the operator sees the approval card pop
          // out of nowhere and has to expand "Raw arguments" to
          // figure out what's about to happen. That defeats the
          // entire point of the approval gate.
          //
          // Defense-in-depth: if the model produced no text in this
          // turn, synthesize a one-line preamble per planned tool
          // call and stream it BEFORE the dispatch loop kicks off.
          // The approval_pending event still carries the structured
          // args (improved card UI uses them too), but this puts
          // human-readable context in the chat thread first.
          //
          // We only synthesize when finalText is empty — if the
          // model DID narrate, we don't add a duplicate preamble.
          if (finalText.length === 0) {
            for (const call of functionCalls) {
              // Only synthesize a preamble for GATED calls
              // (the approval card needs the human context). Non-gated
              // reads stay silent — no preamble — matching the read-tool
              // narration filter above. Without this, a read-only turn
              // whose narration we just suppressed would fall through to
              // here (finalText empty) and get a synthesized preamble,
              // re-introducing exactly the narration we removed.
              const gatedCall = await isToolGated(call.name).catch(() => false);
              if (!gatedCall) continue;
              const preamble = formatToolPreamble(call.name, call.args || {});
              if (preamble) {
                sendEvent('text_delta', { text: preamble + '\n\n' });
              }
            }
          }

          for (const call of functionCalls) {
            const toolName = call.name;
            let toolArgs = call.args || {};
            const toolStartedAt = Date.now();
            logDebug('tool', `Calling ${toolName}`);
            const toolCallId = `tc_${crypto.randomUUID()}`;

            // Permission policy enforcement.
            // Evaluate per-turn policy (set by the job dispatcher via
            // body.permission_policy) before the tool fires. A `deny`
            // short-circuits to a synthetic tool-error response the
            // model sees as a failed call; anything else goes on to
            // the manifest-driven approval gate. Audit every deny so
            // the operator can reconstruct why a job's tools were
            // blocked.
            const policyEval = evaluatePermissionPolicy(toolName, turnPolicy);
            if (policyEval.decision === 'deny') {
              const reason =
                policyEval.reason ?? 'Denied by job permission policy';
              sendEvent('tool_call', {
                tool_call_id: toolCallId,
                tool: toolName,
                args: toolArgs,
                status: 'denied_by_policy',
                reason,
              });
              responseItems.push({
                kind: 'result',
                callId: call.id,
                name: toolName,
                payload: {
                  error: reason,
                  denied_by_policy: true,
                  matched_list: policyEval.matchedList,
                  matched_pattern: policyEval.matchedPattern,
                },
              });
              toolCalls.push({
                tool: toolName,
                args: toolArgs,
                result: '',
                error: reason,
              });
              // Best-effort audit row (don't block on failure).
              void callMcpServer('/api/v1/audit', {
                method: 'POST',
                body: {
                  action: 'tool_denied_by_policy',
                  target: `tool:${toolName}`,
                  status: 'denied',
                  metadata: {
                    session_id: sessionId,
                    tool_name: toolName,
                    matched_list: policyEval.matchedList,
                    matched_pattern: policyEval.matchedPattern,
                  },
                },
              }).catch(() => {});
              continue; // skip the normal dispatch path
            }

            // subagent_create interception.
            // The model invokes this synthetic tool to spawn a
            // scoped subagent. Bypass the standard MCP dispatch +
            // approval-poll path and route to runSubagent. The
            // result is fed back to the model as a regular
            // tool_result so the parent's reasoning loop continues
            // normally.
            if (toolName === SUBAGENT_CREATE_TOOL) {
              // Defense-in-depth gate. If the operator has
              // disabled subagents, the model SHOULDN'T see this
              // tool in its catalog. But if it tries anyway (cached
              // catalog from prior turn, or model hallucinated the
              // tool), synthesize a clean denied response instead
              // of running a sidechain.
              if (!subagentsEnabled) {
                const deniedMsg =
                  'Subagent spawning is disabled by operator preference ' +
                  '(chat_subagents_enabled=false). Re-enable in the chat ' +
                  'header toggle to use subagent_create.';
                sendEvent('tool_call', {
                  id: toolCallId,
                  name: toolName,
                  arguments: toolArgs,
                  status: 'pending',
                });
                sendEvent('tool_result', {
                  tool_call_id: toolCallId,
                  name: toolName,
                  status: 'error',
                  error: deniedMsg,
                });
                responseItems.push({
                  kind: 'result',
                  callId: call.id,
                  name: toolName,
                  payload: { error: deniedMsg, denied_by: 'operator_preference' },
                });
                continue;
              }
              const agentName = String(
                (toolArgs as Record<string, unknown>)['agent_name'] ?? '',
              ).trim();
              const subPrompt = String(
                (toolArgs as Record<string, unknown>)['prompt'] ?? '',
              ).trim();
              if (!agentName || !subPrompt) {
                const errMsg =
                  'subagent_create requires both `agent_name` and `prompt`.';
                sendEvent('tool_call', {
                  id: toolCallId,
                  name: toolName,
                  arguments: toolArgs,
                  status: 'pending',
                });
                sendEvent('tool_result', {
                  tool_call_id: toolCallId,
                  name: toolName,
                  status: 'error',
                  error: errMsg,
                });
                responseItems.push({
                  kind: 'result',
                  callId: call.id,
                  name: toolName,
                  payload: { error: errMsg },
                });
                continue;
              }
              sendEvent('tool_call', {
                id: toolCallId,
                name: toolName,
                arguments: toolArgs,
                status: 'pending',
                metadata: resolveToolMetadata(toolName),
              });
              const subResult = await runSubagent({
                agentName,
                prompt: subPrompt,
                parentSessionId: sessionId,
                parentMessage: message,
                trigger,
                parentTools: tools,
                runtimeConfig,
                parentModel: turnModel.canonical,
                mcpClient,
                sendEvent,
                signal: turnSignal,
              });
              const resultText = JSON.stringify({
                status: subResult.status,
                final_response: subResult.final_response,
                turns_used: subResult.turns_used,
                tool_calls_count: subResult.tool_calls_count,
                tools_called: subResult.tool_calls_made.map((t) => t.tool),
                subagent_session_id: subResult.subagent_session_id,
                duration_ms: subResult.duration_ms,
                error: subResult.error,
              });
              sendEvent('tool_result', {
                tool_call_id: toolCallId,
                name: toolName,
                status: subResult.status === 'completed' ? 'success' : 'error',
                result: resultText,
              });
              toolCalls.push({
                tool: toolName,
                args: toolArgs as Record<string, unknown>,
                result: resultText,
                error: subResult.error,
              });
              responseItems.push({
                kind: 'result',
                callId: call.id,
                name: toolName,
                payload: { result: resultText },
              });
              continue;
            }

            // PreToolUse hook fire-site. Hooks
            // can deny the call (block on policy), ask (force the
            // approval card even for soft-tier tools), or replace
            // the args (e.g. inject a tenant scope before xsiam
            // calls hit the wrong tenant). Fires BEFORE the
            // approval-card poll loop so a hook deny short-circuits
            // the whole gating flow.
            const preToolHook = await fireHookEvent(
              'PreToolUse',
              {
                event: 'PreToolUse',
                sessionId,
                toolName,
                args: toolArgs as Record<string, unknown>,
                trigger,
              },
              trigger,
            );
            if (preToolHook.decision === 'deny') {
              // Synthesize a tool result the model will see as a
              // failure, with the hook's reason as the error. The
              // model can then explain to the operator what was
              // blocked and why.
              const hookReason =
                preToolHook.reason ?? 'Tool call blocked by a PreToolUse hook.';
              sendEvent('tool_call', {
                id: toolCallId,
                name: toolName,
                arguments: toolArgs,
                status: 'pending',
              });
              sendEvent('tool_result', {
                tool_call_id: toolCallId,
                name: toolName,
                status: 'error',
                error: hookReason,
              });
              toolCalls.push({
                tool: toolName,
                args: toolArgs as Record<string, unknown>,
                result: '',
                error: hookReason,
              });
              responseItems.push({
                kind: 'result',
                callId: call.id,
                name: toolName,
                payload: {
                  error: hookReason,
                  blocked_by: 'pre_tool_use_hook',
                },
              });
              continue;
            }
            // If a hook returned `replace`, swap in the new args.
            // The model sees the original; the tool runs with the
            // hook-modified version. Useful for "scope every xsiam
            // call to the active incident's tenant_id".
            if (
              preToolHook.replace &&
              typeof preToolHook.replace === 'object'
            ) {
              toolArgs = preToolHook.replace as typeof toolArgs;
            }

            // Resolve tool metadata once per
            // call. The chat UI uses metadata.destructive/openWorld
            // to color the approval card border; metadata.readOnly
            // is informational; metadata.concurrencySafe is the
            // gating contract for future parallel batch execution
            // (deferred to a follow-up — see allConcurrencySafe
            // export). The metadata is denormalized onto every
            // tool_call event so the UI doesn't need a parallel
            // table lookup.
            const toolMetadata: ToolMetadata = resolveToolMetadata(toolName);

            sendEvent('tool_call', {
              id: toolCallId,
              name: toolName,
              arguments: toolArgs,
              status: 'pending',
              // Tool metadata — UI reads `destructive` (red
              // border), `openWorld` (amber border), `readOnly`
              // (no border + relaxed approval policy). `concurrencySafe` is hint-only for now.
              metadata: toolMetadata,
            });

            // Agent self-modification UX. If the tool is
            // listed in manifest.approvals.humanRequired[], the MCP-
            // side gate creates a pending row and blocks on
            // bus.wait_async until the operator resolves. Without
            // intervention the chat stream just hangs for up to 5
            // minutes while the agent appears stuck.
            //
            // Race the tool call against a poll loop that watches
            // /api/v1/approvals?status=pending. When a new row appears
            // (one whose id wasn't present before we made the call),
            // emit an `approval_pending` SSE event so the UI can
            // render an inline approval card while the call still
            // blocks on bus.wait_async. After the operator clicks
            // Approve in the card, the bus resolution unblocks the
            // tool call, the result flows through normally, and the
            // tool_result event finishes the cycle.
            const gated = await isToolGated(toolName).catch(() => false);
            let approvalPollAbort: AbortController | null = null;
            if (gated) {
              approvalPollAbort = new AbortController();
              // Snapshot existing pending IDs so we can detect just
              // the NEW row created by this tool call. Scope to chat:<sessionId> so concurrent job-fired
              // approvals don't enter the snapshot diff.
              const before = await fetchPendingApprovalIds(sessionId).catch(
                () => new Set<string>(),
              );
              // Don't await — fire-and-forget poll loop. It self-
              // terminates either when it finds the new row or when
              // the AbortController fires (post-resolution).
              void pollForNewApproval({
                signal: approvalPollAbort.signal,
                snapshot: before,
                toolName,
                sessionId,
                onFound: (row) => {
                  sendEvent('approval_pending', {
                    tool_call_id: toolCallId,
                    approval_id: row.id,
                    tool: toolName,
                    args: toolArgs,
                    risk_tier: row.risk_tier ?? classifyRiskTier(toolName),
                    created_at: row.created_at,
                  });
                },
              });
            }

            let result;
            let toolError: Error | null = null;
            let servedFromCache = false; // telemetry-badge a turn-cache hit
            // Turn-cache short-circuit. For an idempotent
            // read whose identical (tool, args) result was already fetched this
            // user message, reuse it instead of re-dispatching to the MCP. Only
            // the network dispatch is skipped — truncation + the tool_result
            // event below still run so the model sees the result for THIS step.
            const turnCallKey = `${toolName} ${stableStringify(toolArgs)}`;
            const turnCacheKey = TURN_CACHEABLE_TOOLS.has(toolName)
              ? turnCallKey
              : null;
            const priorFails = turnFailedCalls.get(turnCallKey)?.count ?? 0;
            if (turnCacheKey && turnToolCache.has(turnCacheKey)) {
              // Cast to callTool's own return type so `result` keeps the same
              // shape it has on the live-dispatch path (the cache is typed
              // `unknown` to stay tool-agnostic).
              result = turnToolCache.get(turnCacheKey) as Awaited<
                ReturnType<typeof mcpClient.callTool>
              >;
              servedFromCache = true;
              approvalPollAbort?.abort();
              logDebug(
                'mcp',
                `turn-cache hit: ${toolName} — reused this-turn result, skipped redundant MCP dispatch`,
              );
            } else if (!isPollTool(toolName) && priorFails >= MAX_IDENTICAL_FAILS) {
              // This exact (tool, args) call already failed
              // MAX_IDENTICAL_FAILS times this turn. Stop re-dispatching and
              // hand the model a synthetic {ok:false} payload telling it to
              // change approach. Breaks deterministic retry loops (install x7)
              // without touching poll/wait tools or distinct-argument retries.
              approvalPollAbort?.abort();
              const prior = turnFailedCalls.get(turnCallKey)?.error ?? 'previous attempt failed';
              result = {
                content: [
                  {
                    type: 'text',
                    text: JSON.stringify({
                      ok: false,
                      error: prior,
                      note: `This identical call (same tool + arguments) has already failed ${priorFails} times this turn. Do NOT retry it; use different arguments, a different tool, or stop and report the blocker to the operator.`,
                    }),
                  },
                ],
              } as Awaited<ReturnType<typeof mcpClient.callTool>>;
              logDebug(
                'mcp',
                `turn-fail short-circuit: ${toolName} failed ${priorFails}x this turn, not re-dispatching`,
              );
            } else {
              try {
                result = await mcpClient.callTool(toolName, toolArgs);
              } catch (err) {
                toolError = err instanceof Error ? err : new Error(String(err));
              } finally {
                // Stop polling regardless of how the call ended (success,
                // tool error, approval denial). Cleanup is idempotent.
                approvalPollAbort?.abort();
              }
              // Record failures (exception OR {ok:false} envelope)
              // so the next identical call increments toward the short-circuit.
              const failText = toolError
                ? (toolError.message || 'tool error').slice(0, 280)
                : resultFailureText(result);
              if (failText) {
                turnFailedCalls.set(turnCallKey, { count: priorFails + 1, error: failText });
              }
              // Cache only genuine successes - never an {ok:false} result.
              if (turnCacheKey && !toolError && result && !resultFailureText(result)) {
                turnToolCache.set(turnCacheKey, result);
              }
              // A catalog/config mutation invalidates the static-read snapshot
              // so a same-turn re-read sees fresh state, not the pre-mutation one.
              if (!toolError && invalidatesTurnCache(toolName)) {
                turnToolCache.clear();
              }
            }

            // Evidence truncation. The MCP tool
            // result is { content: [{type, text}, ...] }. We truncate
            // each text content entry that exceeds maxBytes — head +
            // marker + tail. Structured non-text content passes
            // through. Audit every truncation so operators see where
            // it fired.
            if (
              result &&
              typeof result === 'object' &&
              'content' in result &&
              Array.isArray((result as { content?: unknown[] }).content) &&
              !toolError
            ) {
              const truncationPolicy = truncationPolicyFromEnv();
              const contentArr = (result as { content: Array<Record<string, unknown>> }).content;
              for (let i = 0; i < contentArr.length; i++) {
                const part = contentArr[i];
                if (typeof part?.text !== 'string') continue;
                const truncation = applyTruncation(toolName, part.text, truncationPolicy);
                if (truncation.truncated) {
                  contentArr[i] = { ...part, text: truncation.output };
                  void callMcpServer('/api/v1/audit', {
                    method: 'POST',
                    body: {
                      action: 'tool_output_truncated',
                      target: `tool:${toolName}`,
                      status: 'success',
                      metadata: {
                        session_id: sessionId,
                        tool_name: toolName,
                        bytes_dropped: truncation.bytesDropped,
                        bytes_kept: truncation.bytesKept,
                        head_kept: truncation.headKept,
                        tail_kept: truncation.tailKept,
                        max_bytes: truncationPolicy.maxBytes,
                        content_index: i,
                      },
                    },
                  }).catch(() => {});
                }
              }
            }

            if (toolError || !result) {
              // PostToolUseFailure hook fire-site.
              // Non-decisional. Hooks may forward the failure to an
              // external incident channel ("xsiam tool errored on
              // session X").
              void fireHookEvent(
                'PostToolUseFailure',
                {
                  event: 'PostToolUseFailure',
                  sessionId,
                  toolName,
                  args: toolArgs as Record<string, unknown>,
                  error:
                    toolError?.message ?? 'tool returned no result',
                  durationMs: Date.now() - toolStartedAt,
                  trigger,
                },
                trigger,
              );
              const errMsg =
                toolError?.message ?? 'tool returned no result';

              // Record the failure in the
              // connector state machine. We classify auth errors
              // by message-string heuristic (401, 403, "auth",
              // "expired", "invalid token") because the MCP-side
              // tool wrapper today doesn't expose a structured
              // error type. The connector id is the first segment
              // of the tool name (`<connector>.<tool>`); legacy
              // flat aliases get split on `_`.
              const isAuthError = /\b(401|403|unauth|forbidden|invalid (token|api key|credentials|auth)|expired|reauth|needs.?auth)\b/i.test(
                errMsg,
              );
              // Use the helper: an inline split('_', 1)[0] would give
              // wrong connector_ids for connectors whose function
              // prefix differs from their id (xdr_*, phantom_*,
              // phantom_web_*, cortex_*).
              const connectorId = deriveConnectorId(toolName);
              if (connectorId) {
                void recordConnectorFailure(connectorId, {
                  error: errMsg,
                  isAuthError,
                  trigger,
                });
                if (isAuthError) {
                  // Surface to chat UI so operator sees a needs-
                  // auth chip on /connectors without having to
                  // open the page.
                  sendEvent('connector_auth_required', {
                    connector_id: connectorId,
                    tool_name: toolName,
                    session_id: sessionId,
                  });
                }
              }

              sendEvent('tool_result', {
                tool_call_id: toolCallId,
                name: toolName,
                status: 'error',
                error: errMsg,
              });
              toolCalls.push({
                tool: toolName,
                args: toolArgs as Record<string, unknown>,
                result: '',
                error: errMsg,
              });
              responseItems.push({
                kind: 'result',
                callId: call.id,
                name: toolName,
                payload: { error: errMsg },
              });
              continue;
            }

            let resultText =
              result.content[0]?.text || JSON.stringify(result.content);
            logDebug('tool', `Result from ${toolName} (${resultText.length} chars)`);

            // PostToolUse hook fire-site. Hook
            // may replace the result (scrub sensitive output before
            // the model sees it) or no-op. We await this one because
            // a `replace` has to land before the result event fires.
            const postToolHook = await fireHookEvent(
              'PostToolUse',
              {
                event: 'PostToolUse',
                sessionId,
                toolName,
                args: toolArgs as Record<string, unknown>,
                result: resultText,
                durationMs: Date.now() - toolStartedAt,
                trigger,
              },
              trigger,
            );
            if (typeof postToolHook.replace === 'string') {
              resultText = postToolHook.replace;
            }

            sendEvent('tool_result', {
              tool_call_id: toolCallId,
              name: toolName,
              status: 'success',
              result: resultText,
              cached: servedFromCache,
            });

            // Record success in connector state.
            // A successful call after a failure transitions the
            // connector back to `connected`; subsequent successes
            // are O(1) updates.
            // Use the helper: an inline split('_', 1)[0] would give
            // wrong connector_ids for hyphenated-id connectors.
            const successConnectorId = deriveConnectorId(toolName);
            if (successConnectorId) {
              void recordConnectorSuccess(successConnectorId, trigger);
            }

            toolCalls.push({
              tool: toolName,
              args: toolArgs as Record<string, unknown>,
              result: resultText,
            });

            responseItems.push({
              kind: 'result',
              callId: call.id,
              name: toolName,
              payload: { result: resultText },
            });

            // Track consecutive xdr_run_xql_query failures
            // for the 3-iteration cap. The result is JSON-shaped per
            // the cortex-xdr connector contract; parse leniently +
            // count anything that isn't a clear SUCCESS as a failure.
            if (toolName === 'xdr_run_xql_query') {
              let isFailure = false;
              try {
                const parsed = JSON.parse(resultText);
                // FAIL response shapes (from connector.py:run_xql_query):
                //   {ok: false, error: "..."}            transport error
                //   {status: "FAIL"|"FAILED", ...}       XDR rejected the query
                //   {status: "CANCELLED"|"TIMEOUT", ...} not a query bug, but counts
                // SUCCESS shape:
                //   {status: "SUCCESS", results: [...], total_rows: N}
                if (parsed?.ok === false) {
                  isFailure = true;
                } else if (
                  parsed?.status &&
                  parsed.status !== 'SUCCESS' &&
                  parsed.status !== 'PENDING'
                ) {
                  isFailure = true;
                }
              } catch {
                // Non-JSON result — treat as opaque, don't count.
              }
              if (isFailure) {
                xdrConsecutiveFailures += 1;
              } else {
                xdrConsecutiveFailures = 0;
              }
              // After hitting the cap, inject a synthetic system-style
              // message telling the LLM to STOP retrying. The injection
              // happens on the SAME response-parts batch so the LLM
              // sees it together with the most recent tool result and
              // can fold it into its next decision. The counter is
              // reset to 0 here so a single STOP fires per breach.
              if (xdrConsecutiveFailures >= XDR_FAIL_CAP) {
                responseItems.push({
                  kind: 'directive',
                  text: (
                    `You have run xdr_run_xql_query ${XDR_FAIL_CAP} ` +
                    `times in a row without a SUCCESS response. The ` +
                    `build_xql_query skill's iteration loop caps at ` +
                    `${XDR_FAIL_CAP} iterations for exactly this case ` +
                    `— more retries won't converge; the underlying ` +
                    `issue needs operator clarification, not more ` +
                    `synthesis. STOP retrying xdr_run_xql_query right ` +
                    `now. Summarize for the operator: (a) the user's ` +
                    `original question, (b) the synthesized query ` +
                    `text you last tried, (c) the specific error ` +
                    `message from XDR, (d) one or two concrete ` +
                    `clarifying questions you'd need answered to make ` +
                    `progress (e.g. "which tenant dataset has this ` +
                    `field?", "what's the canonical name for X in ` +
                    `your environment?"). Do NOT call ` +
                    `xdr_run_xql_query again in this turn.`
                  ),
                });
                xdrConsecutiveFailures = 0; // one STOP per breach
              }
            }
          }
          return responseItems;
        };

        const loop = await runModelLoop({
          initial: initialTurn,
          messages: turnMessages,
          maxTurns: MAX_AGENT_TURNS,
          turnThinking,
          capabilities: modelCapabilities,
          nextCallStep: 1, // the initial call used step 0
          call: callTurnModel,
          presentTurn,
          hasFinalText: () => finalText.length > 0,
          executeToolCalls,
          onFollowup: (turn) => {
            // Record cost for the follow-up.
            const c = extractAndRecordCost(turn, {
              sessionId,
              ref: modelRef,
              trigger,
              callKind: 'followup',
            });
            if (c) addCallToTally(turnTally, c);
          },
          note: (message) => logDebug('model', message),
          warn: (message) => console.warn(`chat: ${message}`),
        });
        // The last turn the model returned. When the loop ran out of turns it
        // was never processed; the drain below recovers its text.
        const lastTurn = loop.lastTurn;
        const exhaustedBudget = loop.exhaustedBudget;

        // Drain the last unprocessed response on
        // budget exhaustion.
        //
        // The tool loop processes a turn's text + tool calls at the TOP of
        // each iteration. When it dispatches tools in iteration N, it calls
        // the model at the BOTTOM — and the response from THAT call is what
        // iteration N+1 would normally
        // process. If iteration N is the last allowed iteration
        // (step = MAX_AGENT_TURNS - 1), N+1 never runs, and the
        // response is silently dropped.
        //
        // That response often contains the operator's actual deliverable:
        // the final answer the model wrote AFTER seeing the last batch of
        // tool results, such as a closing summary or cross-reference
        // table. Dropping it would leave the operator with the run
        // narrative but not the final answer.
        //
        // The subagent loop handles this case the same way. The chat
        // route mirrors it, with the additional responsibility of
        // streaming text_delta events so the recovered text appears in
        // the live UI (the subagent doesn't stream).
        //
        // Function calls in this final response are intentionally
        // dropped — we can't dispatch them without bumping the cap,
        // and the deliverable text is what matters most. If the final
        // response also lacks text, the budget-summary fallback below
        // handles the "still nothing to show" case.
        if (exhaustedBudget) {
          let recoveredChars = 0;
          for (const text of lastTurn.text) {
            finalText.push(text);
            sendEvent('text_delta', { text });
            recoveredChars += text.length;
          }
          if (recoveredChars > 0) {
            logDebug(
              'model',
              `Recovered ${recoveredChars} chars of post-budget text ` +
                `from final unprocessed response`,
            );
          }
        }

        let finalResponse = finalText.join('\n').trim();

        // Tool-budget exhaustion summary. If the loop ran
        // for 20 turns without producing any text, fire one more
        // no-tools call asking the model to summarize what it found.
        // Gives the operator partial value instead of a dead-end.
        // Pattern ported from blackhat-noc Slack bot's "Budget exhausted"
        // fallback. Only fires when both conditions hold:
        //   - exhaustedBudget (loop hit the 20-turn cap)
        //   - finalResponse is empty (model produced zero text across
        //     all turns; if it produced anything, respect that)
        if (exhaustedBudget && !finalResponse) {
          logDebug(
            'model',
            `Tool budget exhausted (${toolCalls.length} tool calls, 0 text); ` +
              `firing summary fallback`,
          );
          try {
            // Tool choice 'none': the model can't call more even if it
            // wants to. Belt-and-suspenders against a model that
            // ignores the prompt instruction. (Gemini renders that as an
            // empty tool list.)
            const summary = await requestBudgetSummary({
              messages: turnMessages,
              call: callTurnModel,
              step: loop.nextCallStep,
            });
            for (const text of summary.text) {
              finalText.push(text);
              sendEvent('text_delta', { text });
            }
            finalResponse = finalText.join('\n').trim();
            // Cost record for the summary call (separate from the
            // turn's main accounting).
            const c = extractAndRecordCost(summary, {
              sessionId,
              ref: modelRef,
              trigger,
              callKind: 'budget_summary',
            });
            if (c) addCallToTally(turnTally, c);
          } catch (err) {
            logDebug(
              'model',
              `Tool-budget summary fallback failed: ${
                err instanceof Error ? err.message : String(err)
              }`,
            );
            // Falls through to synthesizeFallbackText below.
          }
        }

        if (!finalResponse || !finalResponse.trim()) {
          // Also catch a WHITESPACE-ONLY finalResponse, not
          // just a strictly-empty one. A turn that ran read tools (e.g. export-
          // yaml: data_sources_list + get_schema) but came back with " " was
          // truthy, slipped past `!finalResponse`, and rendered as a blank
          // assistant message. `.trim()` routes it into the recap below.
          //
          // Gemini sometimes returns turns that are 100% function calls
          // and 0% text, especially after approval-gated tool round-
          // trips: the model emits the tool call, the gate blocks for
          // human approval, and the post-approval response can be a
          // bare functionCall with no narration. Across the whole loop
          // that leaves finalText empty.
          //
          // The old fallback ("No model response was returned. Review
          // the tool results above…") was technically accurate but
          // unhelpful — operators couldn't tell whether anything
          // actually ran or what to do next. Build a context-aware
          // recap instead, then PERSIST it so a session reload doesn't
          // show a blank assistant turn.
          //
          // We pull the finish reason off the last turn to
          // distinguish "model just chose silence" (stop) from
          // truncation (max_tokens) from safety blocks (safety,
          // recitation) — the last two warrant different operator advice.
          finalResponse = synthesizeFallbackText(toolCalls, lastTurn.finish);
          sendEvent('text_delta', { text: finalResponse });
        }

        // Persist tool round-trips first, then the assistant's final
        // text. Order matches the on-screen render order so an export
        // reads top-to-bottom like the chat. Each call is best-effort
        // and isolated, so one failure doesn't drop the rest.
        for (const tc of toolCalls) {
          await safePersist(sessionId, {
            role: 'tool',
            content: tc.result,
            tool_call_id: tc.tool,
            meta: { tool: tc.tool, args: tc.args },
          }, trigger);
        }
        // Always persist an assistant row when there was anything to
        // show — including the synthesized fallback above. This means
        // on session reload, "No model response" sessions now render
        // the recap instead of going blank.
        if (finalResponse) {
          await safePersist(sessionId, {
            role: 'assistant',
            content: finalResponse,
            // Tag the persisted assistant message with which model
            // produced it. The MCP audit row written for this append
            // inherits the meta, so /observability/events shows
            // `chat_append` rows with the model name attached —
            // operator can grep `action:chat_append` and see which
            // models were used per turn.
            meta: {
              model: effectiveModel,
              model_override: Boolean(effectiveRequestedModel),
              model_override_source: overrideSource,
              provider: modelRef.provider,
              model_ref: turnModel.canonical,
            },
          }, trigger);
        }

        // Auto-title brand-new sessions from the first user message.
        // 60 chars matches the column width Spark uses in the sidebar.
        //
        // For job-driven runs (trigger=`job:<name>`), also tag
        // `meta.scheduled_by=<name>`. The chat sidebar filters those
        // sessions out so a scheduled run doesn't pollute the human
        // conversation list — chat sessions stay reserved for
        // operator decisions, job runs surface only on /jobs/[id].
        if (isNewSession) {
          const trimmed = message.trim();
          const preview =
            trimmed.length > 60 ? `${trimmed.slice(0, 60).trimEnd()}…` : trimmed;
          // Extract the job name from `job:<name>` trigger headers; we
          // want metadata regardless of whether there's a preview.
          const jobMatch = trigger?.match(/^job:(.+)$/);
          const scheduledBy = jobMatch ? jobMatch[1] : null;
          // Skip the call only if we'd send neither a title nor metadata.
          if (preview || scheduledBy) {
            try {
              await callMcpServer(
                `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
                {
                  method: 'PATCH',
                  body: {
                    ...(preview ? { title: preview } : {}),
                    ...(scheduledBy
                      ? { metadata: { scheduled_by: scheduledBy } }
                      : {}),
                  },
                  headers: trigger ? { 'X-Phantom-Trigger': trigger } : undefined,
                },
              );
            } catch (err) {
              console.warn(
                `chat: failed to auto-title session ${sessionId}:`,
                err instanceof Error ? err.message : err,
              );
            }
          }
        }

        // Emit a turn_cost SSE event so the
        // chat UI can render "this turn cost $X.XX" inline. The
        // per-call audit rows already landed; this is just the
        // turn-level summary.
        // `cost_usd` is null when no call of the turn had a price, and
        // `priced` is false when any call did not, so a partial figure is
        // never read as the whole bill.
        sendEvent('turn_cost', {
          session_id: sessionId,
          ...turnCostSummary(turnTally),
          model: effectiveModel,
          provider: modelRef.provider,
          model_ref: turnModel.canonical,
        });

        // RunEnd hook fire-site. Non-decisional;
        // fires after the final response has been composed and
        // persisted but before the stream closes. Hooks typically
        // emit external notifications ("turn N completed in this
        // session, X tool calls").
        void fireHookEvent(
          'RunEnd',
          {
            event: 'RunEnd',
            sessionId,
            finalResponseChars: finalResponse.length,
            toolCallCount: toolCalls.length,
            durationMs: Date.now() - turnStartedAt,
            trigger,
          },
          trigger,
        );

        // Surface the run status reason on
        // done. Determined by inspecting how the tool loop exited:
        //   - normal completion (model emitted final text)
        //   - max_turns_exceeded (loop hit the 20-step cap)
        //   - max_output_truncation (final response was synthesized
        //     because Gemini truncated; chat-route's fallback
        //     narration kicked in)
        // The current chat-route doesn't expose the loop's actual
        // exit cause, so we conservatively classify by the final
        // response shape: empty/synthesized = max_output_truncation,
        // present = completed.
        const runStatusReason: RunStatusReason = !finalResponse
          ? 'max_output_truncation'
          : 'completed';

        sendEvent('done', {
          response: finalResponse,
          toolCalls,
          status_reason: runStatusReason,
          duration_ms: Date.now() - turnStartedAt,
        });
      } catch (error) {
        if (isAbortedError(error) || turnSignal.aborted) {
          // The client closed the browser and the model call was cancelled.
          // Not a failure: no error event (nobody is listening), no failure
          // audit row. The stream still closes in `finally`.
          console.info('Chat turn cancelled: the client disconnected.');
          return;
        }
        console.error('Chat API error:', error);
        // Spark's hook reads error event.data as a plain string into the
        // assistant bubble, so emit a string here (not a JSON object).
        // Defensive: a slash-command handler that
        // already closed the controller would make this enqueue throw
        // ("Invalid state: Controller is already closed"), and that
        // throw would propagate out of the start() callback, tearing
        // down the response BEFORE any queued events flushed to the
        // wire. Swallow it — the close already happened; this error
        // event is best-effort.
        try {
          sendEvent(
            'error',
            error instanceof Error ? error.message : 'Unknown error',
          );
        } catch {
          // already closed by a slash-command handler — fine.
        }
      } finally {
        // Slash-command handlers own their own
        // close (they may want to leave the stream open across awaits;
        // some emit a long sequence of events and close at the end).
        // A second close on the post-dispatch return path throws
        // "Invalid state: Controller is already closed", and that
        // synchronous throw would discard any events that were
        // enqueued-but-not-yet-flushed. Swallow it.
        try {
          controller.close();
        } catch {
          // already closed by a handler — events already enqueued
          // before that close are still delivered.
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
