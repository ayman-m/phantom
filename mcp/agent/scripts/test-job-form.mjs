#!/usr/bin/env node
/**
 * Behaviour test for lib/job-form.ts (the /jobs/new form's cron helpers, the
 * stored-job -> form-values mapping behind Duplicate, the "(copy)" name and
 * the Create-enabled rule) and lib/model-catalog.ts (the registry both the
 * /models page and the job form's Model dropdown read).
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the modules).
 *
 *   node scripts/test-job-form.mjs   (npm run test:job-form)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const {
  buildCron,
  buildIntervalCron,
  canSubmitJobForm,
  defaultOnceAt,
  jobToFormValues,
  parseCronSchedule,
  uniqueCopyName,
} = await import("../lib/job-form.ts");
const { parseModelCatalog, selectableChatModels, lifecycleBadge, providerName, compareProviders, refForStoredModel } = await import("../lib/model-catalog.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

// Local-time "now" so the date math matches what the browser form does.
const NOW = new Date(2026, 9, 12, 10, 0, 0, 0);

/** The submit input the page derives from form values. */
function submitInput(v) {
  return {
    name: v.name,
    actionType: v.actionType,
    toolName: v.toolName,
    promptMessage: v.promptMessage,
    mode: v.schedule.mode,
    intervalN: v.schedule.intervalN,
    intervalUnit: v.schedule.intervalUnit,
    customCron: v.schedule.customCron,
    onceAt: v.schedule.onceAt ?? defaultOnceAt(NOW),
  };
}

const promptJob = {
  name: "nightly-summary",
  schedule: "*/15 * * * *",
  timezone: "Asia/Riyadh",
  state: "JOB_STATE_ACTIVE",
  run_once: false,
  bypass_approvals: true,
  action: { type: "prompt", message: "Summarise the alert backlog.", skill: "triage" },
  model_id: "gemini-3.5-flash",
  thinking_enabled: true,
  permission_policy: {
    allowed_tools: ["phantom_*", "xlog.*"],
    denied_tools: ["*_delete"],
    // A key from an older build: stored with the job but not part of the form any more.
    require_approval: ["xsiam_alerts_update"],
  },
  description: "Daily backlog digest",
};

const toolJob = {
  name: "hourly-firewall",
  schedule: "0 */2 * * *",
  timezone: "UTC",
  state: "JOB_STATE_ACTIVE",
  run_once: false,
  bypass_approvals: false,
  action: {
    type: "tool_call",
    name: "phantom_create_data_worker",
    args: { request: { vendor: "Fortinet", product: "FortiGate", count: 50 } },
  },
  model_id: null,
  thinking_enabled: false,
  permission_policy: null,
};

// ── Duplicate: prompt job ───────────────────────────────────────────────

test("a duplicated prompt job carries its prompt, skill, model, flags and policy", () => {
  const v = jobToFormValues(promptJob, NOW);
  assert.equal(v.actionType, "prompt");
  assert.equal(v.promptMessage, "Summarise the alert backlog.");
  assert.equal(v.skillBinding, "triage");
  assert.equal(v.modelId, "gemini-3.5-flash");
  assert.equal(v.thinkingEnabled, true);
  assert.equal(v.bypassApprovals, true);
  assert.equal(v.enabled, true);
  assert.equal(v.timezone, "Asia/Riyadh");
  assert.equal(v.description, "Daily backlog digest");
  assert.equal(v.allowedTools, "phantom_*, xlog.*");
  assert.equal(v.deniedTools, "*_delete");
  assert.equal("requireApproval" in v, false);
});

test("a job stored before descriptions existed duplicates with an empty description", () => {
  assert.equal(jobToFormValues(toolJob, NOW).description, "");
  assert.equal(jobToFormValues({ ...toolJob, description: null }, NOW).description, "");
  assert.equal(jobToFormValues({ ...toolJob, description: "" }, NOW).description, "");
});

test("Create is enabled for a duplicated prompt job once it has a name", () => {
  const v = { ...jobToFormValues(promptJob, NOW), name: uniqueCopyName(promptJob.name, []) };
  assert.equal(canSubmitJobForm(submitInput(v), NOW), true);
});

test("a prompt duplicate with an empty prompt keeps Create disabled", () => {
  const v = { ...jobToFormValues({ ...promptJob, action: { type: "prompt", message: "" } }, NOW), name: "x (copy)" };
  assert.equal(canSubmitJobForm(submitInput(v), NOW), false);
});

// ── Duplicate: tool_call job ────────────────────────────────────────────

test("a duplicated tool_call job carries the tool name and its arguments JSON", () => {
  const v = jobToFormValues(toolJob, NOW);
  assert.equal(v.actionType, "tool_call");
  assert.equal(v.toolName, "phantom_create_data_worker");
  assert.deepEqual(JSON.parse(v.toolArgsJson), toolJob.action.args);
  assert.equal(v.modelId, "");
  assert.equal(v.allowedTools, "");
});

