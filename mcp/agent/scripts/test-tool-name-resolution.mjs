#!/usr/bin/env node
/**
 * Behaviour test for lib/tool-name-resolution.ts (the bare-name lookup used by
 * the direct tool-call route, `^run_xql_query query=...` in chat).
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-tool-name-resolution.mjs   (npm run test:tool-name-resolution)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { resolveToolName } = await import("../lib/tool-name-resolution.ts");

const schema = { type: "object", properties: { query: { type: "string" } } };
const tool = (name, description = "Run an XQL query", inputSchema = schema) => ({ name, description, inputSchema });
let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + e.message); }
}

test("a namespaced tool and its legacy alias resolve to the namespaced name", () => {
  const tools = [tool("xsiam_run_xql_query"), tool("xsiam.run_xql_query"), tool("other_thing", "x")];
  assert.deepEqual(resolveToolName(tools, "run_xql_query"), { resolved: "xsiam.run_xql_query" });
});

test("the same holds when the connector id and the alias prefix differ", () => {
  const t = (n) => tool(n, "Get cases", { type: "object" });
  assert.deepEqual(
    resolveToolName([t("xdr_get_cases_and_issues"), t("cortex-xdr.get_cases_and_issues")], "get_cases_and_issues"),
    { resolved: "cortex-xdr.get_cases_and_issues" },
  );
});

test("two different tools that share a suffix stay ambiguous", () => {
  const tools = [tool("xsiam.search", "Search XSIAM"), tool("cortex-docs.search", "Search the docs")];
  const r = resolveToolName(tools, "search");
  assert.equal(r.resolved, undefined);
  assert.match(r.error, /ambiguous tool name "search" — matched: xsiam\.search, cortex-docs\.search/);
});

test("same description but a different input schema stays ambiguous", () => {
  const tools = [tool("a.go", "Go", { type: "object" }), tool("b.go", "Go", { type: "object", properties: { x: {} } })];
  assert.ok(resolveToolName(tools, "go").error);
});

test("two namespaced tools with identical text are two tools, not an alias pair", () => {
  const tools = [tool("a.run_xql_query"), tool("b.run_xql_query")];
  assert.ok(resolveToolName(tools, "run_xql_query").error);
});

test("two flat names with identical text and no namespaced one stay ambiguous", () => {
  const tools = [tool("a_run_xql_query"), tool("b_run_xql_query")];
  assert.ok(resolveToolName(tools, "run_xql_query").error);
});

test("an exact name wins over suffix matches", () => {
  const tools = [tool("run_xql_query"), tool("xsiam.run_xql_query", "other")];
  assert.deepEqual(resolveToolName(tools, "run_xql_query"), { resolved: "run_xql_query" });
});

test("a fully qualified name resolves to itself", () => {
  const tools = [tool("xsiam_run_xql_query"), tool("xsiam.run_xql_query")];
  assert.deepEqual(resolveToolName(tools, "xsiam_run_xql_query"), { resolved: "xsiam_run_xql_query" });
});

test("a single match resolves", () => {
  assert.deepEqual(resolveToolName([tool("web.fetch", "f")], "fetch"), { resolved: "web.fetch" });
});

test("no match names the way out", () => {
  assert.match(resolveToolName([tool("a.b")], "zzz").error, /no tool matched "zzz"/);
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
