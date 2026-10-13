/**
 * Scenario inputs for the Gemini payload parity harness.
 *
 * Each scenario is described twice, on purpose and by hand:
 *   - `legacy`:  the Gemini-shaped arguments the chat route's callGemini,
 *                callGeminiRaw and summarizeViaGemini receive;
 *   - `neutral`: the equivalent provider-neutral ModelRequest.
 * `record.mjs` replays `legacy` through the original route code (pinned to a
 * commit) to produce fixtures.json; scripts/test-gemini-payload-parity.mjs
 * replays the same scenarios through the moved functions and through the
 * adapter and compares bytes.
 *
 * Nothing here is a real credential. The service-account JSON is assembled at
 * run time from filler characters; the API key and token are obvious fakes.
 */

export const FAKE_API_KEY = 'FAKE-GEMINI-KEY-parity-0001';
export const FAKE_ACCESS_TOKEN = 'fake-access-token-parity';
export const SYSTEM_TEXT = 'PARITY SYSTEM PROMPT (stands in for buildSystemPromptText output)';
export const SUBAGENT_SYSTEM_TEXT = 'You are the parity subagent. Use only the tools you are given.';
export const SUMMARIZE_SYSTEM_TEXT = 'Summarize the transcript in five bullet points.';
export const SUMMARIZE_USER_TEXT = 'user: hello\nassistant: hi there\nuser: list datasets';
export const KEYFILE_PATH = '/etc/parity/service-account.json';

/** Service-account JSON that passes detectPlaceholderCredential, built at run time. */
export function fakeServiceAccountJson(projectId = 'parity-project') {
  const marker = ['-----BEGIN', 'PRIVATE KEY-----'].join(' ');
  const endMarker = ['-----END', 'PRIVATE KEY-----'].join(' ');
  const body = 'A'.repeat(320);
  return JSON.stringify({
    type: 'service_account',
    project_id: projectId,
    private_key: `${marker}\n${body}\n${endMarker}\n`,
    client_email: 'parity@parity-project.iam.gserviceaccount.com',
  });
}

/** A service-account JSON that must be rejected as a placeholder. */
export function placeholderServiceAccountJson() {
  const marker = ['-----BEGIN', 'PRIVATE KEY-----'].join(' ');
  const endMarker = ['-----END', 'PRIVATE KEY-----'].join(' ');
  return JSON.stringify({
    type: 'service_account',
    project_id: 'parity-project',
    private_key: `${marker}\nfake\n${endMarker}\n`,
    client_email: 'parity@parity-project.iam.gserviceaccount.com',
  });
}

/* ─── Tools ─────────────────────────────────────────────────── */

const XQL_SCHEMA = () => ({
  type: 'object',
  $schema: 'http://json-schema.org/draft-07/schema#',
  additionalProperties: false,
  properties: {
    query: { type: 'string', description: 'XQL text', minLength: 1, pattern: '^\\w+' },
    filters: { type: 'array', items: { $ref: '#/$defs/Filter' } },
    mode: { oneOf: [{ type: 'string' }, { type: 'integer' }], description: 'Execution mode' },
    options: {
      type: 'object',
      properties: { limit: { type: 'integer', default: 10, exclusiveMinimum: 0 } },
    },
  },
  required: ['query'],
  $defs: {
    Filter: {
      type: 'object',
      properties: { field: { type: 'string' }, value: { type: 'string', const: 'x' } },
      required: ['field'],
    },
  },
});

/** MCP-shaped tools (name, description, inputSchema). Fresh copy per call. */
export function rawTools() {
  return [
    { name: 'xsiam.run_xql_query', description: 'Run an XQL query', inputSchema: XQL_SCHEMA() },
    { name: 'xsiam_run_xql_query', description: 'Run an XQL query', inputSchema: XQL_SCHEMA() },
    {
      name: 'jobs_create',
      description: 'Create a scheduled job',
      inputSchema: {
        type: 'object',
        properties: { name: { type: 'string' }, cron: { type: 'string', title: 'Cron' } },
        required: ['name'],
      },
    },
    { name: 'no_schema_tool', description: '', inputSchema: {} },
    {
      name: 'tree_tool',
      description: 'Takes a recursive structure',
      inputSchema: {
        type: 'object',
        properties: { root: { $ref: '#/$defs/Node' } },
        $defs: { Node: { type: 'object', properties: { child: { $ref: '#/$defs/Node' } } } },
      },
    },
    {
      name: 'list_tool',
      description: 'Takes a list of variants',
      inputSchema: {
        type: 'object',
        properties: {
          items: { type: 'array', items: { anyOf: [{ type: 'string' }, { type: 'number' }] }, maxItems: 5 },
        },
      },
    },
  ];
}

