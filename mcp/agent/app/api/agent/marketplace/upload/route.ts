/**
 * POST /api/agent/marketplace/upload
 *
 * Multipart proxy to MCP's POST /api/v1/marketplace/upload. The
 * client sends FormData with one required field `connector_yaml`
 * (file content of the connector.yaml, optionally with an embedded
 * `logo: data:image/...;base64,...` field). The backend validates
 * the YAML against connector.schema.json + collision checks before
 * persisting to /app/data/user_connectors/<id>/connector.yaml.
 *
 * Why multipart and not JSON: connector.yaml files can carry an
 * embedded base64 logo data URI which gets large (up to ~260 KB).
 * application/json with a string field would force the operator's
 * browser to base64-decode + re-encode the YAML for transport,
 * which is wasted work. multipart/form-data lets us send the raw
 * YAML bytes through unchanged.
 *
 * Forwarding rule: we re-stream the request body and Content-Type
 * unmodified. fetch() handles multipart boundaries correctly when
 * the Body is the original Request's body — we just pass it through.
 */

import { NextRequest, NextResponse } from "next/server";

import { resolveMcp } from "@/lib/mcp-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const r = await resolveMcp();
  if (r instanceof NextResponse) return r;

  // Pass the multipart body through verbatim. Node's undici fetch
  // accepts a ReadableStream body + preserves the original
  // Content-Type (including the multipart boundary) when we copy
  // the header in explicitly. Don't try to parse + reconstruct
  // FormData here — that loses the boundary and breaks the upload.
  const contentType = request.headers.get("content-type");
  if (!contentType || !contentType.startsWith("multipart/form-data")) {
    return NextResponse.json(
      { error: "Content-Type must be multipart/form-data" },
      { status: 400 },
    );
  }
  // Read the raw body as a buffer so we can pass it to fetch
  // unchanged. Streaming through fetch's `body` parameter has
  // edge cases with Node's undici when the source is a Request
  // body — buffering is safer for the ~1 MB-max payload size
  // we expect here (YAML + base64 logo).
  const body = await request.arrayBuffer();

  try {
    const upstream = await fetch(`${r.base}/api/v1/marketplace/upload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${r.token}`,
        "Content-Type": contentType,
      },
      body,
    });
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: `MCP unreachable: ${
          err instanceof Error ? err.message : err
        }`,
      },
      { status: 502 },
    );
  }
}
