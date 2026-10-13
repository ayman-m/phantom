#!/usr/bin/env node
/**
 * Records the Gemini golden fixtures (fixtures.json) from the ORIGINAL chat
 * route code, before the Gemini logic moved into lib/providers/gemini/.
 *
 * It reads app/api/chat/route.ts as it was at commit f6c50edf (git show),
 * lifts the exact source of callGemini, callGeminiRaw, summarizeViaGemini and
 * every helper they use by pinned line range (each range is anchor-checked),
 * strips the TypeScript types with Node, and runs those functions in a vm
 * sandbox whose fetch, GoogleAuth, cache helper, clock and Math.random are
 * stubs. Every scenario in scenarios.mjs is replayed and the requests the
 * original code issued (URL, headers, exact body string), the auth and cache
 * calls, the sleeps, the warnings and the result or thrown message are written
 * down. The fixtures therefore describe what the code did before the move, not
 * what the moved code does.
 *
 * This is a provenance tool. It is not part of `npm test` and only works
 * while commit f6c50edf exists in the repository:
 *
 *   node scripts/fixtures/gemini-parity/record.mjs            (from mcp/agent)
 *
 * Re-running it must reproduce fixtures.json byte for byte.
 */
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import {
  FAKE_ACCESS_TOKEN,
  SYSTEM_TEXT,
  buildScenarios,
  legacyTools,
  runtimeConfigFor,
} from './scenarios.mjs';

const COMMIT = 'f6c50edf';
const ROUTE_PATH = 'mcp/agent/app/api/chat/route.ts';
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: here, encoding: 'utf8' }).trim();
const git = (...args) => execFileSync('git', args, { cwd: repoRoot, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });

const source = git('show', `${COMMIT}:${ROUTE_PATH}`);
const blob = git('rev-parse', `${COMMIT}:${ROUTE_PATH}`).trim();
const lines = source.split('\n');

/** Inclusive 1-based range, checked against an expected first and last line. */
function slice(from, to, firstStartsWith, lastEquals) {
  const first = lines[from - 1];
  const last = lines[to - 1];
  if (!first.startsWith(firstStartsWith) || last !== lastEquals) {
    throw new Error(`route.ts@${COMMIT} lines ${from}-${to} no longer match the anchors:\n  first: ${first}\n  last:  ${last}`);
  }
  return lines.slice(from - 1, to).join('\n');
}

const code = [
  slice(1800, 1840, 'const GEMINI_API_BASE', 'type GeminiToolSet = Array<{ functionDeclarations: unknown }>;'),
  slice(965, 998, 'async function callGeminiRaw(', '}'),
  slice(2155, 2264, 'const UNSUPPORTED_GEMINI_SCHEMA_KEYS', '}'),
  slice(2321, 2354, 'type GeminiCallPayload', '};'),
  slice(2356, 2361, 'function resolveVertexLocation', '}'),
  slice(2389, 2441, 'function detectPlaceholderCredential', '}'),
  slice(2443, 2474, 'function parseCredentialsInput', '}'),
  slice(2492, 2523, 'async function withRateLimitRetry', '}'),
  slice(2525, 2556, 'async function callGeminiWithApiKey', '}'),
  slice(2558, 2663, 'async function callGeminiWithVertex', '}'),
  slice(2665, 2670, 'function isInvalidGeminiApiKeyError', '}'),
  slice(2744, 2749, 'function resolveModelName', '}'),
  slice(2764, 2809, 'async function summarizeViaGemini', '}'),
  slice(2811, 2908, 'async function callGemini(', '}'),
].join('\n\n');

const js = stripTypeScriptTypes(code);

/* ─── Sandbox ───────────────────────────────────────────────── */

const state = {};
function resetState(scenario) {
  state.requests = [];
  state.authCalls = [];
  state.cacheCalls = [];
  state.promptCalls = [];
  state.sleeps = [];
  state.warns = [];
  state.queue = scenario.responses.map((r) => structuredClone(r));
  state.cacheMode = scenario.cache;
}

const fakeMath = Object.create(Math);
fakeMath.random = () => 0.25;

