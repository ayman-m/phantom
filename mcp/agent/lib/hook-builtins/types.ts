/**
 * Builtin hook spec contract.
 *
 * A "builtin" hook is an in-process TypeScript function shipped in the
 * phantom-agent image (under `mcp/agent/lib/hook-builtins/`) that operators
 * can install from `/settings/hooks` with a single dropdown pick + a
 * dynamic config form — no subprocess, no HTTP, no code edits.
 *
 * Why a registry vs. one-off handlers:
 *
 *   - **Operator-facing affordance** — `/settings/hooks` needs to enumerate
 *     "what builtins exist" + render each one's config form. A registry is
 *     the natural place to ask both questions.
 *   - **Validation** — the same registry that lists builtins to the UI
 *     also lets `validateHook()` confirm that a stored hook's
 *     `transport.name` references a known builtin AND that its `config`
 *     matches the builtin's expected shape.
 *   - **Dispatch** — the hook-runner asks the registry "give me the
 *     handler for builtin `X`", invokes it with the payload + config.
 *
 * Why not zod / json-schema:
 *
 *   - The agent has no zod / ajv dependency (`mcp/agent/package.json`
 *     has zero schema-validation packages), and adding one just for
 *     this contract is not justified — the existing `validateHook()` in `lib/hooks.ts` uses
 *     plain typed-validator functions, and the builtin specs follow the
 *     same pattern: each spec exports a `validateConfig(unknown) -> Result`
 *     function it owns end-to-end.
 *
 * Why builtins ship in `phantom-agent`'s image (not as plugins):
 *
 *   - Builtins are framework-side primitives (slack-approval, rate-limit,
 *     context-warning, memory-inject). They're the same surface for every
 *     deployment; shipping them in-image guarantees they're available
 *     out-of-the-box, no install step.
 *   - Entry-point plugins are the path for THIRD-PARTY
 *     extensions that ship in customer-installed packages. Builtins are
 *     our path; plugins are theirs. Both coexist.
 */

// Type-only import — no runtime cycle even though `hooks.ts` imports
// `getBuiltinHook` (a value) from this directory. Values flow one way:
// hooks.ts → hook-builtins/index.ts. Types flow the other:
// hook-builtins/types.ts ← hooks.ts (type-only, erased at runtime).
import type { HookPayload, HookResult } from "@/lib/hooks";

/** Outcome of `BuiltinHookSpec.validateConfig`. */
export type BuiltinConfigValidation =
  | { ok: true; config: Record<string, unknown> }
  | { ok: false; error: string };

/** What `/settings/hooks/new` renders to gather config from the operator.
 *
 *  Each field becomes one form row. Kept intentionally narrow to keep the
 *  dynamic form simple — most builtins need 1-4 fields. Builtins that
 *  truly need richer UX (color pickers, nested objects) should ship their
 *  own settings page and be triggered via a "Configure…" link from
 *  /settings/hooks rather than overloading this dynamic form. */
export interface BuiltinConfigField {
  /** Stable key — appears verbatim in the stored `transport.config` blob. */
  key: string;
  /** Human-readable label shown above the input. */
  label: string;
  /** Field type — drives which input the UI renders. */
  type: "string" | "url" | "number" | "boolean" | "select" | "secret-ref";
  /** When `type === "select"`, the options the dropdown lists. */
  options?: Array<{ value: string; label: string }>;
  /** Helper text shown below the input (1 line). */
  helper?: string;
  /** Placeholder for text inputs. */
  placeholder?: string;
  /** Bounds for `type === "number"`. */
  min?: number;
  max?: number;
  /** Default applied when the operator leaves the field empty. */
  defaultValue?: unknown;
  /** When true, the form blocks save until the operator provides a value. */
  required?: boolean;
}

/** One registered builtin. Each spec is the single source of truth for:
 *   - what the builtin does (operator-readable description)
 *   - which events it can be attached to
 *   - how to render its config form
 *   - how to validate that config
 *   - how to invoke it at hook-fire time */
export interface BuiltinHookSpec {
  /** Stable name. Stored verbatim as `transport.name`. Convention:
   *  kebab-case, no `builtin:` prefix (the prefix is implied by the
   *  transport.type). */
  name: string;
  /** Operator-readable display name shown in the dropdown. */
  displayName: string;
  /** One- or two-sentence description shown beside the dropdown
   *  selection. Should answer "what does this do, when do I want it?". */
  description: string;
  /** Material icon name (matches the `material-symbols-outlined`
   *  font Phantom already loads). Used in the /settings/hooks list row
   *  to badge builtins by purpose. */
  icon: string;
  /** Which `HookEvent` names this builtin can be attached to. Empty
   *  array means "any event"; non-empty restricts the event selector
   *  to listed values when this builtin is picked. */
  compatibleEvents: readonly string[];
  /** Form field definitions for the dynamic config form. */
  configFields: readonly BuiltinConfigField[];
  /** Validates an operator-submitted config blob. Returns the normalized
   *  config (with defaults applied) or an error message. Same contract
   *  shape as `validateHook` in `lib/hooks.ts` — strict-but-forgiving. */
  validateConfig: (raw: unknown) => BuiltinConfigValidation;
  /** Runs the builtin. Mirrors the shape of `runCommandHook` /
   *  `runHttpHook` in `lib/hook-runner.ts`:
   *   - Resolves to a `HookResult` (possibly empty `{}` for no-op).
   *   - May resolve to `null` for "no decision contributed."
   *   - Throws on hard error; the dispatcher applies the hook's
   *     `failurePolicy` per the same precedence rules as other
   *     transports. */
  handle: (
    payload: HookPayload,
    config: Record<string, unknown>,
    options: { signal: AbortSignal; timeoutMs: number },
  ) => Promise<HookResult | null>;
}
