#!/usr/bin/env node
/**
 * POST /api/agent/instances and PATCH /api/agent/instances/[id]: run the real
 * route handlers against stubbed Next and MCP-proxy modules and assert that a
 * secret starting with "/" (which the MCP would read as a path to another stored
 * secret) is refused with 400 before anything is forwarded, while a plain secret,
 * the "***" redaction sentinel, a "/" value in config (not a secret) and a body
 * with no secrets are forwarded unchanged.
 *
 *   node scripts/test-instances-secret-route.mjs   (npm run test:instances-secret-route)
 *
 * Needs Node's module hooks and type stripping; on a Node without them the
 * test skips (the build type-checks the routes).
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

globalThis.__forwarded = [];
const STUBS = {
  "next/server": dataModule(`
    export class NextResponse extends Response {
      static json(body, init) { return new NextResponse(JSON.stringify(body), { status: init?.status ?? 200, headers: { 'content-type': 'application/json' } }); }
    }`),
  "@/lib/mcp-proxy": dataModule(`
    export async function proxyToMcp(request, path, options = {}) {
      globalThis.__forwarded.push({ method: request.method, path, body: options.body });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }`),
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

const collection = await import("../app/api/agent/instances/route.ts");
const item = await import("../app/api/agent/instances/[id]/route.ts");

const req = (method, body) =>
  new Request("http://localhost/api/agent/instances", { method, body: typeof body === "string" ? body : JSON.stringify(body) });
const params = { params: Promise.resolve({ id: "abc" }) };

const create = (body) => collection.POST(req("POST", body));
const patch = (body) => item.PATCH(req("PATCH", body), params);

// A path to another secret is refused, nothing is forwarded.
for (const [label, call] of [["POST", create], ["PATCH", patch]]) {
  globalThis.__forwarded.length = 0;
  const r = await call({ connector_id: "demo", name: "n", secrets: { api_key: "/ui/auth/admin/password_hash" } });
  assert.equal(r.status, 400, `${label}: a path secret is refused`);
  const body = await r.json();
  assert.match(body.error, /cannot start with "\/"/, `${label}: names the rule`);
  assert.match(body.error, /api_key/, `${label}: names the slot`);
  assert.equal(globalThis.__forwarded.length, 0, `${label}: nothing reaches the MCP`);

  // One bad slot among good ones still refuses the whole request.
  const mixed = await call({ secrets: { token: "fine", other: "/agents/phantom/providers/x/api_key" } });
  assert.equal(mixed.status, 400, `${label}: one path among good secrets is refused`);
  assert.equal(globalThis.__forwarded.length, 0);
}

// Everything else is forwarded byte for byte.
const forwardedBodies = [
  { connector_id: "demo", name: "n", secrets: { api_key: "plain-key" } },
  { secrets: { api_key: "***" } },
  { config: { base_url: "/relative/path" }, secrets: {} },
  { name: "renamed" },
  { secrets: { api_key: " /leading-space-is-a-literal" } },
  { secrets: { n: 5 } },
];
for (const [label, call, path] of [
  ["POST", create, "/api/v1/instances"],
  ["PATCH", patch, "/api/v1/instances/abc"],
]) {
  for (const body of forwardedBodies) {
    globalThis.__forwarded.length = 0;
    const r = await call(body);
    assert.equal(r.status, 200, `${label} ${JSON.stringify(body)} is forwarded`);
    assert.deepEqual(globalThis.__forwarded, [{ method: label, path, body: JSON.stringify(body) }]);
  }
}

// A body that is not JSON is the MCP's to reject (it answers 400 itself).
globalThis.__forwarded.length = 0;
const notJson = await create("not json");
assert.equal(notJson.status, 200);
assert.equal(globalThis.__forwarded[0].body, "not json");

console.log("ok: instances secret route");
