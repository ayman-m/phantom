/**
 * GET /api/agent/models - the model registry as a bare JSON array.
 *
 * One list serves the /models pages, the chat header's picker, the jobs form
 * and the bench form. Each element merges the curated catalog with the
 * provider's live model list (see lib/providers/registry/registry.ts) and adds
 * `ref`, `availability`, `selectable`, `reason`, `pricing`, `lifecycle`,
 * `liveSeenAt`, `source`, `isDefault` and, on the default row, `defaultSource`
 * ("default" when the install's `defaultModel` setting serves, "derived" when no
 * usable default is set and the first configured provider's recommended model
 * does). Retired models are left out unless `?include_retired=1`.
 *
 * The body is built by `listModelsForApi` (lib/model-registry-server.ts); a
 * Next route file may export nothing but its handlers.
 */

import { NextResponse } from "next/server";
import { listModelsForApi } from "@/lib/model-registry-server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const includeRetired = new URL(request.url).searchParams.get("include_retired") === "1";
  return NextResponse.json(await listModelsForApi({ includeRetired }));
}
