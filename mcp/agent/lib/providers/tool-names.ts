/**
 * Reversible wire-name codec for the tool catalog.
 *
 * MCP tool names include dotted forms (`xsiam.run_xql_query`) beside their flat
 * aliases (`xsiam_run_xql_query`). Gemini accepts both, so its adapter uses the
 * `identity` style and the catalog goes out unchanged. Claude requires
 * `^[a-zA-Z0-9_-]{1,128}$` and OpenAI `{1,64}`, so for those styles:
 *
 *   1. alias pairs collapse to the flat alias, so the catalog is not sent twice;
 *   2. every remaining name is encoded: `.` becomes `__`, any other character
 *      outside the allowed set becomes `_`;
 *   3. a name over the limit becomes `name[0:limit-9] + '_' + sha1(name)[0:8]`;
 *   4. a `wire -> canonical` map is built per request, and a collision between
 *      two different canonical names is a hard error, never a silent overwrite.
 *
 * `decode` answers only for names the request advertised, so a model cannot
 * call a tool it was never offered. The route, approvals, hooks, policy and
 * `deriveConnectorId` only ever see canonical names.
 *
 * Erasable TypeScript only; no `@/` imports.
 */

import { createHash } from 'node:crypto';
import { ProviderError } from './errors.ts';
import type { ToolSpec } from './types.ts';

export type ToolNameStyle = 'identity' | 'claude' | 'openai';

/** Longest wire name each vendor accepts. */
export const TOOL_NAME_LIMITS = { claude: 128, openai: 64 } as const;

export interface ToolNameCodec {
  style: ToolNameStyle;
  /** The catalog as it goes on the wire: wire-named, alias pairs collapsed. */
  tools: ToolSpec[];
  /** Canonical name -> wire name. Undefined for a tool that is not advertised. */
  encode(canonical: string): string | undefined;
  /** Wire name -> canonical name. Undefined for a name this request never advertised. */
  decode(wire: string): string | undefined;
  /** Canonical names dropped because a flat alias with the same text stands in for them. */
  collapsedAliases: ReadonlyMap<string, string>;
}

const SAFE_CHAR = /[^A-Za-z0-9_-]/g;

/** `.` -> `__`, anything else outside `[A-Za-z0-9_-]` -> `_`. */
function encodeChars(name: string): string {
  return name.replace(/\./g, '__').replace(SAFE_CHAR, '_');
}

function sha1Prefix(name: string): string {
  return createHash('sha1').update(name).digest('hex').slice(0, 8);
}

function toWireName(canonical: string, limit: number): string {
  const encoded = encodeChars(canonical);
  if (encoded.length <= limit) return encoded;
  // 8 hex characters plus the joining underscore take 9 of the limit.
  return `${encoded.slice(0, limit - 9)}_${sha1Prefix(canonical)}`;
}

function textIdentity(tool: ToolSpec): string {
  return JSON.stringify([tool.description ?? '', tool.inputSchema ?? null]);
}

/**
 * Find alias pairs: exactly two tools with the same description and schema,
 * one namespaced (`<connector>.<tool>`) and one flat whose name ends with that
 * tool segment (`<prefix>_<tool>`). This is the shape `resolveToolName` treats
 * as one function. Two namespaced tools with identical text (two uploaded
 * connectors that copy each other) are different tools and do not collapse,
 * nor do unrelated flat tools that merely share an empty description and
 * schema. Returns dropped-namespaced -> kept-flat.
 */
function findAliasPairs(tools: ToolSpec[]): Map<string, string> {
  const byText = new Map<string, ToolSpec[]>();
  for (const tool of tools) {
    const key = textIdentity(tool);
    const group = byText.get(key);
    if (group) group.push(tool);
    else byText.set(key, [tool]);
  }
  const dropped = new Map<string, string>();
  for (const group of byText.values()) {
    if (group.length !== 2) continue;
    const namespaced = group.filter((t) => t.name.includes('.'));
    const flat = group.filter((t) => !t.name.includes('.'));
    if (namespaced.length !== 1 || flat.length !== 1) continue;
    const segment = namespaced[0].name.slice(namespaced[0].name.lastIndexOf('.') + 1);
    if (flat[0].name === segment || flat[0].name.endsWith(`_${segment}`)) {
      dropped.set(namespaced[0].name, flat[0].name);
    }
  }
  return dropped;
}

export function buildToolNameCodec(tools: ToolSpec[], style: ToolNameStyle): ToolNameCodec {
  if (style === 'identity') {
    return {
      style,
      tools,
      encode: (canonical) => canonical,
      decode: (wire) => wire,
      collapsedAliases: new Map(),
    };
  }

  const limit = TOOL_NAME_LIMITS[style];
  const collapsed = findAliasPairs(tools);
  const kept = tools.filter((t) => !collapsed.has(t.name));

  const wireToCanonical = new Map<string, string>();
  const canonicalToWire = new Map<string, string>();
  const wireTools: ToolSpec[] = [];
  for (const tool of kept) {
    const wire = toWireName(tool.name, limit);
    if (!wire) {
      throw new ProviderError({
        kind: 'invalid_request',
        code: 'TOOL_NAME_INVALID',
        message: `Tool name "${tool.name}" has no wire form for the ${style} tool-name rules.`,
      });
    }
    const existing = wireToCanonical.get(wire);
    if (existing !== undefined) {
      throw new ProviderError({
        kind: 'invalid_request',
        code: 'TOOL_NAME_COLLISION',
        message:
          `Tools "${existing}" and "${tool.name}" both map to the wire name "${wire}" ` +
          `under the ${style} tool-name rules.`,
      });
    }
    wireToCanonical.set(wire, tool.name);
    canonicalToWire.set(tool.name, wire);
    wireTools.push({ ...tool, name: wire });
  }
  // A collapsed namespaced name still resolves to its flat alias's wire name,
  // so a replayed call to it (older history) keeps a valid wire form.
  for (const [dropped, keptName] of collapsed) {
    const wire = canonicalToWire.get(keptName);
    if (wire !== undefined) canonicalToWire.set(dropped, wire);
  }

  return {
    style,
    tools: wireTools,
    encode: (canonical) => canonicalToWire.get(canonical),
    decode: (wire) => wireToCanonical.get(wire),
    collapsedAliases: collapsed,
  };
}
