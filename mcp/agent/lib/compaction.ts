/**
 * Conversation compaction — operator-triggered summarization.
 *
 * The operator can run a `/compress` slash command in chat to
 * manually flush long conversation history into a compact summary,
 * freeing up context budget for new turns. Automatic compaction
 * (triggered when the budget walk decides we'd overflow) uses the
 * same path; this module is the shared helper both call.
 *
 * Design:
 *
 *   1. Take the prior persisted messages (from
 *      `/api/v1/sessions/{id}/messages`) and a `summarize` callback
 *      that knows how to invoke an LLM. Caller supplies the LLM —
 *      this module is provider-agnostic.
 *   2. Build a summarization prompt that asks the model to preserve:
 *        - Open tasks and current status
 *        - Decisions made
 *        - Opaque IDs verbatim (UUIDs, operation IDs, audit-row
 *          ids — anything the next turn might need to reference).
 *      OpenClaw's `IDENTIFIER_PRESERVATION_INSTRUCTIONS` was the
 *      reference here.
 *   3. Return the summary text + a checkpoint marker that
 *      `loadSessionHistory` can recognize.
 *
 * The checkpoint shape:
 *
 *      role: 'system'
 *      content: '<summary text>'
 *      meta: { kind: 'compaction-checkpoint', covers_until: <iso ts> }
 *
 * loadSessionHistory looks for the latest message with
 * `meta.kind === 'compaction-checkpoint'` and treats everything
 * BEFORE it as already-summarized. Only the checkpoint itself + every
 * message AFTER it ends up in the Gemini contents array. So the
 * operator can run /compress whenever — older turns roll into the
 * checkpoint and stop consuming budget.
 *
 * Why an explicit checkpoint marker instead of replacing-then-
 * deleting: persistence stays append-only (audit-friendly), the
 * original transcript is still recoverable for export, and multiple
 * compactions can stack (each new checkpoint supersedes prior ones
 * without a destructive write).
 */

/** Persisted message shape from the MCP session store. Same as the
 *  one in `app/api/chat/route.ts`; redeclared here so this module
 *  stands alone. */
export interface CompactionInputMessage {
  role: string;
  content: string;
  tool_call_id?: string;
  created_at?: string;
  meta?: Record<string, unknown>;
}

export interface CompactionResult {
  /** The summary text produced by the LLM. */
  summary: string;
  /** ISO-8601 timestamp marking the latest message that was rolled
   *  into the summary. Stored on the checkpoint's meta so
   *  loadSessionHistory can determine "is this checkpoint covering
   *  message X?" without scanning. */
  coversUntil: string;
  /** Number of messages summarized (for telemetry / operator
   *  feedback in the chat UI). */
  messagesSummarized: number;
}

/**
 * Format the prior messages as a chat-ish transcript that the
 * summarizer model can read. Tool messages get included with their
 * arguments so the summary captures "what tool ran with what
 * outcome" — the operator's most-cited need.
 */
function renderTranscript(messages: CompactionInputMessage[]): string {
  return messages
    .map((m, i) => {
      const role = m.role === 'tool' ? `tool[${m.tool_call_id ?? '?'}]` : m.role;
      // Trim very long tool results — the summarizer needs the gist,
      // not the full payload. Same 500-char cap as the chat replay.
      const content =
        m.role === 'tool' && m.content.length > 500
          ? `${m.content.slice(0, 500).trimEnd()}…[+${m.content.length - 500} chars]`
          : m.content;
      return `[${i + 1}] ${role}:\n${content}`;
    })
    .join('\n\n');
}

/**
 * The summarization instructions sent to the model. Modeled after
 * OpenClaw's `MERGE_SUMMARIES_INSTRUCTIONS` +
 * `IDENTIFIER_PRESERVATION_INSTRUCTIONS` (see src/agents/compaction.ts
 * lines ~56–74), adapted for Phantom's vocabulary.
 *
 * Grounded-vs-unverified split: a checkpoint REPLACES the raw
 * transcript for every later turn, and each checkpoint feeds the
 * next summarizer's input (see loadSessionHistory() in
 * app/api/chat/route.ts) — a hallucinated claim from turn 3 that
 * isn't flagged gets re-summarized as settled fact at turn 20 and
 * loses its hedging on every pass after that. The instructions below
 * only preserve as "decided"/"verbatim" what a tool call actually
 * backed; everything else gets labelled unconfirmed instead of
 * silently laundered forward. Applies to BOTH the automatic
 * compaction path (fires inside loadSessionHistory() with no
 * operator action once enough messages would be dropped) and the
 * explicit /compress command — this file is the single instruction
 * set both go through.
 *
 * Exported so callers (and a future test) can inspect / override.
 */