test("Create is enabled for a duplicated tool_call job", () => {
  const v = { ...jobToFormValues(toolJob, NOW), name: uniqueCopyName(toolJob.name, []) };
  assert.equal(canSubmitJobForm(submitInput(v), NOW), true);
});

test("a tool_call without args duplicates with an empty JSON object", () => {
  const v = jobToFormValues({ ...toolJob, action: { type: "tool_call", name: "t" } }, NOW);
  assert.equal(v.toolArgsJson, "{}");
});

test("a legacy chat action opens as a prompt", () => {
  const v = jobToFormValues({ ...promptJob, action: { type: "chat", message: "hello" } }, NOW);
  assert.equal(v.actionType, "prompt");
  assert.equal(v.promptMessage, "hello");
});

// ── Schedule kind ───────────────────────────────────────────────────────

test("repeating cron shapes map back to Repeating with the same N and unit", () => {
  for (const [n, unit] of [[15, "minutes"], [2, "hours"], [3, "days"], [1, "minutes"]]) {
    const p = parseCronSchedule(buildIntervalCron(n, unit), false, NOW);
    assert.equal(p.mode, "repeating");
    assert.equal(p.intervalN, n);
    assert.equal(p.intervalUnit, unit);
    assert.equal(buildCron(p.mode, p.intervalN, p.intervalUnit, p.customCron, NOW, NOW), buildIntervalCron(n, unit));
  }
});

test("any other cron stays Custom with the raw expression (not 'weekly')", () => {
  const p = parseCronSchedule("0 9 * * 1-5", false, NOW);
  assert.equal(p.mode, "custom");
  assert.equal(p.customCron, "0 9 * * 1-5");
  assert.equal(p.onceAt, null);
});

test("an out-of-range step is Custom, not Repeating", () => {
  assert.equal(parseCronSchedule("*/75 * * * *", false, NOW).mode, "custom");
  assert.equal(parseCronSchedule("0 */30 * * *", false, NOW).mode, "custom");
});

test("a run-once job with a future date duplicates as Run at that moment", () => {
  const p = parseCronSchedule("30 14 20 11 *", true, NOW);
  assert.equal(p.mode, "once");
  assert.equal(p.onceAt.getTime(), new Date(2026, 10, 20, 14, 30).getTime());
});

test("a run-once job whose date has passed falls back to one hour ahead, so Create stays enabled", () => {
  // A 'Run now' original always has a past date by the time it is duplicated.
  const past = "5 9 12 10 *";
  const v = { ...jobToFormValues({ ...toolJob, schedule: past, run_once: true }, NOW), name: "x (copy)" };
  assert.equal(v.schedule.mode, "once");
  assert.equal(v.schedule.onceAt.getTime(), defaultOnceAt(NOW).getTime());
  assert.equal(canSubmitJobForm(submitInput(v), NOW), true);
});

// ── Enabled flag ────────────────────────────────────────────────────────

test("an operator-paused job duplicates disabled", () => {
  assert.equal(jobToFormValues({ ...promptJob, state: "JOB_STATE_PAUSED" }, NOW).enabled, false);
});

test("a completed run-once job duplicates enabled (it is disabled only because it fired)", () => {
  const v = jobToFormValues({ ...promptJob, state: "JOB_STATE_COMPLETED", run_once: true, schedule: "5 9 12 10 *" }, NOW);
  assert.equal(v.enabled, true);
});

// ── Copy name ───────────────────────────────────────────────────────────

test("the copy name is '<name> (copy)' when free", () => {
  assert.equal(uniqueCopyName("job", ["other"]), "job (copy)");
});

test("the copy name skips taken suffixes", () => {
  assert.equal(uniqueCopyName("job", ["job (copy)"]), "job (copy 2)");
  assert.equal(uniqueCopyName("job", ["job (copy)", "job (copy 2)", "job (copy 3)"]), "job (copy 4)");
});

// ── Submit rule ─────────────────────────────────────────────────────────

test("Run at in the past or under a minute away disables Create", () => {
  const base = { ...submitInput({ ...jobToFormValues(promptJob, NOW), name: "n" }), mode: "once" };
  assert.equal(canSubmitJobForm({ ...base, onceAt: new Date(NOW.getTime() - 1000) }, NOW), false);
  assert.equal(canSubmitJobForm({ ...base, onceAt: new Date(NOW.getTime() + 30_000) }, NOW), false);
  assert.equal(canSubmitJobForm({ ...base, onceAt: new Date(NOW.getTime() + 120_000) }, NOW), true);
});

