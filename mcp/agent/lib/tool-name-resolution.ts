/**
 * Resolve a bare tool name ("run_xql_query") against the MCP's tool list.
 *
 * A bundle connector's tool is registered twice from ONE wrapped function: the
 * namespaced `<connector-id>.<tool>` and the legacy flat alias `<prefix><tool>`
 * (for example `xsiam.run_xql_query` and `xsiam_run_xql_query`). Both appear in
 * tools/list with the same description and input schema. A suffix match used to
 * see two tools and refuse with "ambiguous", so a bare name never worked for
 * any connector that still advertises its legacy aliases.
 *
 * Rule: matches that are the same function (same description and same input
 * schema) count as one tool, and the namespaced name is the one returned. Two
 * different tools that merely share a suffix (different connectors) still
 * differ in description or schema and remain ambiguous.
 *
 * Erasable-syntax TypeScript only, so scripts/test-tool-name-resolution.mjs can
 * import this file directly with Node's type stripping.
 */

export interface ListedTool {
  name: string;
  description?: string;
  inputSchema?: unknown;
}

export interface Resolution {
  resolved?: string;
  error?: string;
}

function identity(t: ListedTool): string {
  return JSON.stringify([t.description ?? "", t.inputSchema ?? null]);
}

export function resolveToolName(tools: ListedTool[], bareName: string): Resolution {
  // Exact match wins.
  const exact = tools.find((t) => t.name === bareName);
  if (exact) return { resolved: exact.name };

  // Suffix match: ".<bare>" (connector-namespaced) or "_<bare>" (functionPrefix style).
  const matches = tools.filter(
    (t) => t.name.endsWith(`.${bareName}`) || t.name.endsWith(`_${bareName}`),
  );
  if (matches.length === 0) {
    return {
      error: `no tool matched "${bareName}"; try the fully-qualified name (e.g. "cortex-xdr.get_cases_and_issues" or "xdr_get_cases_and_issues")`,
    };
  }
  if (matches.length === 1) return { resolved: matches[0].name };

  // Several names for one function? Then there is one tool, not many.
  // Require exactly ONE namespaced name among them: that is the shape of an
  // alias pair. Several namespaced names with identical text (for example two
  // uploaded connectors that copy each other) are different tools.
  const distinct = new Set(matches.map(identity));
  const namespaced = matches.filter((t) => t.name.includes("."));
  if (distinct.size === 1 && namespaced.length === 1) {
    return { resolved: namespaced[0].name };
  }
  return {
    error: `ambiguous tool name "${bareName}" — matched: ${matches
      .map((m) => m.name)
      .join(", ")}. Use a fully-qualified name.`,
  };
}
