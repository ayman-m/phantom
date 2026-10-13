#!/usr/bin/env node
/**
 * Tool-name codec (lib/providers/tool-names.ts): dots, collisions, length
 * caps, round trip, alias dedupe, and the identity style Gemini uses.
 *
 *   node scripts/test-tool-name-codec.mjs   (npm run test:tool-name-codec)
 *
 * Imports the real TypeScript through Node's type stripping; on a Node
 * without it the test skips (the build type-checks the module).
 */
import assert from "node:assert/strict";

const { stripTypeScriptTypes } = await import("node:module");
if (!process.features.typescript || typeof stripTypeScriptTypes !== "function") {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const { buildToolNameCodec, TOOL_NAME_LIMITS } = await import("../lib/providers/tool-names.ts");

let failed = 0;
function test(name, fn) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + String(e.message).split("\n").join("\n     ")); }
}

const SCHEMA = { type: "object", properties: { query: { type: "string" } }, required: ["query"] };
const tool = (name, description = "d", inputSchema = SCHEMA) => ({ name, description, inputSchema });
const CLAUDE_RE = /^[a-zA-Z0-9_-]{1,128}$/;
const OPENAI_RE = /^[a-zA-Z0-9_-]{1,64}$/;

test("limits are the vendors'", () => {
  assert.equal(TOOL_NAME_LIMITS.claude, 128);
  assert.equal(TOOL_NAME_LIMITS.openai, 64);
});

test("identity: the catalog and every name pass through untouched", () => {
  const tools = [tool("xsiam.run_xql_query"), tool("xsiam_run_xql_query")];
  const codec = buildToolNameCodec(tools, "identity");
  assert.equal(codec.tools, tools, "same array, no dedupe");
  assert.equal(codec.encode("xsiam.run_xql_query"), "xsiam.run_xql_query");
  assert.equal(codec.decode("xsiam.run_xql_query"), "xsiam.run_xql_query");
  assert.equal(codec.decode("anything"), "anything", "identity does not police names");
  assert.equal(codec.collapsedAliases.size, 0);
});

test("dots become double underscores and other characters become single underscores", () => {
  const codec = buildToolNameCodec([tool("cortex-xdr.get_cases"), tool("odd name!x"), tool("plain_tool")], "claude");
  assert.deepEqual(codec.tools.map((t) => t.name), ["cortex-xdr__get_cases", "odd_name_x", "plain_tool"]);
  for (const t of codec.tools) assert.match(t.name, CLAUDE_RE);
});

test("wire tools keep description and schema, and the input is not mutated", () => {
  const input = [tool("a.b", "does a b", { type: "object", properties: {} })];
  const before = JSON.stringify(input);
  const codec = buildToolNameCodec(input, "openai");
  assert.equal(JSON.stringify(input), before);
  assert.equal(codec.tools[0].description, "does a b");
  assert.deepEqual(codec.tools[0].inputSchema, { type: "object", properties: {} });
  assert.notEqual(codec.tools[0], input[0]);
});

test("round trip: decode(encode(name)) returns the canonical name", () => {
  const names = ["xsiam.run_xql_query", "jobs_create", "cortex-xdr.get_cases", "weird name.x!"];
  for (const style of ["claude", "openai"]) {
    const codec = buildToolNameCodec(names.map((n) => tool(n, n)), style);
    for (const n of names) {
      const wire = codec.encode(n);
      assert.ok(wire, `${style} encodes ${n}`);
      assert.equal(codec.decode(wire), n, `${style} round trip for ${n}`);
    }
  }
});

test("decode answers only for names the request advertised", () => {
  const codec = buildToolNameCodec([tool("jobs_create", "c"), tool("jobs_list", "l")], "claude");
  assert.equal(codec.decode("jobs_create"), "jobs_create");
  assert.equal(codec.decode("jobs_delete"), undefined);
  assert.equal(codec.decode("jobs__create"), undefined);
  assert.equal(codec.encode("jobs_delete"), undefined);
});

test("collision between two canonical names is a hard error", () => {
  const dotted = [tool("a.b", "x"), tool("a__b", "y")];
  assert.throws(() => buildToolNameCodec(dotted, "claude"), (e) => {
    assert.equal(e.name, "ProviderError");
    assert.equal(e.code, "TOOL_NAME_COLLISION");
    assert.match(e.message, /a\.b/);
    assert.match(e.message, /a__b/);
    return true;
  });
  assert.throws(() => buildToolNameCodec([tool("a b", "x"), tool("a_b", "y")], "openai"), /both map to the wire name/);
  assert.throws(() => buildToolNameCodec([tool("a.", "x"), tool("a__", "y")], "claude"), (e) => e.code === "TOOL_NAME_COLLISION");
});

test("a name with no wire form is rejected, not silently emptied", () => {
  assert.throws(() => buildToolNameCodec([tool("", "x")], "claude"), (e) => e.code === "TOOL_NAME_INVALID");
});

