#!/usr/bin/env node
/**
 * Turn cost rows (lib/cost-rows.ts): how a model call becomes a `chat_turn_cost`
 * audit row, and how rows are read back and summed by the chat route, the
 * /observability/cost page, the /cost command and the cost-warn hook.
 *
 *   - Claude cache writes (5-minute and 1-hour) are priced, not dropped,
 *   - OpenAI reasoning tokens are recorded but not billed twice,
 *   - an unknown or unpriced model is `priced:false` with a null cost, never 0 or NaN,
 *   - a call is priced against its exact provider/model,
 *   - rows written before the provider fields still read (as vertex),
 *   - the summers and the hook are null-safe,
 *   - the route's SSE events and the single audit writer carry provider and model_ref.
 *
 *   node scripts/test-cost-rows.mjs   (npm run test:cost-rows)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node without
 * it the test skips (the build type-checks the modules).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const cr = await import("../lib/cost-rows.ts");
const { computeTurnCostUsd } = await import("../lib/providers/registry/pricing.ts");
const { lookupModelFacts } = await import("../lib/providers/registry/lookup.ts");
const { formatCostOrUnpriced } = await import("../lib/model-pricing.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.message).split("\n").join("\n     ")); }
}
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg ?? ""} ${a} != ${b}`);
const usage = (o = {}) => ({ inputTotal: 0, cacheRead: 0, cacheWrite: 0, cacheWrite1h: 0, output: 0, reasoning: 0, ...o });
const NOW = Date.parse("2026-10-13T12:00:00Z");
const build = (provider, model, u, extra = {}) =>
  cr.buildTurnCostMetadata({ usage: usage(u), provider, model, callKind: "initial", now: NOW, ...extra });
/** No NaN, Infinity or undefined anywhere in a value (JSON would silently turn NaN into null). */
function assertClean(value, where = "value") {
  const walk = (v, path) => {
    if (typeof v === "number") assert.ok(Number.isFinite(v), `${path} is ${v}`);
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, `${path}.${k}`);
    else assert.notEqual(v, undefined, `${path} is undefined`);
  };
  walk(value, where);
}

// ── Pricing from NeutralUsage ─────────────────────────────────────────────

test("Claude: 5-minute and 1-hour cache writes are priced and recorded", () => {
  // claude-sonnet-5-5: input 2, cache read 0.1, 5m write 2.5, 1h write 4, output 10 (per M).
  const { metadata: m, call } = build("anthropic", "claude-sonnet-5-5", {
    inputTotal: 3100, cacheRead: 1000, cacheWrite: 2000, cacheWrite1h: 500, output: 400,
  });
  assert.equal(m.priced, true);
  assert.equal(m.cache_write_tokens, 2000);
  assert.equal(m.cache_write_1h_tokens, 500);
  const writes = (1500 / 1e6) * 2.5 + (500 / 1e6) * 4;
  near(m.cost_components.cache_write_usd, writes, "cache write usd");
  const want = (100 / 1e6) * 2 + (1000 / 1e6) * 0.1 + writes + (400 / 1e6) * 10;
  near(m.cost_usd, want, "total");
  near(call.usd, want);
  // The T6 gap: pricing with the writes dropped (cacheWrite 0) bills the 2000 written tokens as plain input.
  const dropped = computeTurnCostUsd(usage({ inputTotal: 3100, cacheRead: 1000, output: 400 }), lookupModelFacts("anthropic/claude-sonnet-5-5"), { now: NOW });
  assert.ok(Math.abs(dropped.usd - want) > 1e-7, "dropping the writes must change the bill");
});

test("Claude: a cache write outweighing the reads gives negative savings, not a crash", () => {
  const { metadata: m } = build("anthropic", "claude-sonnet-5-5", { inputTotal: 10_000, cacheWrite: 10_000, output: 10 });
  assert.equal(m.priced, true);
  assert.ok(m.cost_components.cached_savings_usd < 0);
  assertClean(m);
});

