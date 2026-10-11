import { apiRequest, listRequest } from "./client";
import type { ApiRequestOptions, ApiResult } from "./client";
import type { Approval, ApprovalResolution } from "./types";

// ─── Wire-shape normalizer ────────────────────────────────────────────────────
//
// MCP `bus.list_pending() / bus.list_recent()` (see
// usecase/approvals_bus.py:ApprovalRecord.to_dict) emits:
//
//   { id, created_at, resolved_at, tool, namespaced, actor, resolver,
//     status, args, reason, risk_tier }
//
// The UI's `Approval` type (lib/api/types.ts) uses camelCase
// (`toolName`, `agentId`, `createdAt`, `resolvedAt`, `description`).
// We normalize at the API boundary so the Approvals page (both Pending
// and Resolved tabs), the unread-badge in the sidebar, and the SSE
// refresher all read a consistent shape — this is what was making the
// Resolved tab look empty: list_recent() returns approved/denied rows
// fine, but the listRequest helper didn't recognize the `{approvals:
// [...]}` envelope and silently returned [].
interface MCPApprovalRow {
  id?: string;
  created_at?: string;
  resolved_at?: string | null;
  tool?: string;
  namespaced?: string;
  actor?: string | null;
  resolver?: string | null;
  status?: string;
  args?: Record<string, unknown>;
  reason?: string | null;
  risk_tier?: string;
  /** Surface that requested the approval. Format e.g.
   *  "chat:<session_id>", "job:<name>", "api", "operator", "unknown". */
  origin?: string;
}

function normalizeStatus(s: string | undefined): Approval["status"] {
  switch (s) {
    case "pending":
    case "approved":
    case "denied":
    case "expired":
      return s;
    case "timeout":
      // MCP bus reports "timeout"; UI groups it under expired so the
      // Resolved tab doesn't sprout a fourth column for the corner case.
      return "expired";
    default:
      return "pending";
  }
}

/** Map one MCP approval row → UI's camelCase `Approval`. */
export function normalizeApproval(row: unknown): Approval {
  const r = (row ?? {}) as MCPApprovalRow & Partial<Approval>;
  // Already-normalized (has camelCase fields) → pass through. Lets the
  // resolveApproval() POST response flow through the same code path.
  if (typeof r.toolName === "string" && typeof r.createdAt === "string") {
    return r as Approval;
  }
  const tool = r.tool ?? r.namespaced ?? "(unknown)";
  // The MCP doesn't carry a separate runId / agentId on approvals —
  // every approval is "this tool, requested by this actor". Map both
  // to actor so the UI has something concrete to render; if we later
  // add proper run linkage, only this normalizer changes.
  const actor = r.actor ?? "agent";
  return {
    id: String(r.id ?? ""),
    runId: actor,
    agentId: actor,
    toolName: tool,
    description:
      typeof r.reason === "string" && r.reason.length > 0
        ? r.reason
        : `Tool call: ${tool}`,
    status: normalizeStatus(r.status),
    createdAt: r.created_at ?? new Date().toISOString(),
    resolvedAt: r.resolved_at ?? undefined,
    origin: typeof r.origin === "string" && r.origin.length > 0
      ? r.origin
      : "unknown",
  };
}

/** List approvals from GET /api/v1/approvals, optionally filtered by status.
 *  Normalizes the MCP `{approvals: [...], count}` envelope and field shape
 *  into the UI's `Approval` array. */
export async function listApprovals(
  params?: { status?: string },
  options?: ApiRequestOptions,
): Promise<ApiResult<Approval[]>> {
  const query = params?.status
    ? `?status=${encodeURIComponent(params.status)}`
    : "";
  const result = await listRequest<unknown>(
    `/api/v1/approvals${query}`,
    options,
  );
  if (!result.ok) return result;
  return { ok: true, data: result.data.map(normalizeApproval) };
}

/** What the install gates, from GET /api/agent/approvals/gating (the bundle
 *  manifest's approvals.humanRequired — the same list the chat route
 *  reads). */
export interface ApprovalGating {
  gated: string[];
  count: number;
  known: boolean;
}

/** Which tools wait for an approval card on this install. Resolves null when
 *  the call fails or the manifest could not be read, so callers keep their
 *  normal view instead of claiming "nothing is gated" on a failed read. */
export async function fetchApprovalGating(): Promise<ApprovalGating | null> {
  try {
    const res = await fetch("/api/agent/approvals/gating", { cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as ApprovalGating;
    return data.known === true && typeof data.count === "number" ? data : null;
  } catch {
    return null;
  }
}

/** Approve an approval request via POST /api/v1/approvals/:id/approve. */
export function approveApproval(id: string, options?: ApiRequestOptions) {
  return apiRequest<Approval>(
    `/api/v1/approvals/${encodeURIComponent(id)}/approve`,
    { ...options, method: "POST" },
  );
}

/** Deny an approval request via POST /api/v1/approvals/:id/deny. */
export function denyApproval(id: string, options?: ApiRequestOptions) {
  return apiRequest<Approval>(
    `/api/v1/approvals/${encodeURIComponent(id)}/deny`,
    { ...options, method: "POST" },
  );
}

/** Resolve an approval via POST /api/v1/approvals/:id/resolve.
 *
 * MCP body format: `{decision, reason?}` — translate from the UI's
 * `{resolution}` payload here so the Approvals page can keep its
 * existing call signature. The response is `{approval: {...mcp shape}}`;
 * we unwrap and normalize so callers get a clean `Approval`. */
export async function resolveApproval(
  id: string,
  resolution: ApprovalResolution,
  options?: ApiRequestOptions,
): Promise<ApiResult<Approval>> {
  const result = await apiRequest<{ approval?: unknown } | unknown>(
    `/api/v1/approvals/${encodeURIComponent(id)}/resolve`,
    {
      ...options,
      method: "POST",
      body: {
        decision: resolution.resolution,
        reason: resolution.resolvedBy ?? null,
      },
    },
  );
  if (!result.ok) return result;
  const raw =
    typeof result.data === "object" &&
    result.data !== null &&
    "approval" in result.data
      ? (result.data as { approval: unknown }).approval
      : result.data;
  return { ok: true, data: normalizeApproval(raw) };
}
