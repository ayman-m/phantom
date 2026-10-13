/**
 * The provider-neutral tool loop behind one chat turn.
 *
 * The chat route owns everything that touches the outside world: streaming
 * events to the operator, gating, hooks, running tools, recording cost. This
 * module owns only the control flow around the model, so it can be exercised
 * with a fake adapter:
 *
 *   present the turn -> no calls? maybe retry (leak recovery, empty turn) or
 *   stop -> otherwise remember the turn, run its calls, check that every call
 *   has exactly one result, send the results back, repeat.
 *
 * Messages are neutral (`TurnMessage[]`): an in-loop assistant turn travels as
 * `assistant_turn` and is replayed through its `raw` payload, and results come
 * back as ordered `tool_results` items keyed by call id.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import type {
  AdapterCapabilities,
  AssistantTurn,
  ToolCall,
  ToolResultItem,
  TurnMessage,
} from './types.ts';

export interface LoopCallOptions {
  /** Monotonic per-turn call counter (retries count); adapters derive call ids from it. */
  step: number;
  thinking: boolean;
  toolChoice: 'auto' | 'required' | 'none';
}

export type LoopCall = (messages: TurnMessage[], options: LoopCallOptions) => Promise<AssistantTurn>;

/** Retry limits the route has always used. */
export const MAX_LEAK_RECOVERY = 2;
export const MAX_EMPTY_TURN_RETRIES = 2;

/** The user message that asks for a closing summary once the tool budget is spent. */
export const BUDGET_SUMMARY_PROMPT =
  'Tool budget reached. Summarize your findings so far for the ' +
  'operator, even if the investigation is incomplete. Do not ' +
  'call any more tools.';

/* ─── Call-id invariant ─────────────────────────────────────── */

const NO_RESULT_PAYLOAD = 'no result recorded';

/**
 * Before a follow-up, every call id must have exactly one result: Claude and
 * OpenAI answer an unmatched call with a 400. A call with no result gets
 * `{ error: 'no result recorded' }` at its own position (Gemini matches results
 * to calls by position); extras and duplicates are logged and left alone.
 *
 * On well-formed input this returns the very same array, untouched: same
 * order, a directive staying wherever the route put it.
 */
export function reconcileToolResults(
  calls: ToolCall[],
  items: ToolResultItem[],
  warn: (message: string) => void = () => {},
): ToolResultItem[] {
  const callIndex = new Map<string, number>();
  calls.forEach((call, i) => callIndex.set(call.id, i));

  const seen = new Map<string, number>();
  for (const item of items) {
    if (item.kind !== 'result') continue;
    seen.set(item.callId, (seen.get(item.callId) ?? 0) + 1);
    if (!callIndex.has(item.callId)) {
      warn(`tool result for unknown call id ${item.callId} (${item.name}); left in place`);
    }
  }
  for (const [callId, count] of seen) {
    if (count > 1) warn(`call id ${callId} has ${count} results; left in place`);
  }

  const missing = calls.filter((call) => !seen.has(call.id));
  if (missing.length === 0) return items;

  const out = items.slice();
  for (const call of missing) {
    warn(`no result recorded for call ${call.id} (${call.name}); filled with an error result`);
    const mine = callIndex.get(call.id) as number;
    // Insert before the first result that belongs to a later call, else append.
    let at = out.findIndex(
      (item) => item.kind === 'result' && (callIndex.get(item.callId) ?? -1) > mine,
    );
    if (at < 0) at = out.length;
    out.splice(at, 0, {
      kind: 'result',
      callId: call.id,
      name: call.name,
      payload: { error: NO_RESULT_PAYLOAD },
    });
  }
  return out;
}

/* ─── The loop ──────────────────────────────────────────────── */