/** The synthetic subagent_create declaration, appended unsanitized by the route. */
export function subagentCreateDeclaration() {
  return {
    name: 'subagent_create',
    description:
      'Spawn a scoped subagent to perform a focused task. The subagent ' +
      'runs with its own system prompt and a curated tool subset.',
    parameters: {
      type: 'object',
      properties: {
        agent_name: { type: 'string', description: 'Name of the agent definition.' },
        prompt: { type: 'string', description: 'The task for the subagent.' },
      },
      required: ['agent_name', 'prompt'],
    },
  };
}

/**
 * Legacy Gemini tool set the way getGeminiTools builds it: sanitized MCP
 * declarations, then the synthetic declaration appended as-is.
 * `sanitize` is the schema function under test.
 */
export function legacyTools(kind, sanitize) {
  if (kind === 'empty') return [];
  const picked = kind === 'scoped' ? rawTools().slice(2, 4) : rawTools();
  const decls = picked.map((tool) => ({
    name: tool.name,
    description: tool.description || '',
    parameters: sanitize(tool.inputSchema || {}),
  }));
  if (kind === 'full') decls.push(subagentCreateDeclaration());
  return [{ functionDeclarations: decls }];
}

/** The same tool set as neutral ToolSpecs. */
export function neutralTools(kind) {
  if (kind === 'empty') return [];
  const picked = kind === 'scoped' ? rawTools().slice(2, 4) : rawTools();
  const specs = picked.map((tool) => ({
    name: tool.name,
    description: tool.description || '',
    inputSchema: tool.inputSchema || {},
  }));
  if (kind === 'full') {
    const d = subagentCreateDeclaration();
    specs.push({ name: d.name, description: d.description, inputSchema: d.parameters });
  }
  return specs;
}

/* ─── Histories ─────────────────────────────────────────────── */

const FIRST_USER = 'List the XSIAM datasets';
const FIRST_MODEL = 'There are three datasets.';
const SECOND_USER = 'Now query the Okta dataset for failed logins';
const DIRECTIVE_TEXT = 'STOP retrying the query. Summarize for the operator what failed.';
const BUDGET_TEXT =
  'Tool budget reached. Summarize your findings so far for the ' +
  'operator, even if the investigation is incomplete. Do not ' +
  'call any more tools.';

function modelParts() {
  return [
    { text: 'Reasoning about the query.', thought: true, thoughtSignature: 'c2lnbmF0dXJlLXBhcml0eQ==' },
    { text: 'I will run the query now.' },
    {
      functionCall: {
        name: 'xsiam.run_xql_query',
        args: { query: 'dataset = okta_sso_raw | limit 5', filters: [{ field: 'outcome', value: 'FAILURE' }] },
      },
      thoughtSignature: 'c2lnLXBhcml0eS0y',
    },
    { functionCall: { name: 'jobs_create', args: { name: 'nightly', cron: '0 2 * * *' } } },
  ];
}

function legacyToolResultParts() {
  return [
    { functionResponse: { name: 'xsiam.run_xql_query', response: { result: '{"rows":[1,2,3]}' } } },
    { functionResponse: { name: 'jobs_create', response: { error: 'permission denied' } } },
    {
      functionResponse: {
        name: 'caldera_list_agents',
        response: { error: "Tool 'caldera_list_agents' is outside the subagent's scope.", blocked_by: 'subagent_scope' },
      },
    },
    { functionResponse: { name: '__system_stop_directive__', response: { stop_directive: DIRECTIVE_TEXT } } },
  ];
}

function neutralToolResultItems() {
  return [
    { kind: 'result', callId: 'gem_0_0', name: 'xsiam.run_xql_query', payload: { result: '{"rows":[1,2,3]}' } },
    { kind: 'result', callId: 'gem_0_1', name: 'jobs_create', payload: { error: 'permission denied' } },
    {
      kind: 'result',
      callId: 'gem_0_2',
      name: 'caldera_list_agents',
      payload: { error: "Tool 'caldera_list_agents' is outside the subagent's scope.", blocked_by: 'subagent_scope' },
    },
    { kind: 'directive', text: DIRECTIVE_TEXT },
  ];
}

function neutralAssistantTurn(model) {
  return {
    provider: 'vertex',
    model,
    text: ['I will run the query now.'],
    thinking: ['Reasoning about the query.'],
    toolCalls: [
      { id: 'gem_0_0', name: 'xsiam.run_xql_query', args: {} },
      { id: 'gem_0_1', name: 'jobs_create', args: {} },
    ],
    finish: 'tool_use',
    usage: null,
    leakedToolCallSuspected: false,
    raw: modelParts(),
  };
}

