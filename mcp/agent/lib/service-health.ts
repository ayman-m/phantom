/**
 * Maps the payload of GET /api/agent/health onto the rows of the /settings
 * Services page.
 *
 * The health route probes four things server-side (xlog-api, phantom-mcp,
 * phantom-agent, caldera). /settings lists five services, so the embedded
 * sqlite stores borrow the phantom-mcp probe: they live inside that process,
 * exactly as the Pipeline page's "Storage rollup" treats them.
 *
 * Pure functions, no I/O, so the mapping is unit-tested
 * (scripts/test-service-health.mjs).
 */

export type ServiceHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface HealthProbe {
  id: string;
  status: "ok" | "failed" | "skipped";
  httpStatus?: number;
  latencyMs?: number;
  error?: string;
}

export interface HealthPayload {
  checkedAt?: string;
  probes?: HealthProbe[];
}

export interface ServiceHealthRow {
  status: ServiceHealth;
  /** Probe latency in ms; null when the probe did not run or did not answer. */
  latencyMs: number | null;
  /** ISO timestamp of the check; null when the health route was unreachable. */
  checkedAt: string | null;
}

const UNKNOWN: ServiceHealthRow = { status: "unknown", latencyMs: null, checkedAt: null };

/**
 * `probeId` is the id the health route uses for that service; `null` means the
 * service has no probe of its own and reports "unknown" rather than a guess.
 */
export function serviceHealthRow(
  payload: HealthPayload | null | undefined,
  probeId: string | null,
): ServiceHealthRow {
  if (!payload || !probeId) return UNKNOWN;
  const probe = payload.probes?.find((p) => p.id === probeId);
  if (!probe) return UNKNOWN;
  const checkedAt = payload.checkedAt ?? null;
  if (probe.status === "ok") {
    return { status: "healthy", latencyMs: probe.latencyMs ?? null, checkedAt };
  }
  if (probe.status === "failed") {
    return { status: "unhealthy", latencyMs: probe.latencyMs ?? null, checkedAt };
  }
  return { status: "unknown", latencyMs: null, checkedAt };
}

/** Counts rows by language root ("Python 3.12 / FastAPI" -> "Python"), in first-seen order. */
export function languageCounts(languages: readonly string[]): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const language of languages) {
    const root = language.trim().split(/\s+/)[0] || "Other";
    counts.set(root, (counts.get(root) ?? 0) + 1);
  }
  return [...counts.entries()];
}
