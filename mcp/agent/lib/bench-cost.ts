/**
 * How the benchmark pages show a cost. A case or run whose model calls had no
 * known price carries `null`, and shows as "unpriced": $0.0000 would pass for a
 * free run. Erasable TypeScript only (a node test loads this file directly).
 */

export function formatBenchCost(usd: number | null | undefined): string {
  return typeof usd === 'number' && Number.isFinite(usd) ? `$${usd.toFixed(4)}` : 'unpriced';
}

/** "p50 / p95" in one cell; each side is its own value, so a mix reads honestly. */
export function formatBenchCostPair(p50: number | null | undefined, p95: number | null | undefined): string {
  return `${formatBenchCost(p50)} / ${formatBenchCost(p95)}`;
}

/** A head-minus-base cost change, or null when either side has no price to compare. */
export function benchCostDelta(base: number | null | undefined, head: number | null | undefined): number | null {
  if (typeof base !== 'number' || typeof head !== 'number') return null;
  if (!Number.isFinite(base) || !Number.isFinite(head)) return null;
  return head - base;
}
