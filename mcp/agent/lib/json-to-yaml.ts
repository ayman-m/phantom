/**
 * Minimal JSON → YAML serializer used by the OpenAPI spec endpoint.
 *
 * Extracted from `app/api/agent/openapi/route.ts` so:
 *
 *   1. It can be unit-tested without dragging in Next.js / OpenAPI
 *      generator surface — test harness lives in
 *      `scripts/test-json-to-yaml.mjs`.
 *   2. The route handler shrinks back to its actual job (assembly +
 *      headers).
 *   3. Future consumers (e.g. an MCP tool that wants a YAML payload)
 *      can import this directly.
 *
 * Design constraints — read these before "improving" the function:
 *
 *   - **No external YAML library.** The original was hand-rolled to
 *     avoid the bundle weight of `js-yaml` (~30kb gzipped) for a
 *     ~50-endpoint spec. If we ever need YAML in 3+ places, switch.
 *   - **Match JSON.stringify object semantics for `undefined`.**
 *     Object values that are undefined drop entirely; array elements
 *     that are undefined render as `null`. Same as
 *     `JSON.stringify({a: undefined})` → `'{}'` and
 *     `JSON.stringify([undefined])` → `'[null]'`.
 *   - **Quote strings only when needed.** Bare scalars are more
 *     readable; we quote when the string contains YAML's special
 *     chars (`: # & * ! | > % @ \` ?`), starts with whitespace or `-`,
 *     or matches a reserved keyword (true/false/null/yes/no).
 *   - **Preserve tool-call/result alternation invariant.** Doesn't
 *     apply here (no chat data), but worth noting that any change to
 *     output shape risks breaking downstream consumers (Swagger UI,
 *     Redoc, yamllint) — bump test fixtures whenever you touch the
 *     emitter logic.
 *
 * Test fixtures live next to the runnable script in
 * `scripts/test-json-to-yaml.mjs` — keep them in sync with this
 * file's behavior.
 */

export function jsonToYaml(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);
  // Handle undefined first: it would otherwise fall through every
  // branch and hit JSON.stringify(undefined), which returns the literal
  // value `undefined` (not a string), so the parent caller would crash
  // on `rendered.includes("\n")` with
  // "Cannot read properties of undefined." Match JSON.stringify
  // semantics: an undefined value renders as null inside arrays
  // (JSON.stringify([undefined]) → "[null]") and gets dropped from
  // objects (JSON.stringify({a: undefined}) → "{}", handled by the
  // object branch's filter below).
  if (value === undefined) return "null";
  if (value === null) return "null";
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (typeof value === "string") {
    // Quote strings with special chars; otherwise emit bare scalar.
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
        if (
          typeof item === "object" &&
          item !== null &&
          !Array.isArray(item)
        ) {
          // The first key inlines onto the `-` dash; subsequent keys
          // are already at `(indent+1)*2` column from the recursion,
          // which is exactly where they need to align under the
          // first key. Adding `${pad}  ` to each
          // subsequent line would double-stack the indent and produce
          // mis-aligned YAML (`        description: y` 8 spaces deep
          // when 4 is correct).
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
    // Drop undefined entries to match JSON.stringify object semantics.
    // Otherwise an `{ a: 1, b: undefined }` would emit "b: null" which
    // changes meaning (and the consumer probably never set b for a
    // reason).
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, v]) => v !== undefined,
    );
    if (entries.length === 0) return "{}";
    return entries
      .map(([k, v]) => {
        const rendered = jsonToYaml(v, indent + 1);
        // Two cases need a newline + indented body:
        //   1. Multi-line rendering (rendered.includes("\n")).
        //   2. Single-line rendering of an object/non-empty array
        //      (the recurse returned `  childKey: val` or `  - val`,
        //      which is still nested data — emitting it inline as
        //      `parent:   childKey: val` produces invalid YAML).
        // Primitive scalars (string, number, bool, null) and the
        // explicit empty markers `{}` and `[]` go inline.
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
  // Fallback for symbols / functions (shouldn't appear in OpenAPI but
  // be defensive — JSON.stringify could return undefined here too).
  const fallback = JSON.stringify(value);
  return typeof fallback === "string" ? fallback : "null";
}
