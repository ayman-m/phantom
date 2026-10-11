/**
 * /api/agent/openapi — OpenAPI 3.0 spec for the agent UI's REST surface.
 *
 * Generated from lib/api-catalog.ts at request time. Cheap to compute
 * (~50 entries) and lets the catalog stay the single source of truth:
 * editing an endpoint description or example automatically flows into
 * the spec download.
 *
 * Use cases:
 *   - Operators paste the JSON into Swagger UI / Redoc / Postman to
 *     get an interactive client.
 *   - CI / lint tools validate that example bodies still match the
 *     declared schemas.
 *   - The /help/api detail page fetches per-endpoint snippets from
 *     the same generator (so the on-page snippet matches the
 *     downloadable spec exactly).
 *
 * Two output formats:
 *   - Default JSON (Content-Type: application/json)
 *   - YAML when ?format=yaml (Content-Type: application/yaml)
 *     useful for `git`-friendly spec checks-in.
 */

import { NextResponse } from "next/server";

import { generateOpenApiSpec } from "@/lib/openapi-generator";
// jsonToYaml lives in lib/ so it can be
// unit-tested without dragging in Next.js / OpenAPI generator surface.
// Test fixtures live in scripts/test-json-to-yaml.mjs.
import { jsonToYaml } from "@/lib/json-to-yaml";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const format = (url.searchParams.get("format") ?? "json").toLowerCase();
  // Use the request's host so the spec's `servers[0].url` matches
  // however the operator reached this route. Avoids "localhost:3000"
  // hard-coded into a spec downloaded from the deployed VM.
  const proto = request.headers.get("x-forwarded-proto") ?? "http";
  const host = request.headers.get("host") ?? "localhost:3000";
  const spec = generateOpenApiSpec({ serverUrl: `${proto}://${host}` });

  if (format === "yaml" || format === "yml") {
    // Defense in depth: a YAML-conversion crash should return a
    // 500 with a real error body, not the bare empty 500 Next.js
    // emits when an exception escapes the route handler. Operator-
    // visible: the modal can show the failure message instead of
    // "loading…" forever.
    try {
      const body = jsonToYaml(spec);
      return new NextResponse(body, {
        status: 200,
        headers: {
          "Content-Type": "application/yaml; charset=utf-8",
          "Content-Disposition": 'inline; filename="phantom-agent-openapi.yaml"',
        },
      });
    } catch (err) {
      return new NextResponse(
        `# YAML conversion failed: ${err instanceof Error ? err.message : String(err)}\n# Falling back to JSON download is recommended.\n`,
        {
          status: 500,
          headers: { "Content-Type": "application/yaml; charset=utf-8" },
        },
      );
    }
  }

  // Default JSON. Pretty-printed for human eyeballs; the file size
  // (~50 endpoints) is small enough that compaction isn't worth the
  // worse readability.
  return new NextResponse(JSON.stringify(spec, null, 2), {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": 'inline; filename="phantom-agent-openapi.json"',
    },
  });
}
