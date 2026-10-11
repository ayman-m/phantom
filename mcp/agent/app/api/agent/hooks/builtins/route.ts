/**
 * Hooks builtin catalog.
 *
 * Serves the in-image registry of builtin hook specs to `/settings/hooks`.
 * Unlike `/api/agent/hooks`, this route does NOT proxy to the MCP — the
 * builtin registry is a TypeScript-side concept (`lib/hook-builtins/`)
 * and the MCP has no knowledge of it. Operators install a builtin by
 * POSTing a hook with `transport.type === "builtin"` + `transport.name`;
 * the MCP just stores the JSON blob and trusts the agent-side validator
 * to enforce that `transport.name` resolves in the current image.
 *
 * Shape:
 *   GET /api/agent/hooks/builtins
 *     -> {
 *          builtins: Array<{
 *            name, displayName, description, icon,
 *            compatibleEvents, configFields,
 *          }>,
 *          count
 *        }
 *
 * The `validateConfig` + `handle` functions are intentionally omitted
 * from the response — those are server-side concerns the browser can't
 * use. The UI only needs metadata + form fields.
 */

import { NextResponse } from "next/server";

import { listBuiltinHooks } from "@/lib/hook-builtins";

export const dynamic = "force-dynamic";

export async function GET() {
  const specs = listBuiltinHooks();
  return NextResponse.json({
    builtins: specs.map((spec) => ({
      name: spec.name,
      displayName: spec.displayName,
      description: spec.description,
      icon: spec.icon,
      compatibleEvents: spec.compatibleEvents,
      configFields: spec.configFields,
    })),
    count: specs.length,
  });
}