test("OpenAI: reasoning tokens are recorded and already inside output, so never billed twice", () => {
  // gpt-6-sol: input 2, cache read 0.2, output 10. output_tokens (1000) includes 600 reasoning.
  const { metadata: m } = build("openai", "gpt-6-sol", { inputTotal: 5000, cacheRead: 1000, output: 1000, reasoning: 600 });
  assert.equal(m.reasoning_tokens, 600);
  assert.equal(m.output_tokens, 1000);
  near(m.cost_components.output_usd, (1000 / 1e6) * 10, "output billed once");
  near(m.cost_usd, (4000 / 1e6) * 2 + (1000 / 1e6) * 0.2 + (1000 / 1e6) * 10);
});

test("Gemini: thinking tokens are inside output (the adapter adds them), billed once at the output rate", () => {
  // gemini-2.5-pro: output is billed on usage.output; 18 = 7 answer + 11 thinking tokens.
  const priced = build("vertex", "gemini-2.5-pro", { inputTotal: 100, output: 18, reasoning: 11 });
  const answerOnly = build("vertex", "gemini-2.5-pro", { inputTotal: 100, output: 7, reasoning: 11 });
  assert.equal(priced.metadata.output_tokens, 18);
  assert.equal(priced.metadata.reasoning_tokens, 11);
  assert.ok(priced.metadata.cost_usd > answerOnly.metadata.cost_usd, "thinking tokens add to the bill");
  near(priced.metadata.cost_components.output_usd, (18 / 1e6) * 5, "gemini-2.5-pro output rate 5 per M, billed once");
});

test("OpenAI: cache writes are priced at the model's write rate", () => {
  const { metadata: m } = build("openai", "gpt-6-sol", { inputTotal: 5000, cacheRead: 1000, cacheWrite: 2000, output: 100 });
  near(m.cost_components.cache_write_usd, (2000 / 1e6) * 2.5);
});

test("Gemini: the legacy fields keep their meaning and the numbers are the old ones", () => {
  const { metadata: m } = build("vertex", "gemini-2.5-pro", { inputTotal: 10_000, cacheRead: 4_000, output: 500 });
  assert.equal(m.input_tokens, 10_000);
  assert.equal(m.cached_input_tokens, 4_000);
  assert.equal(m.uncached_input_tokens, 6_000);
  assert.equal(m.output_tokens, 500);
  assert.equal(m.model, "gemini-2.5-pro", "model stays the bare id");
  assert.equal(m.provider, "vertex");
  assert.equal(m.model_ref, "vertex/gemini-2.5-pro");
  assert.equal(m.cache_write_tokens, 0);
  assert.equal(m.reasoning_tokens, 0);
  const pricing = lookupModelFacts("vertex/gemini-2.5-pro").pricing;
  near(m.cost_components.input_usd, (6_000 / 1e6) * pricing.inputPerM);
  near(m.cost_components.cached_input_usd, (4_000 / 1e6) * pricing.cacheReadPerM);
  near(m.cost_components.cached_savings_usd, (10_000 / 1e6) * pricing.inputPerM - ((6_000 / 1e6) * pricing.inputPerM + (4_000 / 1e6) * pricing.cacheReadPerM));
});

test("the row names the request and the finish reason when the provider gave them", () => {
  const { metadata: m } = build("anthropic", "claude-sonnet-5-5", { inputTotal: 10, output: 1 }, { requestId: "req_1", finish: "tool_use" });
  assert.equal(m.request_id, "req_1");
  assert.equal(m.finish, "tool_use");
  assert.equal(m.pricing_verified, lookupModelFacts("anthropic/claude-sonnet-5-5").pricingVerified);
  const bare = build("anthropic", "claude-sonnet-5-5", { inputTotal: 10 }).metadata;
  assert.equal("request_id" in bare, false);
});

// ── Unpriced ──────────────────────────────────────────────────────────────

test("an unknown model is unpriced: null cost, null components, a reason, and no NaN", () => {
  const { metadata: m, call } = build("anthropic", "not-a-model", { inputTotal: 100_000, cacheRead: 5, output: 5000, reasoning: 7 });
  assert.equal(m.priced, false);
  assert.equal(m.cost_usd, null);
  assert.equal(m.cost_components, null);
  assert.equal(m.unpriced_reason, "unknown_model");
  assert.equal(m.pricing_verified, null);
  assert.equal(call.usd, null);
  assert.equal(call.priced, false);
  assert.equal(m.input_tokens, 100_000, "tokens are still recorded");
  assertClean(m);
  assert.ok(!JSON.stringify(m).includes("NaN"));
});

