#!/usr/bin/env node
/**
 * Behaviour test for lib/hooks-backup.ts: what the backup writes for the
 * operator's hooks (Settings -> Hooks), which secret values it strips, and what
 * restore decides to write back. The round-trip tests drive the two pure
 * functions against an in-memory stand-in for the MCP's hook store (list,
 * upsert-by-id, delete), the way app/api/agent/{backup,restore}/route.ts do.
 *
 *   node scripts/test-hooks-backup.mjs   (npm run test:hooks-backup)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { buildHooksSection, planHooksRestore, stripHookSecrets, HOOKS_FILE } =
  await import("../lib/hooks-backup.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

// What the route passes in from the builtin registry.
const secretKeysFor = (name) => (name === "slack-approval" ? ["authHeaderValue"] : []);

const T0 = "2026-10-10T08:00:00Z";
const hook = (over) => ({
  id: "h-1",
  name: "Block prod",
  event: "PreToolUse",
  priority: 50,
  enabled: true,
  matcher: { toolGlob: "caldera_*" },
  transport: { type: "command", command: "/opt/policy.sh" },
  timeoutMs: 5000,
  failurePolicy: "block",
  createdAt: T0,
  updatedAt: T0,
  ...over,
});

/** The MCP's hook store as the routes see it. */
class FakeHookStore {
  constructor(hooks = []) { this.rows = new Map(hooks.map((h) => [h.id, structuredClone(h)])); }
  list() { return { hooks: [...this.rows.values()].map((h) => structuredClone(h)), count: this.rows.size }; }
  upsert(h) { this.rows.set(h.id, structuredClone(h)); }
  delete(id) { this.rows.delete(id); }
  ids() { return [...this.rows.keys()]; }
}

/** One restore as the route performs it: list, plan, POST each. */
function restoreInto(store, fileText, force) {
  const file = JSON.parse(fileText);
  const plan = planHooksRestore(file, store.ids(), force);
  for (const h of plan.posts) store.upsert(h);
  return plan;
}

test("the section file name", () => {
  assert.equal(HOOKS_FILE, "hooks.json");
});

test("the section carries every hook, disabled ones included, with its full definition", () => {
  const listed = { count: 2, hooks: [hook({}), hook({ id: "h-2", name: "Slack", enabled: false })] };
  const s = buildHooksSection(listed, secretKeysFor);
  assert.equal(s.count, 2);
  assert.deepEqual(s.hooks[0], hook({}));
  assert.equal(s.hooks[1].enabled, false);
  assert.deepEqual(s.redacted, {});
});

test("an empty store or a bad response yields an empty section", () => {
  assert.deepEqual(buildHooksSection({ hooks: [], count: 0 }, secretKeysFor), { count: 0, hooks: [], redacted: {} });
  assert.deepEqual(buildHooksSection(null, secretKeysFor), { count: 0, hooks: [], redacted: {} });
  assert.deepEqual(buildHooksSection({ hooks: "x" }, secretKeysFor), { count: 0, hooks: [], redacted: {} });
  assert.equal(buildHooksSection({ hooks: [{ name: "no id" }, "junk"] }, secretKeysFor).count, 0);
});

// ── Secrets ──────────────────────────────────────────────────────────────

test("http headers and command env keep secret: references and lose literal values", () => {
  const http = hook({ transport: { type: "http", url: "https://x.example/h", headers: { Authorization: "Bearer abc123", "X-Ref": "secret:SLACK_TOKEN", "X-Empty": "" } } });
  const r1 = stripHookSecrets(http, secretKeysFor);
  assert.deepEqual(r1.hook.transport.headers, { "X-Ref": "secret:SLACK_TOKEN", "X-Empty": "" });
  assert.deepEqual(r1.redacted, ["transport.headers.Authorization"]);
  assert.equal(r1.hook.transport.url, "https://x.example/h");

  const cmd = hook({ transport: { type: "command", command: "/x.sh", env: { API_TOKEN: "sk-live-1", FROM_ENV: "secret:API_TOKEN" } } });
  const r2 = stripHookSecrets(cmd, secretKeysFor);
  assert.deepEqual(r2.hook.transport.env, { FROM_ENV: "secret:API_TOKEN" });
  assert.deepEqual(r2.redacted, ["transport.env.API_TOKEN"]);
});

test("a builtin loses only the config fields its spec declares secret-ref", () => {
  const b = hook({ transport: { type: "builtin", name: "slack-approval", config: { webhookUrl: "https://r.example/p", authHeaderName: "X-Auth", authHeaderValue: "hunter2" } } });
  const r = stripHookSecrets(b, secretKeysFor);
  assert.deepEqual(r.hook.transport.config, { webhookUrl: "https://r.example/p", authHeaderName: "X-Auth" });
  assert.deepEqual(r.redacted, ["transport.config.authHeaderValue"]);
  const ref = hook({ transport: { type: "builtin", name: "slack-approval", config: { webhookUrl: "https://r.example/p", authHeaderName: "X-Auth", authHeaderValue: "secret:T" } } });
  assert.deepEqual(stripHookSecrets(ref, secretKeysFor).redacted, []);
});

test("a builtin without secret fields is untouched", () => {
  const b = hook({ transport: { type: "builtin", name: "memory-inject", config: { limit: 5 } } });
  const r = stripHookSecrets(b, secretKeysFor);
  assert.deepEqual(r.hook, b);
  assert.deepEqual(r.redacted, []);
});