export interface ModelLoopArgs {
  /** The turn the first model call returned. */
  initial: AssistantTurn;
  /** Mutated: assistant turns and tool results are appended as the loop runs. */
  messages: TurnMessage[];
  maxTurns: number;
  /** Thinking setting for normal (non-retry) calls. */
  turnThinking: boolean;
  capabilities: AdapterCapabilities;
  /** First unused call counter value (the route's initial call used 0). */
  nextCallStep: number;
  call: LoopCall;
  /** Emit the turn's thinking and text to the operator and record its text. */
  presentTurn: (turn: AssistantTurn, step: number) => Promise<void>;
  /** Whether any answer text has been produced so far this user message. */
  hasFinalText: () => boolean;
  /**
   * Run the turn's tool calls and return their results in order (a directive
   * item may sit between results). Called after the turn was added to
   * `messages`.
   */
  executeToolCalls: (turn: AssistantTurn, step: number) => Promise<ToolResultItem[]>;
  /** Called with each follow-up turn (cost accounting). */
  onFollowup: (turn: AssistantTurn) => void;
  note?: (message: string) => void;
  warn?: (message: string) => void;
}

export interface ModelLoopResult {
  /** The last turn returned by the model; unprocessed when the budget ran out. */
  lastTurn: AssistantTurn;
  /** True when the loop used every allowed turn instead of finishing. */
  exhaustedBudget: boolean;
  /** Next unused call counter value. */
  nextCallStep: number;
}

export async function runModelLoop(args: ModelLoopArgs): Promise<ModelLoopResult> {
  const note = args.note ?? (() => {});
  const warn = args.warn ?? (() => {});
  let turn = args.initial;
  let callStep = args.nextCallStep;
  let leakRecoveryAttempts = 0;
  let emptyTurnRetries = 0;
  let exhaustedBudget = true;

  for (let step = 0; step < args.maxTurns; step++) {
    await args.presentTurn(turn, step);

    if (turn.toolCalls.length === 0) {
      // The model meant to call a tool but serialized the call into its
      // thinking: retry the same turn once more with a forced call and
      // thinking off. Gemini-only.
      if (
        args.capabilities.leakRecovery &&
        turn.leakedToolCallSuspected &&
        leakRecoveryAttempts < MAX_LEAK_RECOVERY
      ) {
        leakRecoveryAttempts++;
        note(
          `Tool call leaked into thinking channel; retrying with forced function-calling (attempt ${leakRecoveryAttempts}/${MAX_LEAK_RECOVERY})`,
        );
        turn = await args.call(args.messages, {
          step: callStep++,
          thinking: false,
          toolChoice: 'required',
        });
        continue;
      }
      // A genuinely empty turn (no calls and no text anywhere this message):
      // retry identically once, then with thinking off. Gemini-only.
      if (
        args.capabilities.emptyTurnRetry &&
        !args.hasFinalText() &&
        emptyTurnRetries < MAX_EMPTY_TURN_RETRIES
      ) {
        emptyTurnRetries++;
        const escalate = emptyTurnRetries > 1;
        note(
          `Empty model turn (no text, no tool calls); auto-retrying (attempt ${emptyTurnRetries}/${MAX_EMPTY_TURN_RETRIES}${escalate ? ', thinking off' : ''})`,
        );
        turn = await args.call(args.messages, {
          step: callStep++,
          thinking: escalate ? false : args.turnThinking,
          toolChoice: 'auto',
        });
        continue;
      }
      note('No tool calls requested');
      exhaustedBudget = false;
      break;
    }

    args.messages.push({ role: 'assistant_turn', turn });
    const items = await args.executeToolCalls(turn, step);
    args.messages.push({
      role: 'tool_results',
      items: reconcileToolResults(turn.toolCalls, items, warn),
    });

    note('Sending tool results to model');
    // The follow-up runs on the same model and thinking setting as the first
    // call; mixing models inside a turn would confuse the continuation.
    turn = await args.call(args.messages, {
      step: callStep++,
      thinking: args.turnThinking,
      toolChoice: 'auto',
    });
    note('Received follow-up response');
    args.onFollowup(turn);
  }

  return { lastTurn: turn, exhaustedBudget, nextCallStep: callStep };
}

/**
 * Ask for a closing summary after the loop spent its budget without producing
 * text. The tools stay in the catalog but the call is made with tool choice
 * 'none' (Gemini renders that as an empty tool list; Claude and OpenAI need the
 * tools present while their history still holds tool turns).
 */
export function requestBudgetSummary(args: {
  messages: TurnMessage[];
  call: LoopCall;
  step: number;
}): Promise<AssistantTurn> {
  args.messages.push({ role: 'user', text: BUDGET_SUMMARY_PROMPT });
  return args.call(args.messages, { step: args.step, thinking: false, toolChoice: 'none' });
}