function history(kind, model) {
  const base = [
    { role: 'user', parts: [{ text: FIRST_USER }] },
    { role: 'model', parts: [{ text: FIRST_MODEL }] },
    { role: 'user', parts: [{ text: SECOND_USER }] },
  ];
  const baseNeutral = [
    { role: 'user', text: FIRST_USER },
    { role: 'assistant', text: FIRST_MODEL },
    { role: 'user', text: SECOND_USER },
  ];
  if (kind === 'base') return { contents: base, messages: baseNeutral };
  const followup = [
    ...base,
    { role: 'model', parts: modelParts() },
    { role: 'user', parts: legacyToolResultParts() },
  ];
  const followupNeutral = [
    ...baseNeutral,
    { role: 'assistant_turn', turn: neutralAssistantTurn(model) },
    { role: 'tool_results', items: neutralToolResultItems() },
  ];
  if (kind === 'followup') return { contents: followup, messages: followupNeutral };
  if (kind === 'budget') {
    // Two consecutive user contents: the route appends the budget text as its
    // own user message after the tool results. They must not be merged.
    return {
      contents: [...followup, { role: 'user', parts: [{ text: BUDGET_TEXT }] }],
      messages: [...followupNeutral, { role: 'user', text: BUDGET_TEXT }],
    };
  }
  throw new Error(`unknown history kind ${kind}`);
}

/* ─── Scenarios ─────────────────────────────────────────────── */

const OK_BODY = () => ({
  candidates: [
    {
      content: { role: 'model', parts: [{ text: 'ok' }] },
      finishReason: 'STOP',
    },
  ],
  usageMetadata: { promptTokenCount: 12, cachedContentTokenCount: 4, candidatesTokenCount: 3 },
});
const OK = () => ({ status: 200, body: OK_BODY() });

const PRO = 'gemini-3.1-pro-preview';
const FLASH = 'gemini-2.5-flash';

/**
 * Build the scenario list. `entry` names the route function the legacy side
 * calls; `creds` selects the transport.
 */
