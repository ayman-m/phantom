/**
 * Single-connector detail endpoint. Looks up the requested id in the
 * same hard-curated list served by /api/marketplace/connectors and
 * returns it (or 404). Detail panel on the connectors page uses this.
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  // Fetch the catalog from our own /api/marketplace/connectors endpoint.
  // Server-to-server fetch needs an absolute URL.
  const base = (
    process.env.PHANTOM_AGENT_INTERNAL_URL || "http://localhost:3000"
  ).replace(/\/+$/, "");
  const r = await fetch(`${base}/api/marketplace/connectors`, {
    cache: "no-store",
  });
  if (!r.ok) return NextResponse.json({ error: "catalog unavailable" }, { status: 502 });
  const list = (await r.json()) as Array<{ id: string }>;
  const found = list.find((c) => c.id === id);
  if (!found) return NextResponse.json({ error: "not found" }, { status: 404 });
  return NextResponse.json(found);
}