export const SUMMARIZE_INSTRUCTIONS = `You are summarizing a chat session
between a human operator and the Phantom MCP agent so the conversation
can continue with less context budget.

Produce a SINGLE compact summary covering:

  1. **Active tasks and their current status** — anything the operator
     is in the middle of doing, what's done, what's blocked, what
     needs review.
  2. **GROUNDED decisions and findings** — choices the operator
     endorsed (vendor X for firewall, schedule Y for the daily job),
     AND conclusions backed by an actual tool result or a field on a
     record the agent looked up. The next turn must read ONLY these
     as already-decided, not re-litigated.
  3. **Tool round-trips and their outcomes** — which tools were
     invoked, what arguments, what results. Operators routinely
     reference earlier tool outputs ("show me the result of that port
     scan again"); the summary must preserve enough detail that the
     model can answer.
  4. **Opaque identifiers VERBATIM, but ONLY the ones that came from a
     tool result or a looked-up record**: UUIDs, operation IDs,
     session IDs, rule IDs, IP addresses, hostnames, audit-row ids,
     timestamps, vendor:product strings. Never paraphrase or
     summarize these — copy them exactly. The operator and the next
     turn will use them as keys to look things up.

An assistant claim made WITHOUT a tool call behind it is an UNVERIFIED
assertion, not a grounded finding — label it "unconfirmed" in the
summary rather than folding it into (2) or (4). A confident tone, or a
prior checkpoint repeating the claim, does not make it grounded — never
launder an unverified assertion into settled fact across a compaction
boundary. Concretely: a dataset name, CEF/XDM field name, connector
instance ID, or Caldera adversary profile ID the assistant stated
without a tool result behind it stays unconfirmed, however specific
and plausible it reads.

Format: concise paragraphs. No headers, no bullet lists, no markdown
formatting. Just dense prose. Aim for ~300-500 words regardless of
input length.

Do NOT:
  - Add commentary ("the operator seems frustrated", "this was
    interesting"). Stick to facts.
  - Speculate about future actions.
  - Drop verbatim IDs. If you summarize a UUID, you've broken the
    contract.
  - Present an unconfirmed assistant claim as a grounded decision or
    finding — even if a prior checkpoint already stated it that way.
  - Invent or firm up a specific-sounding identifier (dataset name,
    field name, instance ID) that didn't come from an actual tool
    result in this session.`;

/**
 * Run a compaction pass.
 *
 * @param messages   The prior session messages, oldest-first.
 * @param summarize  A callback that accepts an instruction + transcript
 *                   string and returns the model's summary text. The
 *                   caller wires this to its LLM provider (Gemini /
 *                   Claude / OpenAI). The shape is intentionally
 *                   provider-agnostic.
 *
 * Returns null if `messages` is empty — there's nothing to compact.
 */
export async function compactMessages(
  messages: CompactionInputMessage[],
  summarize: (instructions: string, transcript: string) => Promise<string>,
): Promise<CompactionResult | null> {
  if (messages.length === 0) return null;
  const transcript = renderTranscript(messages);
  const summary = (await summarize(SUMMARIZE_INSTRUCTIONS, transcript)).trim();
  if (!summary) return null;

  // Latest message timestamp (or now() if none) marks the cover-until
  // boundary for loadSessionHistory's checkpoint awareness.
  const latest = messages[messages.length - 1];
  const coversUntil =
    latest.created_at && /^\d{4}-/.test(latest.created_at)
      ? latest.created_at
      : new Date().toISOString();

  return {
    summary,
    coversUntil,
    messagesSummarized: messages.length,
  };
}

/** Marker we attach to the persisted checkpoint message's meta so
 *  loadSessionHistory recognizes it without string-matching content. */
export const COMPACTION_CHECKPOINT_KIND = 'compaction-checkpoint';

/** Type predicate — true if a persisted message is a compaction
 *  checkpoint (the loadSessionHistory side uses this to short-circuit
 *  to "start replay from this checkpoint forward"). */
export function isCompactionCheckpoint(m: {
  role: string;
  meta?: Record<string, unknown>;
}): boolean {
  return (
    m.role === 'system' &&
    m.meta != null &&
    m.meta['kind'] === COMPACTION_CHECKPOINT_KIND
  );
}
