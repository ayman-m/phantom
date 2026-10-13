#!/usr/bin/env node
/**
 * Model pricing and context caps over the registry (lib/providers/registry/pricing.ts,
 * lib/model-pricing.ts, lib/model-context-caps.ts):
 *
 *   - usage normalization per provider (what counts as uncached input),
 *   - the long-context tiers and their boundaries,
 *   - unpriced models (none, expired, unpriceable usage) and the absence of invented rates,
 *   - the catalog's prices against the 2026-10-13 research tables,
 *   - the Gemini cost arithmetic against the table it replaced,
 *   - the context caps chat budgeted with before the registry.
 *
 *   node scripts/test-model-pricing.mjs   (npm run test:model-pricing)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node without
 * it the test skips (the build type-checks the modules).
 */
import assert from "node:assert/strict";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { computeTurnCostUsd, pricingExpired } = await import("../lib/providers/registry/pricing.ts");
const { CURATED_CATALOG, lookupModelFacts, DEFAULT_CONTEXT_CAP, publishModelFacts } = await import(
  "../lib/providers/registry/lookup.ts"
);
const legacy = await import("../lib/model-pricing.ts");
const caps = await import("../lib/model-context-caps.ts");

// The call shape the chat route used to take (a `legacy.computeTurnCostUsd` wrapper that
// hard-coded cacheWrite to 0 and returned usd 0 for an unpriced model) is gone: the route
// builds its audit row from NeutralUsage in lib/cost-rows.ts. These tests price the same
// numbers through the registry function directly.
const priceOf = (model, inp, cached, out) =>
  computeTurnCostUsd(
    { inputTotal: inp, cacheRead: cached, cacheWrite: 0, cacheWrite1h: 0, output: out, reasoning: 0 },
    lookupModelFacts(model) ?? { pricing: null },
    { now: Date.parse("2026-10-13T12:00:00Z") },
  );

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.message).split("\n").join("\n     ")); }
}
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg ?? ""} ${a} != ${b}`);
const usage = (o = {}) => ({ inputTotal: 0, cacheRead: 0, cacheWrite: 0, cacheWrite1h: 0, output: 0, reasoning: 0, ...o });
const entryOf = (model, provider) => {
  const hit = CURATED_CATALOG.find((m) => m.model === model && (!provider || m.provider === provider));
  assert.ok(hit, `no curated entry ${model}`);
  return hit;
};
const NOW = Date.parse("2026-10-13T12:00:00Z");

// ── Normalization ─────────────────────────────────────────────────────────

test("uncached input is inputTotal minus cache reads minus ALL cache writes (pinned)", () => {
  // A Claude call: 100 uncached, 1000 read, 2000 written (500 of them 1-hour).
  const sonnet = entryOf("claude-sonnet-5-5");
  const r = computeTurnCostUsd(usage({ inputTotal: 3100, cacheRead: 1000, cacheWrite: 2000, cacheWrite1h: 500, output: 400 }), sonnet, { now: NOW });
  assert.equal(r.priced, true);
  near(r.components.inputUsd, (100 / 1e6) * 2, "uncached input");
  near(r.components.cacheReadUsd, (1000 / 1e6) * 0.1, "cache read");
  // 1500 five-minute writes at 2.50 and 500 one-hour writes at 4.
  near(r.components.cacheWriteUsd, (1500 / 1e6) * 2.5 + (500 / 1e6) * 4, "cache write");
  near(r.components.outputUsd, (400 / 1e6) * 10, "output");
  near(r.usd, r.components.inputUsd + r.components.cacheReadUsd + r.components.cacheWriteUsd + r.components.outputUsd);
});

test("Gemini usage: the cached count is a subset of the prompt count", () => {
  const pro = entryOf("gemini-3.1-pro-preview");
  const r = computeTurnCostUsd(usage({ inputTotal: 10_000, cacheRead: 4_000, output: 500 }), pro, { now: NOW });
  near(r.components.inputUsd, (6_000 / 1e6) * 2.5);
  near(r.components.cacheReadUsd, (4_000 / 1e6) * 0.625);
  near(r.components.outputUsd, (500 / 1e6) * 12);
});

test("OpenAI usage: cached tokens are a subset, cache writes are billed at 1.25x input", () => {
  const sol = entryOf("gpt-6-sol");
  const r = computeTurnCostUsd(usage({ inputTotal: 5_000, cacheRead: 1_000, cacheWrite: 2_000, output: 100 }), sol, { now: NOW });
  near(r.components.inputUsd, (2_000 / 1e6) * 2);
  near(r.components.cacheReadUsd, (1_000 / 1e6) * 0.2);
  near(r.components.cacheWriteUsd, (2_000 / 1e6) * 2.5);
});

test("a call with no cache activity is plain input plus output", () => {
  const r = computeTurnCostUsd(usage({ inputTotal: 1_000_000, output: 1_000_000 }), entryOf("claude-opus-5-5"), { now: NOW });
  near(r.usd, 4 + 20);
  near(r.components.cachedSavingsUsd, 0);
});

test("savings: reads cut the bill, writes can outweigh them", () => {
  const opus = entryOf("claude-opus-5-5");
  const reading = computeTurnCostUsd(usage({ inputTotal: 100_000, cacheRead: 90_000 }), opus, { now: NOW });
  assert.ok(reading.components.cachedSavingsUsd > 0);
  const writing = computeTurnCostUsd(usage({ inputTotal: 100_000, cacheWrite: 90_000 }), opus, { now: NOW });
  assert.ok(writing.components.cachedSavingsUsd < 0);
});

test("negative or non-finite usage fields are treated as zero", () => {
  const r = computeTurnCostUsd(usage({ inputTotal: 1000, cacheRead: -5, output: NaN }), entryOf("claude-opus-5-5"), { now: NOW });
  assert.equal(r.priced, true);
  near(r.usd, (1000 / 1e6) * 4);
});

// ── Long-context tiers ────────────────────────────────────────────────────

test("Haiku 5.5: a prompt over 100,000 tokens pays 5x on every rate (boundary is strict)", () => {
  const haiku = entryOf("claude-haiku-5-5");
  const at = computeTurnCostUsd(usage({ inputTotal: 100_000, output: 1000 }), haiku, { now: NOW });
  const over = computeTurnCostUsd(usage({ inputTotal: 100_001, output: 1000 }), haiku, { now: NOW });
  assert.equal(at.longContext, false);
  assert.equal(over.longContext, true);
  near(at.components.inputUsd, (100_000 / 1e6) * 0.1);
  near(over.components.inputUsd, (100_001 / 1e6) * 0.5);
  near(over.components.outputUsd, (1000 / 1e6) * 2.5);
});

test("Haiku 5.5 long context applies to cache reads and writes too", () => {
  const haiku = entryOf("claude-haiku-5-5");
  const r = computeTurnCostUsd(usage({ inputTotal: 200_000, cacheRead: 150_000, cacheWrite: 40_000, cacheWrite1h: 10_000 }), haiku, { now: NOW });
  near(r.components.cacheReadUsd, (150_000 / 1e6) * 0.05);
  near(r.components.cacheWriteUsd, (30_000 / 1e6) * 0.625 + (10_000 / 1e6) * 1);
  near(r.components.inputUsd, (10_000 / 1e6) * 0.5);
});

test("gpt-6-astra and gpt-6-luna: over 272,000 prompt tokens, 2x input and cache, 1.5x output", () => {
  for (const [model, input, output] of [["gpt-6-astra", 10, 50], ["gpt-6-luna", 0.1, 0.5]]) {
    const e = entryOf(model);
    const at = computeTurnCostUsd(usage({ inputTotal: 272_000, cacheRead: 100_000, output: 10_000 }), e, { now: NOW });
    const over = computeTurnCostUsd(usage({ inputTotal: 272_001, cacheRead: 100_000, output: 10_000 }), e, { now: NOW });
    assert.equal(at.longContext, false, model);
    assert.equal(over.longContext, true, model);
    near(over.components.inputUsd, (172_001 / 1e6) * input * 2, model);
    near(over.components.cacheReadUsd, (100_000 / 1e6) * e.pricing.cacheReadPerM * 2, model);
    near(over.components.outputUsd, (10_000 / 1e6) * output * 1.5, model);
  }
});

test("models without a long-context tier are flat at any size", () => {
  const r = computeTurnCostUsd(usage({ inputTotal: 900_000 }), entryOf("claude-opus-5-5"), { now: NOW });
  assert.equal(r.longContext, false);
  near(r.usd, (900_000 / 1e6) * 4);
});

// ── Unpriced ──────────────────────────────────────────────────────────────

test("a model with no price returns no dollar figure", () => {
  const r = computeTurnCostUsd(usage({ inputTotal: 1000, output: 1000 }), entryOf("gemini-3.7-flash"), { now: NOW });
  assert.deepEqual({ priced: r.priced, usd: r.usd, components: r.components }, { priced: false, usd: null, components: null });
  assert.equal(r.reason, "no_pricing");
});

test("promotional pricing is priced through its end date and unpriced the day after", () => {
  const sol = entryOf("gpt-5.6-sol");
  assert.equal(sol.pricingValidUntil, "2026-11-21");
  const usageOne = usage({ inputTotal: 1000, output: 1000 });
  assert.equal(computeTurnCostUsd(usageOne, sol, { now: Date.parse("2026-11-21T23:59:59Z") }).priced, true);
  const after = computeTurnCostUsd(usageOne, sol, { now: Date.parse("2026-11-22T00:00:00Z") });
  assert.equal(after.priced, false);
  assert.equal(after.reason, "pricing_expired");
  assert.equal(pricingExpired({ pricing: sol.pricing }, Date.parse("2030-01-01")), false, "no end date never expires");
});

test("1-hour cache writes with no 1-hour price are unpriceable, not guessed", () => {
  const sol = entryOf("gpt-6-sol");
  assert.equal(sol.pricing.cacheWrite1hPerM, undefined);
  const r = computeTurnCostUsd(usage({ inputTotal: 2000, cacheWrite: 1000, cacheWrite1h: 1000 }), sol, { now: NOW });
  assert.equal(r.priced, false);
  assert.equal(r.reason, "unpriceable_usage");
});

test("a Gemini call that reports a cache write has no write price and is unpriceable", () => {
  const r = computeTurnCostUsd(usage({ inputTotal: 2000, cacheWrite: 500 }), entryOf("gemini-2.5-pro"), { now: NOW });
  assert.equal(r.priced, false);
});

// ── Catalog prices against the research ───────────────────────────────────

test("Anthropic prices match the 2026-10-13 research table", () => {
  const rows = {
    // model: [input, 5m write, 1h write, read, output]
    "claude-fable-5-1": [10, 12.5, 20, 0.25, 50],
    "claude-opus-5-5": [4, 5, 8, 0.2, 20],
    "claude-sonnet-5-5": [2, 2.5, 4, 0.1, 10],
    "claude-haiku-5-5": [0.1, 0.125, 0.2, 0.01, 0.5],
    "claude-opus-5": [5, 6.25, 10, 0.5, 25],
    "claude-sonnet-5": [2, 2.5, 4, 0.2, 10],
  };
  for (const [model, [i, w5, w1, r, o]] of Object.entries(rows)) {
    const p = entryOf(model, "anthropic").pricing;
    assert.deepEqual(
      [p.inputPerM, p.cacheWrite5mPerM, p.cacheWrite1hPerM, p.cacheReadPerM, p.outputPerM],
      [i, w5, w1, r, o],
      model,
    );
    assert.equal(entryOf(model, "anthropic").pricingVerified, "2026-10-13", model);
  }
});

test("OpenAI prices match the 2026-10-13 research table", () => {
  const rows = {
    // model: [input, cached, output, cache write]
    "gpt-6-astra": [10, 1, 50, 12.5],
    "gpt-6.1-sol": [2, 0.1, 10, 2.5],
    "gpt-6-sol": [2, 0.2, 10, 2.5],
    "gpt-6-luna": [0.1, 0.01, 0.5, 0.125],
    "gpt-5.6-sol": [4, 0.4, 20, 5],
    "gpt-5.6-terra": [2, 0.2, 12, 2.5],
    "gpt-5.6-luna": [0.2, 0.02, 1.2, 0.25],
  };
  for (const [model, [i, c, o, w]] of Object.entries(rows)) {
    const e = entryOf(model, "openai");
    const p = e.pricing;
    assert.deepEqual([p.inputPerM, p.cacheReadPerM, p.outputPerM, p.cacheWrite5mPerM], [i, c, o, w], model);
    assert.equal(e.pricingVerified, "2026-10-13", model);
  }
});

test("no catalog row carries an invented price: a null price has a null verification date", () => {
  for (const m of CURATED_CATALOG) {
    if (m.pricing === null) assert.equal(m.pricingVerified, null, m.model);
    else assert.ok(m.pricingVerified, `${m.model} has a price but no verification date`);
  }
});

// ── Gemini equals the table it replaced ───────────────────────────────────

const OLD_TABLE = {
  "gemini-3.1-pro-preview": { inputPerM: 2.5, cachedInputPerM: 0.625, outputPerM: 12.0 },
  "gemini-3.0-pro": { inputPerM: 2.0, cachedInputPerM: 0.5, outputPerM: 10.0 },
  "gemini-2.5-pro": { inputPerM: 1.25, cachedInputPerM: 0.3125, outputPerM: 5.0 },
  "gemini-2.5-flash": { inputPerM: 0.075, cachedInputPerM: 0.01875, outputPerM: 0.3 },
  "gemini-2.5-flash-lite": { inputPerM: 0.0375, cachedInputPerM: 0.009375, outputPerM: 0.15 },
};
function oldCompute(pricing, inputTokens, cachedInputTokens, outputTokens) {
  const cached = Math.max(0, cachedInputTokens);
  const uncached = Math.max(0, inputTokens - cached);
  const inputUsd = (uncached / 1_000_000) * pricing.inputPerM;
  const cachedInputUsd = (cached / 1_000_000) * pricing.cachedInputPerM;
  const outputUsd = (outputTokens / 1_000_000) * pricing.outputPerM;
  return { usd: inputUsd + cachedInputUsd + outputUsd, inputUsd, cachedInputUsd, outputUsd, hypo: ((uncached + cached) / 1_000_000) * pricing.inputPerM };
}

test("the five priced Gemini models cost exactly what the old table computed", () => {
  const cases = [[10_000, 0, 500], [250_000, 100_000, 8_000], [1_000, 1_000, 0], [0, 0, 0], [600_000, 599_999, 65_536]];
  for (const [model, pricing] of Object.entries(OLD_TABLE)) {
    for (const [inp, cached, out] of cases) {
      const want = oldCompute(pricing, inp, cached, out);
      const got = priceOf(model, inp, cached, out);
      assert.equal(got.priced, true, model);
      assert.equal(got.usd, want.usd, `${model} usd for ${inp}/${cached}/${out}`);
      assert.equal(got.components.inputUsd, want.inputUsd, model);
      assert.equal(got.components.cacheReadUsd, want.cachedInputUsd, model);
      assert.equal(got.components.outputUsd, want.outputUsd, model);
      assert.equal(got.components.uncachedHypotheticalInputUsd, want.hypo, model);
    }
  }
});

test("a provider prefix does not change the price", () => {
  const a = priceOf("vertex/gemini-2.5-pro", 5000, 1000, 100);
  const b = priceOf("gemini-2.5-pro", 5000, 1000, 100);
  assert.equal(a.usd, b.usd);
});

test("a model with no price (gemini-3.7-flash was on the old fallback rate) is unpriced, not estimated", () => {
  const r = priceOf("gemini-3.7-flash", 100_000, 0, 5000);
  assert.equal(r.priced, false);
  assert.equal(r.usd, null, "unpriced is null, never 0");
  assert.equal(r.components, null);
});

test("an unknown model is unpriced; resolveModelPricing says so", () => {
  const r = priceOf("not-a-model", 100_000, 0, 5000);
  assert.equal(r.priced, false);
  assert.equal(r.usd, null);
  assert.equal(legacy.resolveModelPricing("not-a-model"), null);
  assert.equal(legacy.resolveModelPricing(""), null);
  assert.deepEqual(legacy.resolveModelPricing("gemini-2.5-pro"), entryOf("gemini-2.5-pro").pricing);
});

test("the old table, the fallback, the prefix matcher and the cache-blind wrapper are gone", () => {
  assert.equal(legacy.computeTurnCostUsd, undefined);
  assert.equal(legacy.MODEL_PRICING_TABLE, undefined);
  assert.equal(legacy.FALLBACK_PRICING, undefined);
  assert.equal(legacy.resolveModelPricing("gemini-2.5-pro-preview-0514"), null, "no prefix matching");
});

test("formatUsd is unchanged", () => {
  assert.equal(legacy.formatUsd(0), "$0");
  assert.equal(legacy.formatUsd(0.0004), "$0.00040");
  assert.equal(legacy.formatUsd(0.0042), "$0.0042");
  assert.equal(legacy.formatUsd(0.42), "$0.420");
  assert.equal(legacy.formatUsd(4.2), "$4.20");
});

// ── Context caps ──────────────────────────────────────────────────────────

test("caps equal the values chat budgeted with before the registry", () => {
  const before = {
    "gemini-3.7-flash": 1_000_000,
    "gemini-3.5-flash": 1_000_000,
    "gemini-3.1-pro-preview": 1_000_000,
    "gemini-3.0-pro": 1_000_000,
    "gemini-2.5-pro": 2_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.5-flash-lite": 1_000_000,
  };
  for (const [model, cap] of Object.entries(before)) assert.equal(caps.resolveContextCap(model), cap, model);
});

test("provider prefixes and case do not matter", () => {
  assert.equal(caps.resolveContextCap("vertex/gemini-2.5-pro"), 2_000_000);
  assert.equal(caps.resolveContextCap("Vertex/Gemini-2.5-Pro"), 2_000_000);
  assert.equal(caps.resolveContextCap("models/gemini-2.5-pro"), 2_000_000);
});

test("an unknown model, an unstated window and empty input all get the single documented default", () => {
  assert.equal(DEFAULT_CONTEXT_CAP, 200_000);
  for (const input of ["not-a-model", "", undefined, "gpt-6-unlisted", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-3-pro-preview", "gpt-5.6-terra"]) {
    assert.equal(caps.resolveContextCap(input), 200_000, String(input));
  }
});

test("a deprecated model keeps its cap and its price", () => {
  const e = entryOf("gemini-2.5-pro");
  assert.equal(e.lifecycle.stage, "deprecated");
  assert.equal(caps.resolveContextCap("gemini-2.5-pro"), 2_000_000);
  assert.ok(legacy.resolveModelPricing("gemini-2.5-pro"));
});

test("Claude and OpenAI caps come from their catalogs", () => {
  assert.equal(caps.resolveContextCap("claude-opus-5-5"), 1_000_000);
  assert.equal(caps.resolveContextCap("anthropic/claude-haiku-5-5"), 1_000_000);
  assert.equal(caps.resolveContextCap("gpt-6-sol"), 1_050_000);
});

test("input budget for Gemini is unchanged: (cap - reserved) * 0.7", () => {
  assert.equal(caps.DEFAULT_RESERVED_OUTPUT_TOKENS, 65_536);
  assert.equal(caps.computeInputBudget("gemini-3.1-pro-preview"), Math.floor((1_000_000 - 65_536) * 0.7));
  assert.equal(caps.computeInputBudget("gemini-2.5-pro"), Math.floor((2_000_000 - 65_536) * 0.7));
  assert.equal(caps.computeInputBudget("unknown-model"), Math.floor((200_000 - 65_536) * 0.7));
  assert.equal(caps.computeInputBudget("gemini-3.1-pro-preview", 1_000_000 - 100), 8_000, "floor at 8k");
});

test("the tokenizer factor shrinks the budget for the newer Claude tokenizer", () => {
  assert.equal(caps.resolveTokenizerFactor("claude-opus-5-5"), 1.3);
  assert.equal(caps.resolveTokenizerFactor("gemini-2.5-pro"), 1);
  assert.equal(caps.resolveTokenizerFactor("nope"), 1);
  assert.equal(caps.computeInputBudget("claude-opus-5-5"), Math.floor(((1_000_000 - 65_536) * 0.7) / 1.3));
});

test("a provider prompt cap below the window bounds the budget", () => {
  assert.equal(entryOf("gpt-6-astra").maxInput, 922_000);
  assert.equal(caps.computeInputBudget("gpt-6-astra"), Math.floor(Math.min(1_050_000 - 65_536, 922_000) * 0.7));
});

test("a published live window wins over the curated one for the sync lookups", () => {
  const e = entryOf("gemini-3.7-flash");
  publishModelFacts([{ ...e, contextWindow: 1_048_576 }]);
  try {
    assert.equal(caps.resolveContextCap("gemini-3.7-flash"), 1_048_576);
    assert.equal(lookupModelFacts("claude-opus-5-5")?.provider, "anthropic", "curated fills in what was not published");
  } finally {
    publishModelFacts([]);
  }
  assert.equal(caps.resolveContextCap("gemini-3.7-flash"), 1_000_000);
});

if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall tests passed");
