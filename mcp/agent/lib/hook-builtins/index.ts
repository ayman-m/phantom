/**
 * Builtin hook registry.
 *
 * Single source of truth for which builtin handlers ship with this
 * phantom-agent image. Lookup is by `name` (the value of
 * `transport.name` on a registered builtin-transport hook).
 *
 * Why a const Record vs. dynamic import / discovery:
 *
 *   - The set of builtins is small and ships with the image. Listing
 *     them statically here means `npx tsc --noEmit` catches at build
 *     time any spec that doesn't satisfy `BuiltinHookSpec` — a runtime
 *     "import everything in the directory" path would defer those
 *     errors to first-fire.
 *   - The agent UI fetches the registry over `/api/agent/hooks/builtins`
 *     to populate the dropdown. A static export
 *     gives the route handler a synchronous, no-IO read of the catalog.
 *
 * Adding a new builtin:
 *   1. Create `lib/hook-builtins/<name>.ts` exporting a `BuiltinHookSpec`.
 *   2. Import + add to `BUILTIN_HOOKS` below.
 *   3. Verify `tsc --noEmit` is clean.
 */

import type { BuiltinHookSpec } from "./types";
import { slackApprovalBuiltin } from "./slack-approval";
import { preCompactContextWarningBuiltin } from "./pre-compact-context-warning";
import { memoryInjectBuiltin } from "./memory-inject";
import { costWarnOverBudgetBuiltin } from "./cost-warn-over-budget";

/** Registry indexed by spec.name. Frozen so accidental mutation at
 *  runtime is a type error. */
export const BUILTIN_HOOKS: Readonly<Record<string, BuiltinHookSpec>> =
  Object.freeze({
    [slackApprovalBuiltin.name]: slackApprovalBuiltin,
    [preCompactContextWarningBuiltin.name]: preCompactContextWarningBuiltin,
    [memoryInjectBuiltin.name]: memoryInjectBuiltin,
    [costWarnOverBudgetBuiltin.name]: costWarnOverBudgetBuiltin,
  });

/** Lookup by name. Returns undefined when the name doesn't match any
 *  registered builtin (e.g. an operator-saved hook references a builtin
 *  that was removed in a later release). */
export function getBuiltinHook(name: string): BuiltinHookSpec | undefined {
  return BUILTIN_HOOKS[name];
}

/** List all registered builtin specs in display-name order. Used by the
 *  `/api/agent/hooks/builtins` route to populate the /settings/hooks
 *  builtin dropdown. */
export function listBuiltinHooks(): BuiltinHookSpec[] {
  return Object.values(BUILTIN_HOOKS).sort((a, b) =>
    a.displayName.localeCompare(b.displayName),
  );
}

export type { BuiltinHookSpec, BuiltinConfigField, BuiltinConfigValidation } from "./types";
