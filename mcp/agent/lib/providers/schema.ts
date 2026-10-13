/**
 * Tool-schema conversion for the model providers.
 *
 * `toPortableSchema` (bottom of file) serves Claude and OpenAI tool
 * definitions. `toGeminiSchema` serves Gemini function declarations and is the former chat-route `sanitizeSchema`, moved verbatim
 * (only the name changed). It strips the JSON-Schema keywords Gemini's
 * function-declaration subset rejects, inlines `$ref`/`$defs`, and flattens
 * `oneOf`/`anyOf`/`allOf`.
 *
 * NOTE: it mutates the `properties` object of the schema it is given (the
 * shallow copy shares it). Callers that reuse a schema must clone first.
 *
 * Erasable TypeScript only; no imports.
 */

const UNSUPPORTED_GEMINI_SCHEMA_KEYS = new Set([
  '$id',
  '$schema',
  'additionalItems',
  'additionalProperties',
  'const',
  'contains',
  'default',
  'dependentRequired',
  'dependentSchemas',
  'else',
  'examples',
  'exclusiveMaximum',
  'exclusiveMinimum',
  'if',
  'maxProperties',
  'minProperties',
  'not',
  'pattern',
  'patternProperties',
  'propertyNames',
  'then',
  'title',
  'unevaluatedItems',
  'unevaluatedProperties',
]);

export function toGeminiSchema(
  schema: Record<string, unknown>,
  defs: Record<string, unknown> = {},
  depth = 0,
  processing: Set<string> = new Set()
): Record<string, unknown> {
  if (depth > 10) {
    return { type: 'object', description: 'Complex schema (truncated)' };
  }

  const localSchema = { ...schema };

  for (const key of UNSUPPORTED_GEMINI_SCHEMA_KEYS) {
    delete localSchema[key];
  }

  if ('$defs' in localSchema && typeof localSchema.$defs === 'object' && localSchema.$defs) {
    Object.assign(defs, localSchema.$defs as Record<string, unknown>);
    delete localSchema.$defs;
  }

  if ('definitions' in localSchema && typeof localSchema.definitions === 'object' && localSchema.definitions) {
    Object.assign(defs, localSchema.definitions as Record<string, unknown>);
    delete localSchema.definitions;
  }

  if ('$ref' in localSchema && typeof localSchema.$ref === 'string') {
    const ref = localSchema.$ref;
    const refName = ref.split('/').pop() || ref;
    delete localSchema.$ref;

    if (processing.has(refName)) {
      return { type: 'object', description: `Recursive reference to ${refName}` };
    }

    const resolved = defs[refName];
    if (resolved && typeof resolved === 'object') {
      processing.add(refName);
      const merged = toGeminiSchema(resolved as Record<string, unknown>, defs, depth + 1, new Set(processing));
      processing.delete(refName);
      return merged;
    }

    return { type: 'string', description: `Reference to ${refName}` };
  }

  const complexKeys = ['oneOf', 'anyOf', 'allOf'] as const;
  let hasComplex = false;
  for (const key of complexKeys) {
    if (key in localSchema) {
      delete localSchema[key];
      hasComplex = true;
    }
  }

  if (hasComplex) {
    return {
      ...localSchema,
      type: 'object',
      description: `${(localSchema.description as string) || 'Complex variant'} (simplified)`,
    };
  }

  if (typeof localSchema.properties === 'object' && localSchema.properties) {
    const props = localSchema.properties as Record<string, unknown>;
    for (const [key, value] of Object.entries(props)) {
      if (value && typeof value === 'object') {
        props[key] = toGeminiSchema(value as Record<string, unknown>, defs, depth + 1, new Set(processing));
      }
    }
  }

  if (typeof localSchema.items === 'object' && localSchema.items) {
    localSchema.items = toGeminiSchema(
      localSchema.items as Record<string, unknown>,
      defs,
      depth + 1,
      new Set(processing)
    );
  }

  return localSchema;
}

/* ─── Portable schema (Claude and OpenAI tool definitions) ───── */

const MAX_PORTABLE_DEPTH = 24;
const VALUE_KEYWORDS = new Set(['enum', 'const', 'default', 'examples', 'required']);
const NAME_MAP_KEYWORDS = new Set(['properties', 'patternProperties', 'dependentSchemas']);

type Json = Record<string, unknown>;

function isPlainObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Follow a local JSON pointer ("#/$defs/Name", "#/properties/a") inside `root`. */
function followPointer(root: Json, ref: string): unknown {
  if (!ref.startsWith('#')) return undefined;
  const path = ref.slice(1);
  if (path === '' || path === '/') return root;
  let node: unknown = root;
  for (const raw of path.replace(/^\//, '').split('/')) {
    const key = decodeURIComponent(raw).replace(/~1/g, '/').replace(/~0/g, '~');
    if (!isPlainObject(node) && !Array.isArray(node)) return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function expandPortable(node: unknown, root: Json, expanding: readonly string[], depth: number): unknown {
  if (Array.isArray(node)) return node.map((item) => expandPortable(item, root, expanding, depth + 1));
  if (!isPlainObject(node)) return node;
  if (depth > MAX_PORTABLE_DEPTH) return { type: 'object', description: 'Complex schema (truncated)' };

  const { $ref, ...rest } = node;
  if (typeof $ref === 'string') {
    if (expanding.includes($ref)) {
      return { type: 'object', description: `Recursive reference to ${$ref.split('/').pop() || $ref}` };
    }
    const target = followPointer(root, $ref);
    // Sibling keywords of a $ref (a description, a default) override the target's.
    const siblings = expandPortable(rest, root, expanding, depth + 1) as Json;
    if (!isPlainObject(target)) return { ...siblings };
    const resolved = expandPortable(target, root, [...expanding, $ref], depth + 1) as Json;
    return { ...resolved, ...siblings };
  }

  const out: Json = {};
  for (const [key, value] of Object.entries(rest)) {
    // The definition tables and identifiers are consumed by the inlining.
    if (key === '$defs' || key === 'definitions' || key === '$schema' || key === '$id') continue;
    if (VALUE_KEYWORDS.has(key)) {
      // Literal data, not schema: never rewritten.
      out[key] = value;
    } else if (NAME_MAP_KEYWORDS.has(key) && isPlainObject(value)) {
      // The keys are property names, so a property called "$id" is not a keyword.
      out[key] = Object.fromEntries(
        Object.entries(value).map(([name, sub]) => [name, expandPortable(sub, root, expanding, depth + 1)]),
      );
    } else {
      out[key] = expandPortable(value, root, expanding, depth + 1);
    }
  }
  return out;
}

/**
 * A tool input schema in the portable JSON-Schema subset that Claude and OpenAI
 * accept: `$ref`/`$defs` (and `definitions`) inlined, `$schema` and `$id`
 * dropped, the top level forced to `type: "object"` with a `properties` member,
 * and top-level `oneOf`/`anyOf`/`allOf` removed (both vendors reject them there).
 * A recursive reference becomes a bare object, an unresolvable one an
 * unconstrained schema. Never mutates its input.
 */
export function toPortableSchema(schema: Record<string, unknown> | null | undefined): Record<string, unknown> {
  if (!isPlainObject(schema)) return { type: 'object', properties: {} };
  const expanded = expandPortable(schema, schema, [], 0) as Json;
  delete expanded.oneOf;
  delete expanded.anyOf;
  delete expanded.allOf;
  expanded.type = 'object';
  if (!isPlainObject(expanded.properties)) expanded.properties = {};
  return expanded;
}