test("a known model with no price is unpriced with the no_pricing reason", () => {
  const { metadata: m } = build("vertex", "gemini-3.7-flash", { inputTotal: 1000, output: 100 });
  assert.equal(m.priced, false);
  assert.equal(m.cost_usd, null);
  assert.equal(m.unpriced_reason, "no_pricing");
});

test("an expired promotional price is unpriced", () => {
  const before = build("openai", "gpt-5.6-sol", { inputTotal: 1000, output: 100 }, { now: Date.parse("2026-11-21T12:00:00Z") }).metadata;
  const after = build("openai", "gpt-5.6-sol", { inputTotal: 1000, output: 100 }, { now: Date.parse("2026-11-22T12:00:00Z") }).metadata;
  assert.equal(before.priced, true);
  assert.equal(after.priced, false);
  assert.equal(after.unpriced_reason, "pricing_expired");
  assert.equal(after.cost_usd, null);
});

test("a call is priced against its exact provider/model, not a same-named model elsewhere", () => {
  const right = build("anthropic", "claude-sonnet-5-5", { inputTotal: 1000, output: 100 }).metadata;
  const wrong = build("openai", "claude-sonnet-5-5", { inputTotal: 1000, output: 100 }).metadata;
  assert.equal(right.priced, true);
  assert.equal(wrong.priced, false, "openai has no such model");
  assert.equal(wrong.model_ref, "openai/claude-sonnet-5-5");
});

test("garbage usage fields become zero, never NaN", () => {
  const { metadata: m } = build("anthropic", "claude-sonnet-5-5", {
    inputTotal: Number.NaN, cacheRead: -5, cacheWrite: Number.POSITIVE_INFINITY, output: undefined, reasoning: "x",
  });
  assertClean(m);
  assert.equal(m.input_tokens, 0);
  assert.equal(m.cached_input_tokens, 0);
});

test("formatCostOrUnpriced says unpriced for null and NaN, a dollar figure otherwise", () => {
  assert.equal(formatCostOrUnpriced(null), "unpriced");
  assert.equal(formatCostOrUnpriced(undefined), "unpriced");
  assert.equal(formatCostOrUnpriced(Number.NaN), "unpriced");
  assert.equal(formatCostOrUnpriced(0), "$0");
  assert.equal(formatCostOrUnpriced(0.42), "$0.420");
});

// ── Reading rows, including rows from before the provider fields ─────────

const OLD_ROW = {
  metadata: {
    call_kind: "followup", input_tokens: 10_000, cached_input_tokens: 4_000, output_tokens: 500, uncached_input_tokens: 6_000,
    cost_usd: 0.0123,
    cost_components: { input_usd: 0.01, cached_input_usd: 0.001, output_usd: 0.0013, uncached_hypothetical_input_usd: 0.02, cached_savings_usd: 0.009 },
    model: "gemini-2.5-pro",
  },
};

test("an old row (no provider, model_ref, priced, cache-write or reasoning fields) reads as a priced vertex call", () => {
  const r = cr.readCostRow(OLD_ROW);
  assert.equal(r.provider, "vertex");
  assert.equal(r.modelRef, "vertex/gemini-2.5-pro");
  assert.equal(r.priced, true);
  assert.equal(r.usd, 0.0123);
  assert.equal(r.savingsUsd, 0.009);
  assert.equal(r.cacheWrite, 0);
  assert.equal(r.reasoning, 0);
  assert.equal(r.input, 10_000);
  assert.equal(r.callKind, "followup");
});

test("an old row that recorded $0 stays a priced $0 (every old row was priced)", () => {
  const r = cr.readCostRow({ metadata: { model: "gemini-2.5-pro", input_tokens: 0, cost_usd: 0 } });
  assert.equal(r.priced, true);
  assert.equal(r.usd, 0);
});

test("a new unpriced row reads as unpriced with a null cost", () => {
  const { metadata } = build("anthropic", "not-a-model", { inputTotal: 10 });
  const r = cr.readCostRow({ metadata });
  assert.equal(r.priced, false);
  assert.equal(r.usd, null);
  assert.equal(r.modelRef, "anthropic/not-a-model");
});

