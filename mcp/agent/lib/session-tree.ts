/**
 * Ordering behind the chat sidebar's session list: sessions are bucketed by
 * date, and a forked session is listed directly under its parent, indented
 * one level per generation.
 *
 * Kept free of imports and of non-erasable TypeScript so
 * scripts/test-session-tree.mjs can load this file directly with Node's type
 * stripping. The sidebar imports the function from here, so the test
 * exercises the same code the page runs.
 */

export type DateGroup = "Today" | "Yesterday" | "Previous 7 Days" | "Older";

export const DATE_GROUP_ORDER: DateGroup[] = [
  "Today",
  "Yesterday",
  "Previous 7 Days",
  "Older",
];

/** The fields the ordering reads; the sidebar's SessionSummary satisfies it. */
export interface TreeSession {
  id: string;
  timestamp: string;
  parentId?: string | null;
}

export interface TreeRow<T extends TreeSession> {
  session: T;
  /**
   * Generations below the tree's root: 0 for a root, 1 for a fork of a root,
   * and so on. A fork whose parent is not in the list (deleted, or paged
   * out) is a root of its own tree and has depth 0.
   */
  depth: number;
}

export interface DateBucket<T extends TreeSession> {
  group: DateGroup;
  rows: TreeRow<T>[];
}

export function dateGroupOf(timestamp: string, now: Date): DateGroup {
  const date = new Date(timestamp);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const sevenDaysAgo = new Date(today);
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

  if (date >= today) return "Today";
  if (date >= yesterday) return "Yesterday";
  if (date >= sevenDaysAgo) return "Previous 7 Days";
  return "Older";
}

function epoch(timestamp: string): number {
  const t = Date.parse(timestamp);
  return Number.isNaN(t) ? 0 : t;
}

/**
 * Bucket sessions by date and order each bucket as a forest.
 *
 * - A tree takes its date bucket from its ROOT, so a parent and its forks
 *   stay together even when a fork was made on a later day.
 * - Roots are listed newest first; under each root, forks follow
 *   depth-first, newest sibling first, so a fork's own forks sit directly
 *   beneath it.
 * - A parent cycle (corrupt data) cannot loop: sessions the walk from the
 *   real roots never reaches are promoted to roots, newest first.
 * - Empty buckets are omitted.
 */
export function groupSessionTree<T extends TreeSession>(
  sessions: T[],
  now: Date,
): DateBucket<T>[] {
  const byId = new Map<string, T>();
  for (const s of sessions) byId.set(s.id, s);

  const children = new Map<string, T[]>();
  const roots: T[] = [];
  for (const s of sessions) {
    const pid = s.parentId;
    if (pid && pid !== s.id && byId.has(pid)) {
      const list = children.get(pid);
      if (list) list.push(s);
      else children.set(pid, [s]);
    } else {
      roots.push(s);
    }
  }

  const newestFirst = (a: T, b: T) => epoch(b.timestamp) - epoch(a.timestamp);
  roots.sort(newestFirst);
  for (const list of children.values()) list.sort(newestFirst);

  const visited = new Set<string>();
  const ordered: Array<{ root: T; rows: TreeRow<T>[] }> = [];

  function walk(s: T, depth: number, out: TreeRow<T>[]): void {
    if (visited.has(s.id)) return;
    visited.add(s.id);
    out.push({ session: s, depth });
    for (const child of children.get(s.id) ?? []) walk(child, depth + 1, out);
  }

  for (const root of roots) {
    const rows: TreeRow<T>[] = [];
    walk(root, 0, rows);
    ordered.push({ root, rows });
  }
  // Anything left is on a parent cycle: promote it to a root.
  const stranded = sessions.filter((s) => !visited.has(s.id)).sort(newestFirst);
  for (const s of stranded) {
    if (visited.has(s.id)) continue;
    const rows: TreeRow<T>[] = [];
    walk(s, 0, rows);
    ordered.push({ root: s, rows });
  }

  // Promoted cycle roots were appended after the real roots; one sort puts
  // every tree in newest-root-first order (Array.sort is stable).
  ordered.sort((a, b) => newestFirst(a.root, b.root));
  const buckets = new Map<DateGroup, TreeRow<T>[]>();
  for (const g of DATE_GROUP_ORDER) buckets.set(g, []);
  for (const { root, rows } of ordered) {
    buckets.get(dateGroupOf(root.timestamp, now))!.push(...rows);
  }
  const out: DateBucket<T>[] = [];
  for (const g of DATE_GROUP_ORDER) {
    const rows = buckets.get(g)!;
    if (rows.length > 0) out.push({ group: g, rows });
  }
  return out;
}