test("length caps: 128 for Claude and 64 for OpenAI, with a sha1 suffix", () => {
  const long = `connector.${"very_long_segment_".repeat(12)}tool`;
  for (const [style, limit, re] of [["claude", 128, CLAUDE_RE], ["openai", 64, OPENAI_RE]]) {
    const codec = buildToolNameCodec([tool(long, "l")], style);
    const wire = codec.tools[0].name;
    assert.ok(wire.length <= limit, `${style}: ${wire.length} > ${limit}`);
    assert.equal(wire.length, limit, "an over-limit name is cut to exactly the limit");
    assert.match(wire, re);
    assert.match(wire, /_[0-9a-f]{8}$/);
    assert.equal(codec.decode(wire), long);
  }
  // A name right at the limit is not hashed.
  const exact = "x".repeat(64);
  assert.equal(buildToolNameCodec([tool(exact, "e")], "openai").tools[0].name, exact);
  assert.notEqual(buildToolNameCodec([tool(exact + "y", "e")], "openai").tools[0].name, exact + "y");
});

test("two long names sharing a prefix get different wire names", () => {
  const prefix = "p".repeat(100);
  const codec = buildToolNameCodec([tool(`${prefix}.one`, "a"), tool(`${prefix}.two`, "b")], "openai");
  const [a, b] = codec.tools.map((t) => t.name);
  assert.notEqual(a, b);
  assert.equal(codec.decode(a), `${prefix}.one`);
  assert.equal(codec.decode(b), `${prefix}.two`);
});

test("the hash depends only on the canonical name, so it is stable across requests", () => {
  const long = "q".repeat(90) + ".tool";
  const a = buildToolNameCodec([tool(long, "1")], "openai").tools[0].name;
  const b = buildToolNameCodec([tool("other", "x"), tool(long, "2")], "openai").tools[1].name;
  assert.equal(a, b);
});

test("alias dedupe: a namespaced name and its flat alias collapse to the flat one", () => {
  const tools = [tool("xsiam.run_xql_query", "Run XQL"), tool("xsiam_run_xql_query", "Run XQL"), tool("jobs_list", "List jobs")];
  const codec = buildToolNameCodec(tools, "claude");
  assert.deepEqual(codec.tools.map((t) => t.name), ["xsiam_run_xql_query", "jobs_list"]);
  assert.equal(codec.collapsedAliases.get("xsiam.run_xql_query"), "xsiam_run_xql_query");
  // The dropped namespaced name still has a wire form (older history), and the flat one decodes.
  assert.equal(codec.encode("xsiam.run_xql_query"), "xsiam_run_xql_query");
  assert.equal(codec.decode("xsiam_run_xql_query"), "xsiam_run_xql_query");
});

test("alias dedupe: the catalog is not sent twice", () => {
  const tools = [];
  for (const id of ["xsiam", "caldera", "cortex-xdr"]) {
    for (const fn of ["a", "b", "c"]) {
      tools.push(tool(`${id}.${fn}`, `${id} ${fn}`));
      tools.push(tool(`${id.replace("-", "_")}_${fn}`, `${id} ${fn}`));
    }
  }
  const codec = buildToolNameCodec(tools, "openai");
  assert.equal(codec.tools.length, 9);
  assert.equal(codec.collapsedAliases.size, 9);
});

test("alias dedupe: two namespaced tools with identical text do NOT collapse", () => {
  const tools = [tool("one.run", "same"), tool("two.run", "same")];
  const codec = buildToolNameCodec(tools, "claude");
  assert.equal(codec.tools.length, 2);
  assert.equal(codec.collapsedAliases.size, 0);
});

test("alias dedupe: unrelated flat tools sharing an empty description and schema do NOT collapse", () => {
  const tools = [tool("no_schema_tool", "", {}), tool("other.thing", "", {})];
  const codec = buildToolNameCodec(tools, "claude");
  assert.equal(codec.tools.length, 2, "flat name does not end with the namespaced tool segment");
  const three = buildToolNameCodec([tool("c.run", "t"), tool("c_run", "t"), tool("d_run", "t")], "claude");
  assert.equal(three.tools.length, 3, "a group of three is not an alias pair");
});

test("alias dedupe: different description or schema keeps both", () => {
  const codec = buildToolNameCodec([tool("c.run", "one"), tool("c_run", "two")], "claude");
  assert.equal(codec.tools.length, 2);
  const codec2 = buildToolNameCodec([tool("c.run", "t", SCHEMA), tool("c_run", "t", { type: "object" })], "claude");
  assert.equal(codec2.tools.length, 2);
});

test("a collapsed alias does not cause a collision with its flat twin", () => {
  assert.doesNotThrow(() => buildToolNameCodec([tool("c.run", "t"), tool("c_run", "t")], "openai"));
});

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all passed");