test("malformed rows read without throwing", () => {
  for (const bad of [null, undefined, {}, { metadata: null }, { metadata: "x" }, { metadata: { cost_usd: "0.5", input_tokens: "9", provider: 7, model: {} } }, 5, "row"]) {
    const r = cr.readCostRow(bad);
    assertClean(r);
    assert.equal(r.provider, "vertex");
    assert.equal(r.usd, null);
  }
});

// ── Summing ───────────────────────────────────────────────────────────────

const ROWS = [
  OLD_ROW,
  { metadata: build("anthropic", "claude-sonnet-5-5", { inputTotal: 3100, cacheRead: 1000, cacheWrite: 2000, cacheWrite1h: 500, output: 400 }).metadata },
  { metadata: build("openai", "gpt-6-sol", { inputTotal: 5000, cacheRead: 1000, output: 1000, reasoning: 600 }).metadata },
  { metadata: build("anthropic", "not-a-model", { inputTotal: 7000, output: 70 }).metadata },
  { metadata: { model: "gemini-2.5-pro" } },
];

test("sumCostRows groups by provider and by provider/model, counting unpriced calls apart", () => {
  const t = cr.sumCostRows(ROWS);
  assertClean(t);
  assert.equal(t.calls, 5);
  assert.equal(t.unpricedCalls, 2, "the unknown model and the row with no cost");
  assert.deepEqual(Object.keys(t.byProvider).sort(), ["anthropic", "openai", "vertex"]);
  assert.equal(t.byProvider.vertex.calls, 2, "the old row and the bare one both read as vertex");
  assert.equal(t.byProvider.anthropic.calls, 2);
  assert.equal(t.byProvider.anthropic.unpricedCalls, 1);
  assert.ok(t.byModelRef["anthropic/claude-sonnet-5-5"]);
  assert.ok(t.byModelRef["anthropic/not-a-model"]);
  assert.ok(t.byModelRef["vertex/gemini-2.5-pro"]);
  assert.equal(t.byModelRef["vertex/gemini-2.5-pro"].calls, 2);
  assert.equal(t.cacheWrite, 2000);
  assert.equal(t.reasoning, 600);
  const claude = ROWS[1].metadata.cost_usd;
  const gpt = ROWS[2].metadata.cost_usd;
  near(t.usd, 0.0123 + claude + gpt, "dollar total is the priced rows only");
  near(t.byProvider.anthropic.usd, claude);
});

test("sumCostRows is null-safe for empty, null and undefined input", () => {
  for (const input of [[], null, undefined]) {
    const t = cr.sumCostRows(input);
    assert.equal(t.calls, 0);
    assert.equal(t.usd, 0);
    assertClean(t);
  }
});

