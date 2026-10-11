/**
 * Category-to-badge mapping.
 *
 * Raw category names come from Cortex pack_metadata.json (verbose taxonomy
 * mirroring the upstream content marketplace). The UI surfaces a short
 * 1-2 word badge so the operator can read a vendor card at a glance.
 *
 * Edit policy: this map is the SINGLE source of truth for which badges
 * exist. Adding a new badge starts here. Categories not in this map
 * fall through to a "Other" badge so untaxed packs still show something.
 *
 * Ordering matters for the OUTER vendor card: when a vendor groups N packs
 * with M distinct categories between them, we dedupe and show up to 4
 * badges in BADGE_PRIORITY_ORDER. SIEM-first because that's the dominant
 * use case in the Phantom catalog (81 of 197 packs).
 */

export const CATEGORY_LABELS: Record<string, string> = {
  // Cortex catalog taxonomy → short UI badge
  "Analytics & SIEM": "SIEM",
  "Network Security": "Network",
  Endpoint: "EDR",
  "Cloud Security": "Cloud",
  "Cloud Services": "Cloud",
  "Cloud Service Provider": "Cloud Provider",
  "Identity and Access Management": "IAM",
  "Data Enrichment & Threat Intelligence": "Threat Intel",
  Email: "Email",
  "Vulnerability Management": "Vuln",
  "IT Services": "IT",
  "CI/CD": "DevOps",
  Forensics: "Forensics",
  Database: "Database",
  Messaging: "Messaging",
  Authentication: "Auth",
  Utilities: "Utility",
};

/**
 * Display order for badges when a vendor has more than 4 categories.
 * Keep the most-distinguishing badges first.
 */
export const BADGE_PRIORITY_ORDER: string[] = [
  "SIEM",
  "EDR",
  "Network",
  "Cloud",
  "Cloud Provider",
  "IAM",
  "Threat Intel",
  "Email",
  "Vuln",
  "Auth",
  "DevOps",
  "Database",
  "Messaging",
  "Forensics",
  "Utility",
  "IT",
  "Other",
];

/**
 * Map raw pack categories to short UI badges, dedupe, and cap at maxBadges.
 * Stable sort by BADGE_PRIORITY_ORDER so card-to-card ordering is consistent.
 */
export function mapCategoriesToBadges(
  rawCategories: string[],
  maxBadges = 4,
): string[] {
  if (!rawCategories || rawCategories.length === 0) return [];
  const seen = new Set<string>();
  for (const raw of rawCategories) {
    const badge = CATEGORY_LABELS[raw] ?? "Other";
    seen.add(badge);
  }
  const order = new Map(BADGE_PRIORITY_ORDER.map((b, i) => [b, i]));
  return Array.from(seen)
    .sort((a, b) => (order.get(a) ?? 999) - (order.get(b) ?? 999))
    .slice(0, maxBadges);
}

/**
 * Strip "agentix" from a supportedModules array.
 * Every pack in the Cortex catalog supports agentix, so showing it as a
 * pill on every card is pure noise. This helper is the one place to
 * apply the filter so the rule lives in one location.
 */
export function filterAgentix(modules: string[]): string[] {
  if (!modules) return [];
  return modules.filter((m) => m.toLowerCase() !== "agentix");
}