const sandbox = {
  console: {
    warn: (...args) => state.warns.push(args),
    log: () => {},
    error: () => {},
  },
  Math: fakeMath,
  setTimeout: (fn, ms) => {
    state.sleeps.push(ms);
    fn();
  },
  process: { env: {} },
  fetch: async (url, init) => {
    state.requests.push({ url, method: init.method, headers: { ...init.headers }, body: init.body });
    const next = state.queue.shift();
    if (!next) throw new Error('record.mjs: no scripted response left for this request');
    const text = next.text !== undefined ? next.text : JSON.stringify(next.body);
    return {
      ok: next.status < 400,
      status: next.status,
      text: async () => text,
      json: async () => (next.body !== undefined ? structuredClone(next.body) : JSON.parse(text)),
    };
  },
  GoogleAuth: class {
    constructor(opts) {
      state.authCalls.push({
        hasCredentials: Boolean(opts.credentials),
        credentialsProjectId: opts.credentials ? opts.credentials.project_id : null,
        keyFile: opts.keyFile ?? null,
        scopes: opts.scopes,
      });
    }
    async getProjectId() {
      return 'adc-project';
    }
    async getAccessToken() {
      return FAKE_ACCESS_TOKEN;
    }
  },
  getOrCreateSystemPromptCache: async (args) => {
    state.cacheCalls.push({ ...args });
    if (state.cacheMode === 'throw') throw sandbox.makeError('cache helper exploded');
    return state.cacheMode === 'name' ? 'cachedContents/parity-1' : null;
  },
  buildSystemPromptText: (...a) => {
    state.promptCalls.push({ modelArg: a[5] });
    return SYSTEM_TEXT;
  },
  getApprovalGating: async () => ({ known: false, gated: undefined }),
};
vm.createContext(sandbox);
// Errors the stubs throw must come from the sandbox realm, or `instanceof Error`
// inside the original code would be false and change what it logs.
sandbox.makeError = vm.runInContext('(message) => new Error(message)', sandbox);
const api = vm.runInContext(
  `${js}\n;({ callGemini, callGeminiRaw, summarizeViaGemini, sanitizeSchema });`,
  sandbox,
  { filename: `route.ts@${COMMIT}` },
);

/* ─── Replay ────────────────────────────────────────────────── */

async function replay(scenario) {
  resetState(scenario);
  sandbox.process.env = { ...scenario.env };
  const rc = runtimeConfigFor(scenario.creds);
  const l = scenario.legacy;
  const tools = legacyTools(l.toolsKind, (schema) => api.sanitizeSchema(schema));
  let result;
  try {
    let value;
    if (l.entry === 'callGemini') {
      value = await api.callGemini(
        structuredClone(l.contents), tools, rc, {}, l.model, null, null, 'manual', l.thinking, l.forceToolUse,
      );
    } else if (l.entry === 'callGeminiRaw') {
      value = await api.callGeminiRaw(
        structuredClone(l.contents), tools, rc, { role: 'system', parts: [{ text: l.systemText }] }, l.model,
      );
    } else {
      value = await api.summarizeViaGemini(l.systemText, l.userContent, rc, l.model);
    }
    result = { value: JSON.parse(JSON.stringify(value)) };
  } catch (err) {
    // The error comes from the sandbox realm, so read .message rather than instanceof.
    result = { thrown: typeof err?.message === 'string' ? err.message : String(err) };
  }
  return JSON.parse(
    JSON.stringify({
      id: scenario.id,
      note: scenario.note,
      requests: state.requests,
      authCalls: state.authCalls,
      cacheCalls: state.cacheCalls,
      systemPromptModelArgs: state.promptCalls.map((c) => c.modelArg),
      sleeps: state.sleeps,
      warns: state.warns,
      result,
    }),
  );
}

const scenarios = [];
for (const scenario of buildScenarios()) scenarios.push(await replay(scenario));

const out = {
  provenance: {
    commit: COMMIT,
    file: ROUTE_PATH,
    blob,
    recorder: 'scripts/fixtures/gemini-parity/record.mjs',
    stubs: 'fetch, GoogleAuth, getOrCreateSystemPromptCache, buildSystemPromptText, getApprovalGating, setTimeout, Math.random (0.25)',
    note: 'Request bodies are the exact JSON.stringify strings the original code produced. No real credential appears here.',
  },
  scenarios,
};
writeFileSync(join(here, 'fixtures.json'), JSON.stringify(out, null, 2) + '\n');
console.log(`recorded ${scenarios.length} scenarios from ${COMMIT} (route.ts blob ${blob.slice(0, 10)})`);