export function buildScenarios() {
  const out = [];

  function add(s) {
    const model = s.model || PRO;
    const h = s.history ? history(s.history, model) : null;
    const entry = s.entry || 'callGemini';
    const purpose =
      entry === 'callGeminiRaw' ? 'subagent' : entry === 'summarize' ? 'summarize' : s.purpose || 'chat';
    const toolsKind = s.tools || (entry === 'summarize' ? 'empty' : 'full');
    const legacy = {
      entry,
      model,
      thinking: s.thinking === true,
      forceToolUse: s.forceToolUse === true,
      toolsKind,
    };
    let system;
    if (entry === 'summarize') {
      legacy.systemText = SUMMARIZE_SYSTEM_TEXT;
      legacy.userContent = SUMMARIZE_USER_TEXT;
      system = SUMMARIZE_SYSTEM_TEXT;
    } else if (entry === 'callGeminiRaw') {
      legacy.contents = h.contents;
      legacy.systemText = SUBAGENT_SYSTEM_TEXT;
      system = SUBAGENT_SYSTEM_TEXT;
    } else {
      legacy.contents = h.contents;
      system = SYSTEM_TEXT;
    }
    const messages =
      entry === 'summarize' ? [{ role: 'user', text: SUMMARIZE_USER_TEXT }] : h.messages;
    const toolChoice =
      toolsKind === 'empty' ? 'none' : s.forceToolUse ? 'required' : 'auto';
    out.push({
      id: s.id,
      note: s.note || '',
      entry,
      model,
      creds: s.creds,
      env: s.env || {},
      cache: s.cache,
      responses: s.responses || [OK()],
      legacy,
      neutral: {
        ref: { provider: 'vertex', model },
        system,
        messages,
        toolsKind,
        toolChoice,
        thinking: s.thinking === true,
        purpose,
      },
      // Whether the adapter can reproduce this scenario's error wording.
      adapterComparable: s.adapterComparable !== false,
    });
  }

  const KEY = { apiKey: true };
  const SA = { sa: 'json' };

  add({ id: 'main_thinking_off_apikey', history: 'base', creds: KEY });
  add({ id: 'main_thinking_on_apikey', history: 'base', thinking: true, creds: KEY });
  add({ id: 'main_force_tool_use_thinking_off', history: 'base', forceToolUse: true, creds: KEY,
    note: 'leak recovery retry: thinking off, mode ANY' });
  add({ id: 'main_force_tool_use_thinking_on', history: 'base', thinking: true, forceToolUse: true, creds: KEY,
    note: 'key order generationConfig then toolConfig' });
  add({ id: 'main_followup_tool_results_directive', history: 'followup', thinking: true, creds: KEY,
    note: 'replays raw thought parts with signature; tool results incl. stop directive' });
  add({ id: 'main_followup_thinking_off', history: 'followup', creds: KEY,
    note: 'escalated empty-turn retry sends thinking off' });
  add({ id: 'budget_summary_empty_tools', history: 'budget', tools: 'empty', creds: KEY,
    note: 'tools:[] while contents still hold tool turns; no generationConfig' });
  add({ id: 'summarize_apikey', entry: 'summarize', creds: KEY, model: FLASH });
  add({ id: 'subagent_apikey', entry: 'callGeminiRaw', history: 'followup', tools: 'scoped', creds: KEY });
  add({ id: 'main_vertex_json_global', history: 'followup', thinking: true, creds: SA,
    note: 'gemini-3 resolves location global' });
  add({ id: 'main_vertex_json_us_central', history: 'base', creds: SA, model: 'gemini-2.5-pro',
    note: 'gemini-2.5 resolves location us-central1' });
  add({ id: 'main_vertex_keyfile', history: 'base', creds: { sa: 'keyfile' },
    note: 'key file path: project id comes from the auth client' });
  add({ id: 'summarize_vertex', entry: 'summarize', creds: SA, model: FLASH });
  add({ id: 'subagent_vertex', entry: 'callGeminiRaw', history: 'base', tools: 'scoped', creds: SA });
  add({ id: 'vertex_cache_swap', history: 'followup', thinking: true, creds: SA, env: { PHANTOM_VERTEX_CACHE: '1' },
    cache: 'name', note: 'cachedContent replaces systemInstruction, key placed last' });
  add({ id: 'vertex_cache_miss_inline', history: 'base', creds: SA, env: { PHANTOM_VERTEX_CACHE: '1' },
    cache: 'null', note: 'helper returns null: systemInstruction stays inline' });
  add({ id: 'vertex_cache_throws_inline', history: 'base', creds: SA, env: { PHANTOM_VERTEX_CACHE: '1' },
    cache: 'throw', note: 'helper throws: warn and inline' });
  add({ id: 'vertex_cache_flag_off_ignores_cache', history: 'base', creds: SA, env: { PHANTOM_VERTEX_CACHE: '0' },
    cache: 'name', note: 'flag not "1": helper is never consulted' });
  add({ id: 'apikey_invalid_falls_back_to_vertex', history: 'base', creds: { apiKey: true, sa: 'json' },
    responses: [
      { status: 400, text: '{"error":{"message":"API key not valid. Please pass a valid API key.","status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}' },
      OK(),
    ],
    note: 'first request on the API key, second on Vertex' });
  add({ id: 'rate_limit_retry_then_ok', history: 'base', creds: KEY,
    responses: [
      { status: 429, text: '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}' },
      { status: 429, text: '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}' },
      OK(),
    ],
    note: 'two 429s then success: identical bodies, backoff sleeps 2250 then 4250' });
  add({ id: 'rate_limit_vertex_retry_then_ok', history: 'base', creds: SA, model: FLASH,
    responses: [{ status: 429, text: 'RESOURCE_EXHAUSTED' }, OK()],
    note: 'Vertex path retries too; label vertex:<model>@<location>' });
  add({ id: 'error_rate_limit_exhausted', history: 'base', creds: KEY,
    responses: Array.from({ length: 6 }, () => ({ status: 429, text: 'Resource exhausted' })),
    note: '6 x 429: 5 retries then the original error is thrown' });
  add({ id: 'error_apikey_500', history: 'base', creds: KEY,
    responses: [{ status: 500, text: 'internal boom' }], note: 'no retry on non-429' });
  add({ id: 'error_vertex_500', history: 'base', creds: SA,
    responses: [{ status: 500, text: 'internal boom' }] });
  add({ id: 'error_apikey_other_400_no_fallback', history: 'base', creds: { apiKey: true, sa: 'json' },
    responses: [{ status: 400, text: 'bad request, not a key problem' }],
    note: 'only an invalid-key error falls through to Vertex' });
  add({ id: 'error_placeholder_credential', history: 'base', creds: { sa: 'placeholder' } });
  add({ id: 'error_no_provider_main', history: 'base', creds: {} });
  add({ id: 'error_no_provider_subagent', entry: 'callGeminiRaw', history: 'base', tools: 'scoped', creds: {} });
  add({ id: 'error_no_provider_summarize', entry: 'summarize', creds: {}, model: FLASH });

  return out;
}

/** The runtime config object the route would pass for a scenario's creds. */
export function runtimeConfigFor(creds) {
  const rc = {};
  if (creds.apiKey) rc.GEMINI_API_KEY = FAKE_API_KEY;
  if (creds.sa === 'json') rc.GOOGLE_APPLICATION_CREDENTIALS = fakeServiceAccountJson();
  if (creds.sa === 'keyfile') rc.GOOGLE_APPLICATION_CREDENTIALS = KEYFILE_PATH;
  if (creds.sa === 'placeholder') rc.GOOGLE_APPLICATION_CREDENTIALS = placeholderServiceAccountJson();
  return rc;
}
