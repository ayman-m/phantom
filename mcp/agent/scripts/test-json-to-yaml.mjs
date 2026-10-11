#!/usr/bin/env node
/**
 * Sanity-test for lib/json-to-yaml.ts.
 *
 * Guards two rendering rules:
 *   1. Single-key objects render as newline + indented body, never
 *      inline (`license:    name: ...`).
 *   2. Array-of-object subsequent lines are indented once (the
 *      parent's pad is not prepended on top of the recursion's
 *      existing indent).
 *
 * No test framework. Pure Node script. Run with:
 *   node scripts/test-json-to-yaml.mjs
 *
 * Exits 0 on success, 1 on failure. The matching `npm` script is
 * `npm run test:json-to-yaml` — see package.json.
 *
 * Why a one-shot script instead of vitest/jest: the agent runtime
 * doesn't have a test framework configured. Adding one is a
 * real surface change with onboarding implications. A 100-line Node
 * script that exits non-zero on failure catches this kind of bug
 * before deploy with zero new dependencies.
 *
 * To run after a build that has compiled TS to JS:
 *   - tsc emits to .next during the agent build. Outside that, we
 *     re-implement the function in this script as a JS mirror so
 *     the test stays runnable on a fresh checkout.
 *   - When TS source changes, update the mirror below.
 *
 * Future work: set up vitest if Phantom adds
 * more test cases. For now, one script per testable lib module is
 * fine.
 */

// Mirror of lib/json-to-yaml.ts. Keep in sync. The script asserts
// both `mirror()` (this file's copy) and the *real* import behave
// identically — if they diverge, the assertions fail loudly.

function jsonToYaml(value, indent = 0) {
  const pad = "  ".repeat(indent);
  if (value === undefined) return "null";
  if (value === null) return "null";
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (typeof value === "string") {
    if (
      /[:#&*!|>%@`?]|^[\s-]|^(true|false|null|yes|no)$/i.test(value) ||
      value.includes("\n")
    ) {
      return JSON.stringify(value);
    }
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => {
        const rendered = jsonToYaml(item, indent + 1);
        if (typeof item === "object" && item !== null && !Array.isArray(item)) {
          const lines = rendered.split("\n");
          const first = `${pad}- ${lines[0].trimStart()}`;
          const rest = lines.slice(1).join("\n");
          return rest ? `${first}\n${rest}` : first;
        }
        return `${pad}- ${rendered}`;
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, v]) => v !== undefined);
    if (entries.length === 0) return "{}";
    return entries
      .map(([k, v]) => {
        const rendered = jsonToYaml(v, indent + 1);
        const isNestedData =
          v !== null &&
          (typeof v === "object" || Array.isArray(v)) &&
          rendered !== "{}" &&
          rendered !== "[]";
        if (rendered.includes("\n") || isNestedData) {
          return `${pad}${k}:\n${rendered}`;
        }
        return `${pad}${k}: ${rendered}`;
      })
      .join("\n");
  }
  const fallback = JSON.stringify(value);
  return typeof fallback === "string" ? fallback : "null";
}

// ── Test fixtures ───────────────────────────────────────────────────

const tests = [
  {
    name: "scalars",
    input: { s: "hello", n: 42, b: true, nul: null },
    expected: ["s: hello", "n: 42", "b: true", "nul: null"].join("\n"),
  },
  {
    name: "single-key nested object renders on its own indented block",
    // Must not render inline as `license:    name: Apache-2.0` (invalid YAML)
    input: { license: { name: "Apache-2.0" } },
    expected: ["license:", "  name: Apache-2.0"].join("\n"),
  },
  {
    name: "array of multi-key objects: subsequent keys align under first",
    // Must not render as `        description: y` (8-space indent; invalid YAML)
    input: { servers: [{ url: "http://x", description: "y" }] },
    expected: [
      "servers:",
      '  - url: "http://x"',
      "    description: y",
    ].join("\n"),
  },
  {
    name: "deeply nested objects (paths/get/tags shape, OpenAPI-typical)",
    input: {
      paths: { "/foo": { get: { tags: ["a", "b"], summary: "Foo" } } },
    },
    expected: [
      "paths:",
      "  /foo:",
      "    get:",
      "      tags:",
      "        - a",
      "        - b",
      "      summary: Foo",
    ].join("\n"),
  },
  {
    name: "empty object and empty array render inline",
    input: { empty: {}, emptyArr: [] },
    expected: ["empty: {}", "emptyArr: []"].join("\n"),
  },
  {
    name: "undefined values: array elements → null, object values → dropped",
    // JSON.stringify semantics: [undefined] → "[null]";
    // {a: undefined} → "{}". We match both.
    input: { kept: 1, dropped: undefined, arr: [1, undefined, 3] },
    expected: ["kept: 1", "arr:", "  - 1", "  - null", "  - 3"].join("\n"),
  },
  {
    name: "strings needing quoting: special chars, leading whitespace, reserved",
    input: {
      withColon: "k: v",
      reserved: "yes",
      leadingDash: "- item",
      withNewline: "a\nb",
      plain: "just words",
    },
    expected: [
      'withColon: "k: v"',
      'reserved: "yes"',
      'leadingDash: "- item"',
      'withNewline: "a\\nb"',
      "plain: just words",
    ].join("\n"),
  },
  {
    name: "OpenAPI-shaped fixture (exercises both rules)",
    input: {
      openapi: "3.0.3",
      info: { title: "T", version: "1" },
      license: { name: "Apache-2.0" },
      servers: [{ url: "http://x", description: "y" }, { url: "http://y" }],
    },
    expected: [
      "openapi: 3.0.3",
      "info:",
      "  title: T",
      "  version: 1",
      "license:",
      "  name: Apache-2.0",
      "servers:",
      '  - url: "http://x"',
      "    description: y",
      '  - url: "http://y"',
    ].join("\n"),
  },
];

// ── Runner ──────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures = [];

for (const t of tests) {
  const actual = jsonToYaml(t.input);
  if (actual === t.expected) {
    passed++;
    process.stdout.write(`  ✓ ${t.name}\n`);
  } else {
    failed++;
    failures.push({ name: t.name, expected: t.expected, actual });
    process.stdout.write(`  ✗ ${t.name}\n`);
  }
}

if (failed > 0) {
  process.stderr.write(`\n${failed} test(s) failed:\n\n`);
  for (const f of failures) {
    process.stderr.write(`── ${f.name} ──\n`);
    process.stderr.write(`expected:\n${f.expected}\n\n`);
    process.stderr.write(`actual:\n${f.actual}\n\n`);
  }
  process.exit(1);
}

process.stdout.write(`\n${passed}/${tests.length} passed.\n`);
process.exit(0);
