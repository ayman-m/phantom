#!/usr/bin/env node
/**
 * GET/PUT /api/agent/providers/config: runs the real route handler against
 * stubbed Next, MCP-proxy and DNS modules and a fake MCP provider store, and
 * asserts:
 *
 *   - the OpenAI card's fields (key, organization, project, base URL) are
 *     stored on a "primary-openai" instance and read back redacted;
 *   - the key-exfiltration rule, for EVERY provider with a base URL: a saved
 *     key is never kept when the base URL changes unless the key is typed again
 *     in the same request. "***" (the redaction sentinel) is not a typed key;
 *     clearing a gateway URL back to the default is a change too; the same URL
 *     spelled differently is not;
 *   - a refused save writes nothing to the store;
 *   - an unsafe base URL and a malformed organization/project are refused;
 *   - saving one provider never touches another's instance.
 *
 *   node scripts/test-providers-config-route.mjs   (npm run test:providers-config-route)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the route).
 */
import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as nodeModule from "node:module";

if (!process.features.typescript || typeof nodeModule.stripTypeScriptTypes !== "function" || typeof nodeModule.registerHooks !== "function") {
  console.log("skip: this Node lacks type stripping or module hooks");
  process.exit(0);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dataModule = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

const STUBS = {
  "next/server": dataModule(`
    export class NextResponse extends Response {
      static json(body, init) { return new NextResponse(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } }); }
    }`),
  "@/lib/mcp-proxy": dataModule(`export async function resolveMcp() { return { base: 'http://localhost:8080', token: 'tok-fake' }; }`),
  "@/lib/vertex-credentials": dataModule(`export function bustVertexCredsCache() {}`),
  "node:dns/promises": dataModule(`export async function lookup(host) { return [{ address: '203.0.113.10', family: 4 }]; }`),
};

nodeModule.registerHooks({
  resolve(specifier, context, nextResolve) {
    if (STUBS[specifier]) return { url: STUBS[specifier], shortCircuit: true };
    if (specifier.startsWith("@/")) {
      const rel = specifier.slice(2);
      const file = /\.[cm]?[jt]sx?$/.test(rel) ? rel : `${rel}.ts`;
      return { url: pathToFileURL(join(root, file)).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

process.env.MCP_URL = "http://localhost:8080/api/v1/stream/mcp";
const route = await import("../app/api/agent/providers/config/route.ts");

let failed = 0;
const queue = [];
const test = (name, fn) => queue.push({ name, fn });

// Credential-shaped values are assembled at run time so no secret scanner
// mistakes the source for a real key.
const K_SAVED = ["sk", "proj", "SAVED" + "x".repeat(16)].join("-");
const K_NEW = ["sk", "proj", "FRESH" + "y".repeat(16)].join("-");
const K_ANT = ["sk", "ant", "SAVED" + "x".repeat(12)].join("-");

/**
 * A fake MCP provider store. `instances` seeds it; every write is recorded in
 * `writes`. The list endpoint returns secrets redacted, as the real one does.
 */
function installStore(instances = []) {
  const store = new Map(instances.map((i) => [i.id, structuredClone(i)]));
  const writes = [];
  let next = 1;
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    const method = init.method ?? "GET";
    if (u.pathname === "/api/v1/providers" && method === "GET") {
      const wanted = u.searchParams.get("provider_id");
      const list = [...store.values()].filter((i) => !wanted || i.provider_id === wanted);
      return json({ instances: list.map((i) => ({ ...i, secrets: Object.fromEntries(Object.keys(i.secrets).map((k) => [k, "***"])) })) });
    }
    if (u.pathname === "/api/v1/providers" && method === "POST") {
      const body = JSON.parse(init.body);
      writes.push({ method, body });
      const instance = { id: `new-${next++}`, ...body, created_at: "2026-10-13T00:00:00Z" };
      store.set(instance.id, instance);
      return json({ instance }, 201);
    }
    const m = u.pathname.match(/^\/api\/v1\/providers\/([^/]+)$/);
    if (m && method === "PUT") {
      const body = JSON.parse(init.body);
      writes.push({ method, id: m[1], body });
      const cur = store.get(m[1]);
      if (!cur) return json({ error: "not found" }, 404);
      store.set(m[1], { ...cur, config: body.config ?? cur.config, secrets: { ...cur.secrets, ...(body.secrets ?? {}) } });
      return json({ instance: store.get(m[1]) });
    }
    return json({ error: "unexpected " + method + " " + u.pathname }, 500);
  };
  return { store, writes };
}

const OPENAI = (over = {}) => ({ id: "oa-1", provider_id: "openai", name: "primary-openai", config: {}, secrets: { api_key: K_SAVED }, created_at: "2026-10-13T00:00:00Z", ...over });
const ANTHROPIC = (over = {}) => ({ id: "an-1", provider_id: "anthropic", name: "primary-anthropic", config: {}, secrets: { api_key: K_ANT }, created_at: "2026-10-13T00:00:00Z", ...over });

async function put(value) {
  const res = await route.PUT(new Request("http://localhost/api/agent/providers/config", { method: "PUT", body: JSON.stringify({ value }) }));
  return { status: res.status, body: await res.json() };
}
async function get() {
  const res = await route.GET();
  return await res.json();
}

/* ─── GET ──────────────────────────────────────────────────── */

test("GET reports OpenAI as configured with the key redacted and its organization, project and base URL", async () => {
  installStore([OPENAI({ config: { organization: "org-abc", project: "proj_def", base_url: "https://gw.example.com/v1" } })]);
  const { providers, configured } = await get();
  assert.equal(providers.openaiApiKey, "***");
  assert.equal(providers.openaiOrganization, "org-abc");
  assert.equal(providers.openaiProject, "proj_def");
  assert.equal(providers.openaiBaseUrl, "https://gw.example.com/v1");
  assert.deepEqual(Object.keys(configured).sort(), ["openaiApiKey", "openaiBaseUrl", "openaiOrganization", "openaiProject"]);
  assert.ok(!JSON.stringify({ providers, configured }).includes(K_SAVED), "the key never leaves the server");
});

test("GET with nothing stored reports nothing configured", async () => {
  installStore([]);
  const { providers, configured } = await get();
  assert.deepEqual(providers, {});
  assert.deepEqual(configured, {});
});

/* ─── OpenAI save ──────────────────────────────────────────── */

test("a first save creates the primary-openai instance with the key as a secret and the rest as config", async () => {
  const s = installStore([]);
  const r = await put({ openaiApiKey: K_NEW, openaiOrganization: " org-abc ", openaiProject: "proj_def", openaiBaseUrl: "" });
  assert.equal(r.status, 200);
  assert.equal(s.writes.length, 1);
  assert.equal(s.writes[0].method, "POST");
  assert.deepEqual(s.writes[0].body, {
    provider_id: "openai",
    name: "primary-openai",
    config: { base_url: "", organization: "org-abc", project: "proj_def" },
    secrets: { api_key: K_NEW },
  });
  assert.equal(r.body.mcp_sync.openai.action, "create");
  assert.equal(r.body.mcp_sync.anthropic.action, "skipped");
  assert.ok(!JSON.stringify(r.body).includes(K_NEW));
});

test("a first save with no key is refused and writes nothing", async () => {
  const s = installStore([]);
  const r = await put({ openaiApiKey: "", openaiBaseUrl: "https://gw.example.com/v1" });
  assert.equal(r.status, 400);
  assert.match(r.body.mcp_sync.openai.error, /not yet configured/);
  assert.equal(s.writes.length, 0);
});

test("saving only the organization keeps the saved key and base URL (config merges, the secret is untouched)", async () => {
  const s = installStore([OPENAI({ config: { base_url: "https://gw.example.com/v1" } })]);
  const r = await put({ openaiApiKey: "***", openaiBaseUrl: "https://gw.example.com/v1", openaiOrganization: "org-new" });
  assert.equal(r.status, 200);
  assert.equal(s.writes.length, 1);
  assert.deepEqual(s.writes[0].body.config, { base_url: "https://gw.example.com/v1", organization: "org-new" });
  assert.equal(s.writes[0].body.secrets, undefined, "the sentinel never overwrites the secret");
  assert.equal(s.store.get("oa-1").secrets.api_key, K_SAVED);
});

test("a malformed organization or project is refused, and clearing one with an empty value is allowed", async () => {
  const s = installStore([OPENAI({ config: { organization: "org-abc", project: "proj_def" } })]);
  for (const bad of [{ openaiOrganization: "org x" }, { openaiProject: "p\r\nX-Evil: 1" }, { openaiOrganization: "-lead" }]) {
    const r = await put({ openaiApiKey: "***", ...bad });
    assert.equal(r.status, 400, JSON.stringify(bad));
    assert.match(r.body.error, /must be an identifier/);
  }
  assert.equal(s.writes.length, 0);
  const ok = await put({ openaiApiKey: "***", openaiOrganization: "", openaiProject: "" });
  assert.equal(ok.status, 200);
  assert.deepEqual(s.writes[0].body.config, { organization: "", project: "" });
});

test("an unsafe base URL is refused and writes nothing", async () => {
  const s = installStore([OPENAI()]);
  for (const openaiBaseUrl of ["http://api.example.com/v1", "https://localhost/v1", "https://169.254.169.254/v1", "https://phantom-agent/v1", "https://user:pw@api.example.com/v1"]) {
    const r = await put({ openaiApiKey: K_NEW, openaiBaseUrl });
    assert.equal(r.status, 400, openaiBaseUrl);
    assert.equal(r.body.ok, false);
  }
  assert.equal(s.writes.length, 0);
});

/* ─── The key-exfiltration rule ────────────────────────────── */

for (const [label, def] of [
  ["openai", { instance: OPENAI, keyField: "openaiApiKey", urlField: "openaiBaseUrl", dflt: "https://api.openai.com/v1", gateway: "https://gw.example.com/openai/v1", other: "https://other.example.net/v1" }],
  ["anthropic", { instance: ANTHROPIC, keyField: "anthropicApiKey", urlField: "anthropicBaseUrl", dflt: "https://api.anthropic.com", gateway: "https://gw.example.com/anthropic", other: "https://other.example.net" }],
]) {
  test(`${label}: changing the base URL with the saved key left as "***" is refused and writes nothing`, async () => {
    const s = installStore([def.instance()]);
    const r = await put({ [def.keyField]: "***", [def.urlField]: def.other });
    assert.equal(r.status, 400);
    assert.equal(r.body.ok, false);
    assert.match(r.body.error, /again to change the base URL/);
    assert.match(r.body.mcp_sync[label].error, /only sent to the base URL it was saved with/);
    assert.equal(s.writes.length, 0, "the store is untouched");
    assert.equal(s.store.get(def.instance().id).config.base_url, undefined);
  });

  test(`${label}: changing the base URL with the key field omitted or empty is refused as well`, async () => {
    for (const keyPart of [{}, { [def.keyField]: "" }]) {
      const s = installStore([def.instance()]);
      const r = await put({ ...keyPart, [def.urlField]: def.other });
      assert.equal(r.status, 400, JSON.stringify(keyPart));
      assert.equal(s.writes.length, 0);
    }
  });

  test(`${label}: changing the base URL together with a newly typed key is accepted, and both are stored`, async () => {
    const s = installStore([def.instance()]);
    const r = await put({ [def.keyField]: K_NEW, [def.urlField]: def.other });
    assert.equal(r.status, 200);
    assert.equal(s.writes.length, 1);
    assert.equal(s.writes[0].body.secrets.api_key, K_NEW);
    assert.equal(s.writes[0].body.config.base_url, def.other);
  });

  test(`${label}: moving back to the default is a change too, when a gateway was saved`, async () => {
    const s = installStore([def.instance({ config: { base_url: def.gateway } })]);
    for (const toDefault of [def.dflt, ""]) {
      const r = await put({ [def.keyField]: "***", [def.urlField]: toDefault });
      assert.equal(r.status, 400, JSON.stringify(toDefault));
    }
    assert.equal(s.writes.length, 0);
  });

  test(`${label}: moving from the default to a gateway is a change; the default spelled out is not`, async () => {
    const s = installStore([def.instance()]);
    assert.equal((await put({ [def.keyField]: "***", [def.urlField]: def.gateway })).status, 400);
    assert.equal(s.writes.length, 0);
    // The default, typed out or left empty, is what is saved already.
    assert.equal((await put({ [def.keyField]: "***", [def.urlField]: def.dflt })).status, 200);
    assert.equal((await put({ [def.keyField]: "***", [def.urlField]: "" })).status, 200);
  });

  test(`${label}: the same URL spelled differently (case, trailing slash) needs no key`, async () => {
    const s = installStore([def.instance({ config: { base_url: def.gateway } })]);
    const respelled = def.gateway.replace("gw.example.com", "GW.Example.com") + "/";
    const r = await put({ [def.keyField]: "***", [def.urlField]: respelled });
    assert.equal(r.status, 200);
    assert.equal(s.writes.length, 1);
    assert.equal(s.writes[0].body.secrets, undefined);
  });

  test(`${label}: with no key stored there is nothing to carry away, so a base URL alone is not refused by this rule`, async () => {
    // No instance at all: the create step then needs the key (a different message), and nothing is written.
    const s = installStore([]);
    const r = await put({ [def.urlField]: def.other });
    assert.equal(r.status, 400);
    assert.match(r.body.mcp_sync[label].error, /not yet configured/);
    assert.equal(s.writes.length, 0);
  });
}

test("a refused provider stops the whole save: another provider's fields in the same request are not written", async () => {
  const s = installStore([OPENAI(), ANTHROPIC()]);
  const r = await put({ anthropicApiKey: K_NEW, openaiApiKey: "***", openaiBaseUrl: "https://other.example.net/v1" });
  assert.equal(r.status, 400);
  assert.equal(s.writes.length, 0);
  assert.equal(s.store.get("an-1").secrets.api_key, K_ANT, "the anthropic key was not replaced either");
});

test("saving Vertex fields never touches the keyed providers", async () => {
  const s = installStore([OPENAI(), ANTHROPIC()]);
  const r = await put({ vertexProjectId: "my-gcp-project", vertexLocation: "us-central1" });
  // Vertex has no instance and no JSON here, so the create is refused; what matters is that nothing else was written.
  assert.equal(r.status, 400);
  assert.equal(r.body.mcp_sync.openai.action, "skipped");
  assert.equal(r.body.mcp_sync.anthropic.action, "skipped");
  assert.equal(s.writes.length, 0);
});

for (const [label, field, existing] of [["OpenAI", "openaiApiKey", OPENAI], ["Anthropic", "anthropicApiKey", ANTHROPIC]]) {
  test(`${label}: a typed key that is a secret-store path is refused and writes nothing`, async () => {
    for (const bad of ["/ui/auth/admin/password_hash", " /ui/auth/admin/password_hash", "/agents/phantom/providers/other/api_key"]) {
      // The exfiltration shape: the path as the key, plus a changed base URL.
      const s = installStore([existing()]);
      const baseField = field.replace("ApiKey", "BaseUrl");
      const r = await put({ [field]: bad, [baseField]: "https://attacker.example.net/v1" });
      assert.equal(r.status, 400, bad);
      assert.match(r.body.error, /cannot start with "\/"/);
      assert.equal(s.writes.length, 0, "nothing reached the store");
      // And on first create, with no base URL.
      const c = installStore([]);
      assert.equal((await put({ [field]: bad })).status, 400);
      assert.equal(c.writes.length, 0);
    }
  });

  test(`${label}: a typed key containing whitespace or a newline is refused`, async () => {
    for (const bad of ["sk-abc def", "sk-abc\ndef", "sk-abc\r\ndef"]) {
      const s = installStore([]);
      const r = await put({ [field]: bad });
      assert.equal(r.status, 400, JSON.stringify(bad));
      assert.match(r.body.error, /spaces or line breaks/);
      assert.equal(s.writes.length, 0);
    }
  });

  test(`${label}: a normal key with surrounding whitespace is still trimmed and saved`, async () => {
    const s = installStore([]);
    const r = await put({ [field]: `  ${K_NEW}\n` });
    assert.equal(r.status, 200);
    assert.equal(s.writes[0].body.secrets.api_key, K_NEW);
  });
}

test("Vertex: a service-account value that is a path is refused and writes nothing", async () => {
  const s = installStore([]);
  const r = await put({ vertexProjectId: "p", vertexLocation: "us-central1", vertexServiceAccountJson: "/ui/auth/admin/password_hash" });
  assert.equal(r.status, 400);
  assert.match(r.body.error, /cannot start with "\/"/);
  assert.equal(s.writes.length, 0);
});

test("an empty save is a no-op", async () => {
  const s = installStore([OPENAI()]);
  const r = await put({});
  assert.equal(r.status, 200);
  assert.equal(r.body.mcp_sync.skipped, true);
  assert.equal(s.writes.length, 0);
});

for (const { name, fn } of queue) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.stack ?? e.message).split("\n").slice(0, 8).join("\n     ")); }
}
if (failed) { console.log(`\n${failed} test(s) failed`); process.exit(1); }
console.log("\nall providers config route tests passed");