test("a plugin config loses secret-looking string keys, nested ones included, and keeps the rest", () => {
  const p = hook({ transport: { type: "plugin", handlerName: "h", timeoutS: 5, config: { channel: "#soc", apiToken: "t0k", nested: { password: "pw", note: "keep" }, ref: "secret:X", auth_required: true } } });
  const r = stripHookSecrets(p, secretKeysFor);
  assert.deepEqual(r.hook.transport.config, { channel: "#soc", nested: { note: "keep" }, ref: "secret:X", auth_required: true });
  assert.deepEqual(r.redacted.sort(), ["transport.config.apiToken", "transport.config.nested.password"]);
});

test("stripping does not mutate its input and the zip text never holds the secret", () => {
  const h = hook({ transport: { type: "http", url: "https://x.example", headers: { Authorization: "Bearer topsecret-value" } } });
  const before = JSON.stringify(h);
  const s = buildHooksSection({ hooks: [h] }, secretKeysFor);
  assert.equal(JSON.stringify(h), before);
  assert.ok(!JSON.stringify(s).includes("topsecret-value"));
  assert.deepEqual(s.redacted, { "h-1": ["transport.headers.Authorization"] });
});

// ── Round trip ───────────────────────────────────────────────────────────

test("round trip: create -> backup -> delete -> restore brings the hook back unchanged", () => {
  const source = new FakeHookStore([hook({}), hook({ id: "h-2", name: "Off", enabled: false, event: "RunEnd", transport: { type: "http", url: "https://n.example", headers: { "X-Ref": "secret:N" } } })]);
  const zipText = JSON.stringify(buildHooksSection(source.list(), secretKeysFor), null, 2);

  source.delete("h-1");
  source.delete("h-2");
  assert.deepEqual(source.ids(), []);

  const plan = restoreInto(source, zipText, false);
  assert.deepEqual(source.ids().sort(), ["h-1", "h-2"]);
  assert.deepEqual(source.rows.get("h-1"), hook({}));
  assert.equal(source.rows.get("h-2").enabled, false);
  assert.equal(plan.skipped, 0);
  assert.equal(plan.invalid, 0);
  assert.deepEqual(plan.warnings, []);
});

test("restore into an install that has the same id keeps the destination's hook and counts it skipped", () => {
  const backup = JSON.stringify(buildHooksSection({ hooks: [hook({ name: "From backup" })] }, secretKeysFor));
  const dest = new FakeHookStore([hook({ name: "Edited on destination", priority: 7 })]);
  const plan = restoreInto(dest, backup, false);
  assert.equal(plan.skipped, 1);
  assert.deepEqual(plan.posts, []);
  assert.equal(dest.rows.get("h-1").name, "Edited on destination");
  assert.equal(dest.rows.get("h-1").priority, 7);
});

test("force overwrites a hook the destination already has", () => {
  const backup = JSON.stringify(buildHooksSection({ hooks: [hook({ name: "From backup" })] }, secretKeysFor));
  const dest = new FakeHookStore([hook({ name: "Edited on destination" })]);
  const plan = restoreInto(dest, backup, true);
  assert.equal(plan.skipped, 0);
  assert.equal(dest.rows.get("h-1").name, "From backup");
});

test("a mixed restore writes the missing hooks and skips the present ones", () => {
  const backup = JSON.stringify(buildHooksSection({ hooks: [hook({}), hook({ id: "h-2", name: "B" })] }, secretKeysFor));
  const dest = new FakeHookStore([hook({ name: "Mine" })]);
  const plan = restoreInto(dest, backup, false);
  assert.deepEqual(plan.posts.map((p) => p.id), ["h-2"]);
  assert.equal(plan.skipped, 1);
  assert.deepEqual(dest.ids().sort(), ["h-1", "h-2"]);
});

test("a hook that lost secret values comes back disabled, with a warning that names the fields", () => {
  const src = new FakeHookStore([hook({ failurePolicy: "block", transport: { type: "http", url: "https://x.example", headers: { Authorization: "Bearer s3cr3t" } } })]);
  const zipText = JSON.stringify(buildHooksSection(src.list(), secretKeysFor));
  src.delete("h-1");
  const plan = restoreInto(src, zipText, false);
  assert.equal(src.rows.get("h-1").enabled, false);
  assert.deepEqual(src.rows.get("h-1").transport.headers, {});
  assert.deepEqual(plan.disabledForSecrets, ["h-1"]);
  assert.equal(plan.warnings.length, 1);
  assert.match(plan.warnings[0], /transport\.headers\.Authorization/);
  assert.match(plan.warnings[0], /Settings -> Hooks/);
});

test("under force a hook that lost secrets never replaces the destination's working one", () => {
  const withSecret = hook({ transport: { type: "http", url: "https://x.example", headers: { Authorization: "Bearer real" } } });
  const zipText = JSON.stringify(buildHooksSection({ hooks: [withSecret] }, secretKeysFor));
  const dest = new FakeHookStore([withSecret]);
  const plan = restoreInto(dest, zipText, true);
  assert.equal(plan.skipped, 1);
  assert.deepEqual(plan.posts, []);
  assert.equal(dest.rows.get("h-1").transport.headers.Authorization, "Bearer real");
  assert.match(plan.warnings[0], /even with Overwrite/);
});

test("unusable entries are counted and a repeated id is written once, last one wins", () => {
  const plan = planHooksRestore(
    { hooks: [hook({ name: "first" }), hook({ name: "second" }), { id: "", name: "x" }, { id: "n", name: "no event", transport: { type: "http", url: "u" } }, { id: "t", name: "t", event: "RunEnd" }, "junk"] },
    [],
    false,
  );
  assert.deepEqual(plan.posts.map((p) => p.name), ["second"]);
  assert.equal(plan.invalid, 5);
});

test("a missing or malformed file plans nothing", () => {
  for (const f of [undefined, null, {}, { hooks: "x" }, []]) {
    const plan = planHooksRestore(f, [], false);
    assert.deepEqual(plan.posts, []);
    assert.equal(plan.invalid, 0);
  }
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