test("an empty name or an out-of-range interval disables Create", () => {
  const ok = submitInput({ ...jobToFormValues(promptJob, NOW), name: "n" });
  assert.equal(canSubmitJobForm({ ...ok, name: "  " }, NOW), false);
  assert.equal(canSubmitJobForm({ ...ok, mode: "repeating", intervalN: 90, intervalUnit: "minutes" }, NOW), false);
});

// ── Model registry ──────────────────────────────────────────────────────

// Mirrors /api/agent/models for a Vertex-only install: 7 chat, 2 embedding,
// 2 image, 1 voice = 12 models on /models. Every chat model the registry
// marks selectable carries `selectable: true`; the others do not.
const registry = [
  ...["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-3.0-pro",
      "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    .map((model) => ({ provider: "vertex", model, ref: `vertex/${model}`, kind: "chat", supportsThinking: true, selectable: true, availability: "available" })),
  { provider: "vertex", model: "gemini-embedding-001", kind: "embedding", selectable: false },
  { provider: "vertex", model: "text-embedding-005", kind: "embedding", selectable: false },
  { provider: "vertex", model: "imagen-4.0-generate-preview", kind: "image", selectable: false },
  { provider: "vertex", model: "imagen-3.0-generate-002", kind: "image", selectable: false },
  { provider: "vertex", model: "chirp-3-hd", kind: "voice", selectable: false },
];

test("the route's bare array parses as the registry (the job form once read .models and saw nothing)", () => {
  assert.equal(parseModelCatalog(registry).length, 12);
});

test("an object payload is a contract break, not an empty registry", () => {
  assert.throws(() => parseModelCatalog({ models: registry }), /unexpected payload/);
  assert.throws(() => parseModelCatalog(null), /unexpected payload/);
});

test("the picker lists the 7 chat models and nothing else", () => {
  const picked = selectableChatModels(parseModelCatalog(registry));
  assert.equal(picked.length, 7);
  assert.ok(picked.every((m) => m.kind === "chat"));
});

test("only models the registry marks selectable are offered; an entry without the flag is not", () => {
  const picked = selectableChatModels([
    { provider: "anthropic", model: "claude-x", kind: "chat", selectable: false, availability: "not_configured" },
    { provider: "openai", model: "gpt-x", kind: "chat", selectable: false, availability: "unavailable" },
    { provider: "vertex", model: "no-flag", kind: "chat" },
    { provider: "vertex", model: "ok", kind: "chat", selectable: true },
    { provider: "vertex", model: "no-kind", selectable: true },
  ]);
  assert.deepEqual(picked.map((m) => m.model), ["ok", "no-kind"]);
});

test("a deprecated model is still offered, with a badge", () => {
  const dep = { provider: "vertex", model: "gemini-2.5-pro", kind: "chat", selectable: true, availability: "deprecated" };
  assert.deepEqual(selectableChatModels([dep]), [dep]);
  assert.equal(lifecycleBadge(dep), "deprecated");
  assert.equal(lifecycleBadge({ ...dep, availability: "available" }), "");
});

test("providers are named and ordered for the pickers", () => {
  assert.equal(providerName("vertex"), "Google Gemini");
  assert.equal(providerName("openai"), "OpenAI");
  assert.equal(providerName("mystery"), "mystery");
  assert.deepEqual(["openai", "mystery", "vertex", "anthropic"].sort(compareProviders), ["vertex", "anthropic", "openai", "mystery"]);
});

test("a stored bare model id shows as the canonical ref it resolves to; a ref stays itself", () => {
  const picked = selectableChatModels(parseModelCatalog(registry));
  assert.equal(refForStoredModel(picked, "gemini-3.5-flash"), "vertex/gemini-3.5-flash");
  assert.equal(refForStoredModel(picked, "Gemini-3.5-Flash"), "vertex/gemini-3.5-flash");
  assert.equal(refForStoredModel(picked, "vertex/gemini-3.5-flash"), "vertex/gemini-3.5-flash");
});

test("an unknown, retired or ambiguous stored model is left as written, never guessed", () => {
  const picked = selectableChatModels(parseModelCatalog(registry));
  assert.equal(refForStoredModel(picked, "gemini-9"), null);
  assert.equal(refForStoredModel(picked, "openai/gemini-3.5-flash"), null);
  assert.equal(refForStoredModel(picked, ""), null);
  const twin = [
    { provider: "vertex", model: "claude-x", ref: "vertex/claude-x" },
    { provider: "anthropic", model: "claude-x", ref: "anthropic/claude-x" },
  ];
  assert.equal(refForStoredModel(twin, "claude-x"), null);
  assert.equal(refForStoredModel(twin, "anthropic/claude-x"), "anthropic/claude-x");
});

test("a truly empty registry selects nothing", () => {
  assert.deepEqual(selectableChatModels(parseModelCatalog([])), []);
});

if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall tests passed");