test("a window of only unpriced calls has a zero dollar total and says unpriced", () => {
  const t = cr.sumCostRows([ROWS[3], ROWS[3]]);
  assert.equal(t.usd, 0);
  assert.equal(t.unpricedCalls, 2);
  assert.match(cr.describeBucketCost(t), /^unpriced \(2 calls/);
  assert.equal(cr.describeBucketCost(cr.sumCostRows([])), "$0");
  assert.match(cr.describeBucketCost(cr.sumCostRows([OLD_ROW, ROWS[3]])), /^\$0\.012 \+ 1 unpriced call$/);
});

test("the turn tally keeps priced and unpriced calls apart and never invents a figure", () => {
  const priced = build("anthropic", "claude-sonnet-5-5", { inputTotal: 1000, cacheWrite: 400, output: 100, reasoning: 10 }).call;
  const unpriced = build("anthropic", "not-a-model", { inputTotal: 500, output: 50 }).call;

  const none = cr.newTurnTally();
  assert.equal(cr.turnCostSummary(none).cost_usd, null, "no call, no figure");

  const allUnpriced = cr.newTurnTally();
  cr.addCallToTally(allUnpriced, unpriced);
  cr.addCallToTally(allUnpriced, unpriced);
  const a = cr.turnCostSummary(allUnpriced);
  assert.deepEqual({ cost_usd: a.cost_usd, priced: a.priced, unpriced_calls: a.unpriced_calls }, { cost_usd: null, priced: false, unpriced_calls: 2 });

  const mixed = cr.newTurnTally();
  cr.addCallToTally(mixed, priced);
  cr.addCallToTally(mixed, unpriced);
  const b = cr.turnCostSummary(mixed);
  assert.equal(b.priced, false, "a partial figure is not marked complete");
  near(b.cost_usd, Number(priced.usd.toFixed(6)));
  assert.equal(b.unpriced_calls, 1);
  assert.equal(b.cache_write_tokens, 400);
  assert.equal(b.reasoning_tokens, 10);
  assert.equal(b.input_tokens, 1500);
  assertClean(b);

  const ok = cr.newTurnTally();
  cr.addCallToTally(ok, priced);
  assert.equal(cr.turnCostSummary(ok).priced, true);
});

// ── Cache-hit savings ─────────────────────────────────────────────────────

test("cache-hit savings come from the model's own prices, per provider", () => {
  const claude = cr.cacheReadSavings({ usage: usage({ inputTotal: 5000, cacheRead: 4000 }), provider: "anthropic", model: "claude-sonnet-5-5", now: NOW });
  near(claude.usd, (4000 / 1e6) * (2 - 0.1));
  assert.equal(claude.tokensEquivalent, Math.floor(4000 * (1 - 0.1 / 2)));
  const sol = cr.cacheReadSavings({ usage: usage({ inputTotal: 5000, cacheRead: 1000 }), provider: "openai", model: "gpt-6-sol", now: NOW });
  near(sol.usd, (1000 / 1e6) * (2 - 0.2));
  assert.equal(cr.cacheReadSavings({ usage: usage({ inputTotal: 5000, cacheRead: 1000 }), provider: "anthropic", model: "nope", now: NOW }), null, "unpriced: no figure");
});

// ── The /cost reply ───────────────────────────────────────────────────────

test("the /cost reply is null-safe, groups by provider and model, and never calls an unpriced model $0", () => {
  const text = cr.renderCostSummary(cr.sumCostRows([ROWS[1], ROWS[3]]), cr.sumCostRows(ROWS));
  assert.ok(!/NaN|undefined|null/.test(text), text);
  assert.match(text, /Today by provider/);
  assert.match(text, /`anthropic`/);
  assert.match(text, /`vertex`/);
  assert.match(text, /Today by model/);
  assert.match(text, /`anthropic\/claude-sonnet-5-5`/);
  assert.match(text, /1 unpriced call/);
  assert.match(text, /2,000 written to cache/);
  assert.match(text, /600 reasoning/);
  assert.ok(!/counts as \$0/.test(text));
  const empty = cr.renderCostSummary(cr.sumCostRows([]), cr.sumCostRows(null));
  assert.match(empty, /\*\*\$0\*\*/);
  assert.ok(!/NaN|undefined/.test(empty));
});

// ── The cost-warn hook ────────────────────────────────────────────────────

test("the audit response the hook reads is {events, count, total}; the old `rows` key yields nothing", () => {
  const resp = { events: ROWS, count: 5, total: 5 };
  assert.equal(cr.auditResponseRows(resp).length, 5);
  assert.deepEqual(cr.auditResponseRows({ rows: ROWS }), []);
  for (const bad of [null, undefined, "x", 3, {}, { events: "nope" }]) assert.deepEqual(cr.auditResponseRows(bad), []);
});

test("the hook's total skips unpriced calls and reports how many it skipped", () => {
  const totals = cr.sumCostRows(cr.auditResponseRows({ events: ROWS }));
  near(totals.usd, 0.0123 + ROWS[1].metadata.cost_usd + ROWS[2].metadata.cost_usd);
  assert.equal(totals.unpricedCalls, 2);
  assertClean(totals);
});

test("the hook reads {events} through the shared summer and tells the operator about unpriced calls", () => {
  const src = readFileSync(new URL("../lib/hook-builtins/cost-warn-over-budget.ts", import.meta.url), "utf8");
  assert.match(src, /auditResponseRows\(resp\)/);
  assert.match(src, /sumCostRows\(/);
  assert.ok(!/resp\.rows|\.rows\b/.test(src), "the stale `rows` response key is gone");
  assert.match(src, /unpricedCalls/);
  assert.match(src, /unpriced_calls/);
});

// ── The writer and the SSE events ─────────────────────────────────────────

const routeSrc = readFileSync(new URL("../app/api/chat/route.ts", import.meta.url), "utf8");

test("the chat route has exactly one chat_turn_cost writer and it uses cost-rows", () => {
  assert.equal((routeSrc.match(/safeAudit\('chat_turn_cost'/g) ?? []).length, 1);
  assert.match(routeSrc, /buildTurnCostMetadata\(/);
  assert.ok(!/from '@\/lib\/model-pricing'/.test(routeSrc), "the cache-blind legacy pricing wrapper is not imported");
  // Every call site passes the whole turn (usage, request id, finish) and a ModelRef, never a bare id.
  const sites = routeSrc.match(/extractAndRecordCost\(\w+, \{[^}]*\}/g) ?? [];
  assert.equal(sites.length, 5, "initial, follow-up, budget summary, subagent initial and follow-up");
  for (const site of sites) {
    assert.match(site, /ref: (modelRef|subagentRef)/, site);
    assert.ok(!/\bmodel:/.test(site), site);
  }
});

/** Every `sendEvent('name', { ... })` payload in the route, with nested braces matched. */
function sseBlocks(src) {
  const out = [];
  const re = /sendEvent\('([a-z_]+)', \{/g;
  let m;
  while ((m = re.exec(src))) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < src.length && depth > 0) {
      if (src[i] === "{") depth += 1;
      else if (src[i] === "}") depth -= 1;
      i += 1;
    }
    out.push({ name: m[1], body: src.slice(re.lastIndex, i) });
  }
  return out;
}

test("every SSE event that names a model carries provider and model_ref", () => {
  const blocks = sseBlocks(routeSrc);
  assert.ok(blocks.length > 20, "found the route's events");
  const naming = blocks.filter((b) => /(^|[\s,{])model:/.test(b.body));
  assert.deepEqual([...new Set(naming.map((b) => b.name))].sort(), ["cache_hit", "model", "turn_cost"]);
  for (const b of naming) {
    assert.match(b.body, /provider: modelRef\.provider/, b.name);
    assert.match(b.body, /model_ref: turnModel\.canonical/, b.name);
  }
  const model = blocks.find((b) => b.name === "model");
  assert.match(model.body, /ref: turnModel\.canonical/, "the old `ref` field stays");
  assert.match(blocks.find((b) => b.name === "turn_cost").body, /\.\.\.turnCostSummary\(turnTally\)/);
  // The cache-hit audit row carries them too, and the Gemini-only 0.75 factor is gone.
  const hit = routeSrc.slice(routeSrc.indexOf("safeAudit('chat_cache_hit'"), routeSrc.indexOf("safeAudit('chat_cache_hit'") + 900);
  assert.match(hit, /model_ref: turnModel\.canonical/);
  assert.ok(!/\* ?0\.75/.test(routeSrc), "no fixed savings factor");
});

test("the cost page keeps no provider guesser", () => {
  const page = readFileSync(new URL("../app/observability/cost/page.tsx", import.meta.url), "utf8");
  assert.ok(!/providerFromModel/.test(page));
  assert.ok(!/startsWith\("(gemini|claude|gpt)-/.test(page));
  assert.match(page, /readCostRow\(/);
});

test("the cost page's total card says unpriced for a window with no priced call, never $0", () => {
  const page = readFileSync(new URL("../app/observability/cost/page.tsx", import.meta.url), "utf8");
  assert.match(page, /stats\.unpricedCalls === stats\.calls\s*\?\s*"unpriced"/);
  assert.match(page, /unpriced not included/);
});

test("the events page has chips for turn costs and provider tests", () => {
  const page = readFileSync(new URL("../app/observability/events/page.tsx", import.meta.url), "utf8");
  assert.match(page, /query: "action:chat_turn_cost"/);
  assert.match(page, /query: "action:provider_test"/);
  assert.match(page, /readCostRow\(e\)/);
});

if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall tests passed");
