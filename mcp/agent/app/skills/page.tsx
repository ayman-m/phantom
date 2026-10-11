"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ImportSkillButton } from "./import-button";

// ─── Types ───────────────────────────────────────────────────────────────────

// Phantom skill categories mirror the on-disk layout under
// bundles/spark/mcp/skills/ — foundation primitives, scenario
// runbooks, validation queries, end-to-end workflows, and
// plugin-contributed skills under plugins/<vendor>/<skill>.md.
type CategoryKey =
  | "all"
  | "foundation"
  | "scenarios"
  | "validation"
  | "workflows"
  | "plugins";

type SourceType = "platform" | "workspace" | "managed" | "plugin";
type LoadingMode = "always" | "on-demand";

interface SkillDef {
  id: string;
  name: string;
  displayName: string;
  category: Exclude<CategoryKey, "all">;
  description: string;
  icon: string;
  source: SourceType;
  loadingMode: LoadingMode;
  enabled: boolean;
  locked: boolean;
  agentCount: number;
  calls7d: number;
  content: string;
  charCount: number;
  tokenCount: number;
  maxConcurrentAgents: number;
  eligibleAgents: string;
  analytics: {
    calls24h: number;
    calls7d: number;
    calls30d: number;
    avgContextTokens: number;
    activeAgents: number;
    topAgents: { name: string; color: string }[];
  };
}

// ─── Constants ───────────────────────────────────────────────────────────────

const CATEGORY_META: Record<
  Exclude<CategoryKey, "all">,
  { label: string; icon: string; color: string; bg: string; border: string; iconBg: string }
> = {
  // Unified tint — mixed blue/green/orange icons across categories
  // looked inconsistent. Each card already
  // carries its category as a labeled chip (so the meaning is preserved
  // without the icon hue carrying it). All four categories now use
  // primary blue tints, which read as a single design language and
  // matches the rest of the app's blue-anchored chrome.
  foundation: {
    label: "Foundation",
    icon: "foundation",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  scenarios: {
    label: "Scenarios",
    icon: "campaign",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  validation: {
    label: "Validation",
    icon: "fact_check",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  workflows: {
    label: "Workflows",
    icon: "workflow",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
  plugins: {
    label: "Plugins",
    icon: "extension",
    color: "text-primary",
    bg: "bg-primary/10",
    border: "border-primary/30",
    iconBg: "bg-primary/15",
  },
};

const SOURCE_META: Record<SourceType, { label: string; className: string }> = {
  platform: { label: "PLATFORM", className: "text-on-surface-variant bg-surface-container-high" },
  workspace: { label: "WORKSPACE", className: "text-primary border border-primary/30" },
  managed: { label: "MANAGED", className: "text-secondary border border-secondary/30" },
  // Plugin-contributed skills shipped under plugins/<vendor>/.
  // Vendor name is surfaced in the row's `plugin_vendor` field; this
  // chip just marks "this didn't come from the bundle's built-in
  // categories" without committing to a specific vendor's brand colour.
  plugin: { label: "PLUGIN", className: "text-tertiary border border-tertiary/30" },
};

// Counts in CATEGORY_FILTERS are hardcoded fallbacks for
// the SSR / first-paint case before the live /api/skills response
// lands. Once skills are loaded, the page renders the actual filtered
// counts on the chips via the live `skills` array (see the rendered
// pill row — count comes from a useMemo there). Plugin-contributed
// skills may or may not be present at install time depending on
// what the operator has configured.
const CATEGORY_FILTERS: { key: CategoryKey; label: string; count: number }[] = [
  { key: "all", label: "All", count: 0 },
  { key: "foundation", label: "Foundation", count: 0 },
  { key: "scenarios", label: "Scenarios", count: 0 },
  { key: "validation", label: "Validation", count: 0 },
  { key: "workflows", label: "Workflows", count: 0 },
  { key: "plugins", label: "Plugins", count: 0 },
];

// Summary stats are computed from the live `skills` array (see
// SkillsPage::summaryStats useMemo) rather than hardcoded, so they
// cannot drift out of sync with what /api/skills returns.
//
// Caption + delta strings are still constants because they don't
// depend on the live count — operators can read them as static
// help text.
const SUMMARY_CAPTIONS = {
  totalCaption: "Registered skills",
  invocationsDelta: "Tracking not yet implemented",
} as const;

// Phantom is single-tenant — there are no workspaces. The Workspaces
// column on the skill detail panel still exists in the UI but the
// data is empty. Future work: drop the entire workspace section from
// the detail panel.
const DEFAULT_WORKSPACES: { name: string; slug: string; icon: string; enabled: boolean }[] = [];

// ─── Mock Data ──────────────────────────────────────────────────────────────

// ─── Phantom Skills (sourced from bundles/spark/mcp/skills/*) ─────────────
//
// Skills shipped with the bundle, organized by the
// on-disk layout:
//   foundation/  — primitive helpers (IOC generation, topology) — 5 skills
//   scenarios/   — named ATT&CK scenarios — 12 skills
//   workflows/   — multi-step orchestration including build_xql_query — 3 skills
// (There is no separate validation/ category; it lives under workflows/.)
//
// Description text is paraphrased from the skill's MD frontmatter; the
// `content` field is a one-line summary so the detail panel renders
// without freighting the bundle. To pull the live MD body, hit
// /api/skills?file_path=<path> which proxies the MCP's `skills_read`.

const SKILLS: SkillDef[] = [
  // ── Foundation ───────────────────────────────────────────────────────
  {
    id: "foundation-iocs",
    name: "generate_shared_iocs",
    displayName: "Generate shared IOCs",
    category: "foundation",
    description:
      "Pre-generates the indicators (IPs, domains, hashes, users) that downstream scenarios reuse — keeps cross-scenario telemetry coherent.",
    icon: "fingerprint",
    source: "platform",
    loadingMode: "always",
    enabled: true,
    locked: true,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/foundation/generate_shared_iocs.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#00f5ff" }] },
  },
  {
    id: "foundation-topology",
    name: "create_device_topology",
    displayName: "Create device topology",
    category: "foundation",
    description:
      "Materializes a fleet of synthetic devices (workstations, servers, network gear) with realistic naming + IP plans for log generation.",
    icon: "lan",
    source: "platform",
    loadingMode: "always",
    enabled: true,
    locked: true,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/foundation/create_device_topology.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#00f5ff" }] },
  },
  // ── Scenarios ───────────────────────────────────────────────────────
  {
    id: "scenario-knock-knock",
    name: "knock_knock",
    displayName: "Knock-knock (recon)",
    category: "scenarios",
    description:
      "External recon scenario — port scans, banner grabs, DNS enumeration. Drops Stage-1 reconnaissance signals into your XSIAM tenant.",
    icon: "radar",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/knock_knock.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-ink-and-foil",
    name: "ink_and_foil",
    displayName: "Ink & Foil (phishing → C2)",
    category: "scenarios",
    description:
      "Phishing email → malicious attachment → first-stage C2 callback. Exercises detection rules around credential theft + outbound beaconing.",
    icon: "mail_lock",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/ink_and_foil.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-everything-is-now",
    name: "everything_is_now",
    displayName: "Everything is now (lateral)",
    category: "scenarios",
    description:
      "Lateral movement scenario — credential reuse, RDP/WMI/PsExec hops across the synthetic device topology.",
    icon: "device_hub",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/everything_is_now.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-alpha-and-omega",
    name: "alpha_and_omega",
    displayName: "Alpha & Omega (privesc)",
    category: "scenarios",
    description:
      "Local + domain privilege escalation chain — token impersonation, GPO abuse, golden-ticket forging.",
    icon: "shield_with_heart",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/alpha_and_omega.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-sic-mundus",
    name: "sic_mundus_creatus_est",
    displayName: "Sic Mundus Creatus Est (full chain)",
    category: "scenarios",
    description:
      "End-to-end attack chain — recon → initial access → persistence → privesc → exfil. Full coverage exercise.",
    icon: "auto_stories",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/sic_mundus_creatus_est.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-crossroads",
    name: "crossroads",
    displayName: "Crossroads (insider threat)",
    category: "scenarios",
    description:
      "Insider data-exfiltration scenario — abnormal file access, off-hours uploads, USB write events.",
    icon: "fork_right",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/crossroads.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-midnight-butterfly",
    name: "midnight_butterfly",
    displayName: "Midnight butterfly (low-and-slow)",
    category: "scenarios",
    description:
      "Low-and-slow data exfiltration spread over hours/days — DNS tunneling, encrypted side channels, beaconing under threshold.",
    icon: "nights_stay",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/midnight_butterfly.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  // ── Heavy-volume kill chains ─────────────────────────────
  // Each of these models a complete attack chain across multiple ATT&CK
  // tactics with 1-13k synthetic events. Designed for end-to-end
  // detection stress-tests; per-skill detection coverage is documented
  // in the bottom of each MD body.
  {
    id: "scenario-ransomware-double-extortion",
    name: "ransomware_double_extortion",
    displayName: "Ransomware (double extortion)",
    category: "scenarios",
    description:
      "Full LockBit-style chain: phish → PowerShell → LSASS dump → defender tamper → SMB lateral → bulk exfil → file encryption + Volume Shadow delete. ~1.5k events.",
    icon: "lock_open",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/ransomware_double_extortion.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-apt-long-dwell",
    name: "apt_long_dwell_espionage",
    displayName: "APT (long-dwell espionage)",
    category: "scenarios",
    description:
      "Slow-burn nation-state campaign: CVE-2023-22515 exploit + web shell + LDAP recon + low-rate password spray + DNS C2 + tunnelled exfil. ~3k events over 12 simulated hours.",
    icon: "hourglass_empty",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/apt_long_dwell_espionage.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-insider-threat",
    name: "insider_threat_data_theft",
    displayName: "Insider threat (privileged DBA)",
    category: "scenarios",
    description:
      "DBA exfil with HR-resignation pivot: 1k baseline events + cross-unit DB access + bulk dump + USB write + log clearing. ~2.5k events with baseline-vs-anomaly pattern.",
    icon: "person_off",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/insider_threat_data_theft.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-supply-chain-npm",
    name: "supply_chain_npm_compromise",
    displayName: "Supply chain (npm fan-out)",
    category: "scenarios",
    description:
      "Backdoored npm package installs across 30+ build hosts → same-IoC outbound from many sources → secrets sweep → S3 exfil. Tests destination-IoC correlation, not host-level.",
    icon: "account_tree",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/supply_chain_npm_compromise.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-cloud-account-takeover",
    name: "cloud_account_takeover_m365",
    displayName: "Cloud takeover (M365 OAuth)",
    category: "scenarios",
    description:
      "OAuth consent phishing for a finance VP → token-based sign-in → inbox-rule persistence (auto-deletes alerts) → mailbox harvest via Graph + lateral mail. 100% cloud audit telemetry.",
    icon: "cloud_off",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/cloud_account_takeover_m365.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-phishing-credential-harvest",
    name: "phishing_credential_harvest_campaign",
    displayName: "Phishing (mass credential harvest)",
    category: "scenarios",
    description:
      "5k inbound phish → 0.6% click-through → fake portal POST → SSO replay from foreign IPs → MFA-push fatigue → VPN + RDP fan-out. ~6k events.",
    icon: "phishing",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/phishing_credential_harvest_campaign.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-web-app-sqli",
    name: "web_app_sqli_to_rce",
    displayName: "Web app (SQLi → RCE → exfil)",
    category: "scenarios",
    description:
      "External portal compromise: 3k WAF scans (noise) → successful UNION-SELECT SQLi → admin login → file-upload web shell → reverse shell → DB mass-export → exfil via paste/discord.",
    icon: "bug_report",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/web_app_sqli_to_rce.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-living-off-the-land",
    name: "living_off_the_land_lolbin",
    displayName: "Living off the land (LOLBin)",
    category: "scenarios",
    description:
      "Fileless attack via signed Microsoft tools: certutil/mshta/wmic/bitsadmin/msbuild + WMI event-subscription persistence + DoH C2. Pure command-line argument signal.",
    icon: "terminal",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/living_off_the_land_lolbin.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-cryptojacking",
    name: "cryptojacking_xmrig_botnet",
    displayName: "Cryptojacking (XMRig botnet)",
    category: "scenarios",
    description:
      "Redis CONFIG-SET → SSH key drop → Docker API container deploy → cron+systemd persistence + EDR disable → sustained XMRig mining-pool C2 across cloud workloads. ~2.7k events.",
    icon: "memory",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/cryptojacking_xmrig_botnet.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-business-email-compromise",
    name: "business_email_compromise",
    displayName: "BEC (CEO wire-transfer fraud)",
    category: "scenarios",
    description:
      "10-day quiet mailbox dwell + look-alike domain registration + inbox rule that auto-deletes evidence + spoofed CEO wire instruction to AP. No malware — pure social engineering.",
    icon: "mark_email_unread",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/business_email_compromise.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-kubernetes-escape",
    name: "kubernetes_container_escape",
    displayName: "Kubernetes (container escape)",
    category: "scenarios",
    description:
      "Pod RCE → service-account token abuse → privileged pod with hostPath:/ → chroot escape → cluster-admin ClusterRoleBinding + cross-namespace exec. Heavy on kube-audit telemetry.",
    icon: "stack",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/kubernetes_container_escape.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  {
    id: "scenario-ddos-multivector",
    name: "ddos_volumetric_layer7",
    displayName: "DDoS (volumetric + L7)",
    category: "scenarios",
    description:
      "Multi-vector availability attack: DNS+NTP+memcached amplification + TCP SYN flood + L7 HTTP-GET flood + Slowloris. ~13k events to test rate-change alerting.",
    icon: "warning",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/scenarios/ddos_volumetric_layer7.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#1f7bff" }] },
  },
  // ── Validation ──────────────────────────────────────────────────────
  {
    id: "validation-ioc-correlation",
    name: "validate_ioc_correlation",
    displayName: "Validate IOC correlation",
    category: "validation",
    description:
      "Runs XQL queries against the XSIAM tenant to confirm the IOCs from a scenario actually triggered the expected detection rules.",
    icon: "fact_check",
    source: "platform",
    loadingMode: "always",
    enabled: true,
    locked: true,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/validation/validate_ioc_correlation.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#45ffd6" }] },
  },
  // ── Workflows ───────────────────────────────────────────────────────
  {
    id: "workflow-purple-team",
    name: "purple_team_exercise",
    displayName: "Purple-team exercise",
    category: "workflows",
    description:
      "End-to-end purple exercise — pick scenario, run via Caldera + xlog, validate detection in XSIAM, file the postmortem.",
    icon: "groups",
    source: "platform",
    loadingMode: "on-demand",
    enabled: true,
    locked: false,
    agentCount: 1,
    calls7d: 0,
    content: "See bundles/spark/mcp/skills/workflows/purple_team_exercise.md",
    charCount: 0,
    tokenCount: 0,
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: { calls24h: 0, calls7d: 0, calls30d: 0, avgContextTokens: 0, activeAgents: 1, topAgents: [{ name: "phantom", color: "#6a7cff" }] },
  },
];

// ─── Styles ─────────────────────────────────────────────────────────────────

const glassStyle: React.CSSProperties = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
};

const panelStyle: React.CSSProperties = {
  background: "var(--glass-bg-elev)",
  backdropFilter: "blur(16px)",
  borderLeft: "0.5px solid var(--glass-border)",
};

const ghostBorder: React.CSSProperties = {
  border: "0.5px solid var(--glass-border)",
};

// ─── Sub-Components ─────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div
        className="h-[2px] w-16"
        style={{ background: "linear-gradient(90deg, #1963b3 0%, transparent 100%)" }}
      />
      <span className="font-label uppercase tracking-[0.2em] text-[10px] font-black text-on-surface-variant/40">
        {label}
      </span>
    </div>
  );
}

function DangerSectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div
        className="h-[2px] w-16"
        style={{ background: "linear-gradient(90deg, #ef4444 0%, transparent 100%)" }}
      />
      <span className="font-label uppercase tracking-[0.2em] text-[10px] font-black text-[#ffb4ab]/60">
        {label}
      </span>
    </div>
  );
}

function LockBadge({ locked }: { locked: boolean }) {
  if (locked) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1 bg-primary/10 text-primary-fixed-dim border border-primary/30 rounded-lg text-[10px] font-bold">
        <span className="material-symbols-outlined text-sm">lock</span>
        Enforced
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 px-3 py-1 bg-[#424751]/10 text-on-surface-variant/60 border border-[#424751]/20 rounded-lg text-[10px] font-bold">
      <span className="material-symbols-outlined text-sm">lock_open</span>
    </div>
  );
}

function SkillCard({
  skill,
  onSelect,
  onToggleEnabled,
}: {
  skill: SkillDef;
  onSelect: () => void;
  onToggleEnabled: () => void;
}) {
  const cat = CATEGORY_META[skill.category];
  const src = SOURCE_META[skill.source];
  const isDisabled = !skill.enabled;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`p-6 rounded-2xl hover:ring-1 hover:ring-primary/20 transition-all cursor-pointer group ${
        isDisabled ? "opacity-60 grayscale-[0.5]" : ""
      }`}
      style={glassStyle}
    >
      {/* Icon + controls */}
      <div className="flex justify-between mb-6">
        <div
          className={`w-12 h-12 rounded-xl ${cat.iconBg} flex items-center justify-center`}
        >
          <span className={`material-symbols-outlined text-2xl ${cat.color}`}>
            {skill.icon}
          </span>
        </div>
        <div className="flex gap-2 items-center">
          <span
            className={`material-symbols-outlined ${
              skill.locked ? "text-primary-fixed-dim" : "text-on-surface-variant/20"
            }`}
            title={skill.locked ? "Platform Enforced" : "Unlocked"}
          >
            {skill.locked ? "lock" : "lock_open"}
          </span>
          {/* Toggle — was a static <div> that didn't actually toggle.
              Now a real <button> with stopPropagation so clicks don't
              bubble up to the card's onClick (which would open the
              detail panel). Color is primary blue because green washed
              out on the light background. */}
          <button
            type="button"
            role="switch"
            aria-checked={skill.enabled}
            aria-label={
              skill.enabled
                ? `Disable skill ${skill.displayName}`
                : `Enable skill ${skill.displayName}`
            }
            onClick={(e) => {
              e.stopPropagation();
              onToggleEnabled();
            }}
            onKeyDown={(e) => {
              // Don't let Enter/Space bubble to the card's keydown
              // handler (which would also re-open detail).
              if (e.key === "Enter" || e.key === " ") {
                e.stopPropagation();
              }
            }}
            className={`w-10 h-5 rounded-full flex items-center px-1 transition-colors cursor-pointer hover:ring-2 hover:ring-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/40 ${
              skill.enabled
                ? "bg-primary/30"
                : "bg-surface-container-highest"
            }`}
          >
            <div
              className={`w-3.5 h-3.5 rounded-full transition-all ${
                skill.enabled
                  ? "bg-primary ml-auto"
                  : "bg-on-surface-variant/40"
              }`}
            />
          </button>
        </div>
      </div>
      {/* Display name (frontmatter-driven, operator-friendly) +
          canonical name (snake_case, model-facing). `skill.name` is the
          canonical identifier that the agent's chat-prompt sees and
          that skill-binding jobs reference, but it's NOT the operator-
          friendly label. Frontmatter `displayName` is what the card
          shows; the canonical name sits below in monospace as a
          subtitle so operators can still grep by it (helpful when
          troubleshooting "agent says it can't find the skill").
          The font sizing inverts the prior emphasis: displayName is
          the visual primary (text-lg in body font), name is
          secondary (text-xs in monospace under it). */}
      <h3 className="font-headline text-lg font-medium text-on-surface mb-0.5">
        {skill.displayName}
      </h3>
      <p className="font-mono text-xs text-on-surface-variant/60 mb-1">
        {skill.name}
      </p>
      <p className="text-xs font-label text-on-surface-variant uppercase tracking-widest mb-4">
        {cat.label}
      </p>
      <p className="text-sm text-on-surface-variant/70 line-clamp-2 mb-6">
        {skill.description}
      </p>
      {/* Footer */}
      <div className="flex justify-between items-center pt-4 border-t border-outline-variant/30">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-on-surface-variant text-sm">
            <span className="material-symbols-outlined text-lg">group</span>
            <span>{skill.agentCount} agents</span>
          </div>
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-bold ${
              skill.loadingMode === "always"
                ? "text-secondary bg-secondary/10"
                : "text-tertiary bg-tertiary/10"
            }`}
          >
            {skill.loadingMode === "always" ? "ALWAYS" : "ON-DEMAND"}
          </span>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded ${src.className}`}>
          {src.label}
        </span>
      </div>
    </div>
  );
}

function SkillDetailPanel({
  skill,
  onClose,
  onToggleEnabled,
  onDownload,
  onSave,
  onDelete,
}: {
  skill: SkillDef;
  onClose: () => void;
  onToggleEnabled: () => void;
  // The detail panel hosts the per-skill CRUD actions.
  // Download is always available (even for locked skills — viewing
  // and saving locally doesn't mutate state). Save fires when the
  // operator edits the body textarea. Delete is gated by the locked
  // flag in the parent handler, but the button is still rendered
  // (disabled) for discoverability.
  onDownload: (skill: SkillDef) => void;
  onSave: (skill: SkillDef, content: string) => Promise<boolean>;
  onDelete: (skill: SkillDef) => void;
}) {
  const cat = CATEGORY_META[skill.category];
  const [activeRange, setActiveRange] = useState<"24h" | "7d" | "30d">("24h");

  // Local body state. The body auto-loads on panel mount (a lazy-load on
  // click/focus would leave the textarea showing a one-line
  // "See bundles/…" placeholder until you clicked into it, which reads
  // as broken). We hydrate the real MD body via skills_read immediately
  // when the detail panel opens and render a proper loading state in
  // place of the textarea while the fetch is in flight.
  //
  // - `bodyContent`     — the live MD body once loaded, or empty
  //                       string while loading. The seed value
  //                       (skill.content, a one-line filename hint)
  //                       is not used as a textarea
  //                       placeholder; it's only shown if the auto-
  //                       load fails and the operator hasn't clicked
  //                       Retry yet.
  // - `loadState`       — "loading" | "loaded" | "error". Replaces
  //                       the older bodyLoaded + isLoading boolean
  //                       pair so the three rendering modes are an
  //                       explicit enum.
  // - `loadError`       — operator-facing message shown next to the
  //                       Retry button on `loadState === "error"`.
  // - `isSaving`, `dirty` — Save / unsaved-change tracking, unchanged.
  const [bodyContent, setBodyContent] = useState("");
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">(
    "loading",
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const loadBody = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const filePath = `${skill.category}/${skill.name}.md`;
      const res = await fetch(
        `/api/skills?file_path=${encodeURIComponent(filePath)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        setLoadError(`Server returned ${res.status}`);
        setLoadState("error");
        return;
      }
      const body = (await res.json()) as {
        success: boolean;
        content?: string;
        error?: string;
      };
      if (body.success && typeof body.content === "string") {
        setBodyContent(body.content);
        setLoadState("loaded");
        setDirty(false);
      } else {
        setLoadError(body.error || "Empty response from /api/skills");
        setLoadState("error");
      }
    } catch (err) {
      setLoadError(
        err instanceof Error
          ? err.message
          : "Network error reaching /api/skills",
      );
      setLoadState("error");
    }
  }, [skill.category, skill.name]);

  // Auto-load on mount (and whenever the panel switches to a
  // different skill — though today the parent unmounts + remounts
  // the panel for each selection, so the dependency change is just
  // belt-and-suspenders).
  useEffect(() => {
    void loadBody();
  }, [loadBody]);

  const isLoading = loadState === "loading";
  const bodyLoaded = loadState === "loaded";

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-[2px] animate-[fadeIn_0.2s_ease-out]"
        onClick={() => {
          if (
            dirty &&
            !window.confirm("Unsaved changes — close anyway?")
          )
            return;
          onClose();
        }}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 h-full w-[55%] z-50 shadow-[0_0_80px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col animate-[slideInRight_0.3s_ease-out]"
        style={panelStyle}
      >
        {/* Header */}
        <header className="p-8 pb-6 border-b border-white/5 shrink-0">
          <div className="flex items-start justify-between mb-6">
            <button
              onClick={() => {
                if (
                  dirty &&
                  !window.confirm("Unsaved changes — close anyway?")
                )
                  return;
                onClose();
              }}
              className="w-10 h-10 rounded-full flex items-center justify-center bg-white/5 hover:bg-white/10 transition-all active:scale-95 group"
              aria-label="Close panel"
            >
              <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary-fixed-dim">
                arrow_back
              </span>
            </button>
            {/* Per-skill CRUD action row. Download / Save /
                Delete sit between the back button and the category
                badges. Save is enabled only when the body is dirty.
                Delete is disabled-with-tooltip for locked skills. */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => onDownload(skill)}
                className="h-9 px-3 flex items-center gap-1.5 rounded-full bg-white/5 hover:bg-white/10 transition-all active:scale-95 text-xs font-medium text-on-surface-variant hover:text-on-surface"
                title="Download as .md file"
                aria-label={`Download ${skill.displayName}`}
              >
                <span className="material-symbols-outlined text-base">
                  download
                </span>
                Download
              </button>
              <button
                onClick={async () => {
                  if (!dirty || isSaving) return;
                  setIsSaving(true);
                  const ok = await onSave(skill, bodyContent);
                  setIsSaving(false);
                  if (ok) setDirty(false);
                }}
                disabled={!dirty || isSaving}
                className={`h-9 px-3 flex items-center gap-1.5 rounded-full transition-all text-xs font-medium ${
                  dirty && !isSaving
                    ? "bg-primary/20 hover:bg-primary/30 text-primary-fixed-dim active:scale-95"
                    : "bg-white/5 text-on-surface-variant/40 cursor-not-allowed"
                }`}
                title={
                  dirty
                    ? "Save body changes"
                    : "No unsaved changes"
                }
                aria-label="Save edits"
              >
                <span className="material-symbols-outlined text-base">
                  {isSaving ? "hourglass_empty" : "save"}
                </span>
                {isSaving ? "Saving…" : "Save"}
              </button>
              <button
                onClick={() => {
                  if (skill.locked) return;
                  onDelete(skill);
                }}
                disabled={skill.locked}
                className={`h-9 px-3 flex items-center gap-1.5 rounded-full transition-all text-xs font-medium ${
                  skill.locked
                    ? "bg-white/5 text-on-surface-variant/30 cursor-not-allowed"
                    : "bg-red-500/10 hover:bg-red-500/20 text-red-300 hover:text-red-200 active:scale-95"
                }`}
                title={
                  skill.locked
                    ? "Platform-locked — can't be deleted"
                    : "Soft-delete (recoverable from .deleted/)"
                }
                aria-label={`Delete ${skill.displayName}`}
              >
                <span className="material-symbols-outlined text-base">
                  delete
                </span>
                Delete
              </button>
            </div>
            <div className="flex gap-2">
              <span
                className={`px-3 py-1 ${cat.bg} ${cat.border} border rounded-full text-[10px] uppercase tracking-widest font-bold ${cat.color}`}
              >
                {cat.label}
              </span>
              <span className="px-3 py-1 border border-[#424751]/30 rounded-full text-[10px] uppercase tracking-widest font-bold text-on-surface-variant">
                {SOURCE_META[skill.source].label}
              </span>
            </div>
          </div>
          {/* Title color was `text-primary-fixed-dim` (#a7c8ff) which
              has the same value in both themes — bright/legible on the
              navy dark bg, but invisible on the pale-azure light bg.
              Switching to `text-on-surface` makes it theme-aware
              (dark navy on light, pale gray on dark). */}
          <h2 className="text-4xl font-headline font-bold mb-4 tracking-tight flex items-center gap-4">
            <span className="font-mono text-on-surface">{skill.name}</span>
            <span
              className={`material-symbols-outlined text-2xl ${cat.color}`}
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              {skill.icon}
            </span>
          </h2>
          <p className="text-on-surface-variant leading-relaxed max-w-2xl text-lg">
            {skill.description}
          </p>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-8 space-y-12 custom-scrollbar">
          {/* Skill Content
              The body auto-loads on panel mount. While
              the fetch is in flight we render a centered loading
              card in place of the textarea (matching the panel's
              ghost-border + bg-surface-container-lowest style). On
              load failure we render an error card with a Retry
              button. Once loaded, the textarea takes over and the
              footer row shows char/token counts + dirty indicator. */}
          <section>
            <SectionHeader label="Skill Content" />
            <div className="relative">
              {isLoading ? (
                <div
                  className="w-full rounded-xl px-5 py-12 flex flex-col items-center justify-center gap-3 bg-surface-container-lowest"
                  style={ghostBorder}
                  role="status"
                  aria-live="polite"
                  aria-busy="true"
                >
                  <span className="material-symbols-outlined text-3xl text-primary-fixed-dim animate-spin">
                    progress_activity
                  </span>
                  <p className="text-sm text-on-surface-variant">
                    Loading skill content…
                  </p>
                  <p className="text-[11px] text-on-surface-variant/60 font-mono">
                    {skill.category}/{skill.name}.md
                  </p>
                </div>
              ) : loadState === "error" ? (
                <div
                  className="w-full rounded-xl px-5 py-10 flex flex-col items-center justify-center gap-3 bg-surface-container-lowest"
                  style={ghostBorder}
                  role="alert"
                >
                  <span className="material-symbols-outlined text-3xl text-error">
                    error
                  </span>
                  <p className="text-sm text-on-surface">
                    Couldn&apos;t load this skill&apos;s body.
                  </p>
                  {loadError && (
                    <p className="text-[11px] text-on-surface-variant/70 font-mono max-w-md text-center">
                      {loadError}
                    </p>
                  )}
                  <button
                    onClick={loadBody}
                    className="mt-1 text-xs text-primary-fixed-dim hover:underline font-medium"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <textarea
                  value={bodyContent}
                  onChange={(e) => {
                    setBodyContent(e.target.value);
                    setDirty(true);
                  }}
                  rows={16}
                  className="w-full bg-surface-container-lowest rounded-xl px-5 py-4 text-sm font-mono text-on-surface-variant leading-relaxed resize-none focus:ring-1 focus:ring-primary-fixed-dim/30 focus:outline-none"
                  style={ghostBorder}
                />
              )}
              <div className="flex items-center justify-between mt-2 px-1">
                <div className="flex items-center gap-4 text-[10px] text-on-surface-variant">
                  <span>
                    {bodyContent.length.toLocaleString()} chars
                  </span>
                  <span>~{Math.ceil(bodyContent.length / 4)} tokens</span>
                  {dirty && bodyLoaded && (
                    <span className="text-amber-300">
                      • Unsaved changes
                    </span>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* Configuration */}
          <section>
            <SectionHeader label="Configuration" />
            <div className="grid grid-cols-1 gap-3">
              {/* Availability — power icon + toggle were green (#7bdc7b)
                  which read fine on dark navy but desaturated on the
                  pale-azure light bg. Switched to primary blue tints,
                  and the toggle is now a functional <button> mirroring
                  the card-level toggle (clicking flips skill.enabled
                  via the parent's setSkills). */}
              <div
                className="flex items-center justify-between p-5 bg-surface-container rounded-xl"
                style={ghostBorder}
              >
                <div className="flex items-center gap-4">
                  <span
                    className="material-symbols-outlined text-primary"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    power_settings_new
                  </span>
                  <div>
                    <div className="font-semibold">Availability</div>
                    <div className="text-xs text-on-surface-variant">
                      System-wide accessibility for agents
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={skill.enabled}
                    aria-label={
                      skill.enabled
                        ? `Disable skill ${skill.displayName}`
                        : `Enable skill ${skill.displayName}`
                    }
                    onClick={onToggleEnabled}
                    className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors hover:ring-2 hover:ring-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/40 ${
                      skill.enabled ? "bg-primary/30" : "bg-surface-container-highest"
                    }`}
                  >
                    <div
                      className={`absolute top-1 w-3 h-3 rounded-full transition-all ${
                        skill.enabled ? "right-1 bg-primary" : "left-1 bg-on-surface-variant/40"
                      }`}
                    />
                  </button>
                  <LockBadge locked={skill.locked} />
                </div>
              </div>

              {/* Loading Mode */}
              <div
                className="flex items-center justify-between p-5 bg-surface-container rounded-xl"
                style={ghostBorder}
              >
                <div className="flex items-center gap-4">
                  <span
                    className="material-symbols-outlined text-primary-fixed-dim"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    {skill.loadingMode === "always" ? "bolt" : "schedule"}
                  </span>
                  <div>
                    <div className="font-semibold">Loading Mode</div>
                    <div className="text-xs text-on-surface-variant">
                      {skill.loadingMode === "always"
                        ? "Loaded into every agent context"
                        : "Loaded only when explicitly requested"}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex gap-1 p-1 bg-surface-container-low rounded-lg border border-white/5">
                    <div
                      className={`px-3 py-1.5 text-[10px] font-bold rounded ${
                        skill.loadingMode === "always"
                          ? "bg-[#a7c8ff]/20 text-primary-fixed-dim"
                          : "text-on-surface-variant/40"
                      }`}
                    >
                      Always
                    </div>
                    <div
                      className={`px-3 py-1.5 text-[10px] font-bold rounded ${
                        skill.loadingMode === "on-demand"
                          ? "bg-[#fbbc30]/20 text-[#fbbc30]"
                          : "text-on-surface-variant/40"
                      }`}
                    >
                      On-demand
                    </div>
                  </div>
                  <LockBadge locked={false} />
                </div>
              </div>

              {/* Max Concurrent Agents */}
              <div
                className="flex items-center justify-between p-5 bg-surface-container rounded-xl"
                style={ghostBorder}
              >
                <div className="flex items-center gap-4">
                  <span
                    className="material-symbols-outlined text-[#fbbc30]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    groups
                  </span>
                  <div>
                    <div className="font-semibold">Max Concurrent Agents</div>
                    <div className="text-xs text-on-surface-variant">
                      Maximum simultaneous agent loads (0 = unlimited)
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2 bg-surface-container-highest px-4 py-2 rounded-lg">
                    <span className="font-mono text-sm">
                      {skill.maxConcurrentAgents === 0
                        ? "Unlimited"
                        : skill.maxConcurrentAgents}
                    </span>
                    <span className="material-symbols-outlined text-sm cursor-pointer hover:text-primary-fixed-dim">
                      edit
                    </span>
                  </div>
                  <LockBadge locked={false} />
                </div>
              </div>

              {/* Eligible Agents */}
              <div
                className="flex items-center justify-between p-5 bg-surface-container rounded-xl"
                style={ghostBorder}
              >
                <div className="flex items-center gap-4">
                  <span
                    className="material-symbols-outlined text-[#c084fc]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    verified_user
                  </span>
                  <div>
                    <div className="font-semibold">Eligible Agents</div>
                    <div className="text-xs text-on-surface-variant">
                      Which agents can use this skill
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2 bg-surface-container-highest px-4 py-2 rounded-lg">
                    <span className="text-sm">{skill.eligibleAgents}</span>
                    <span className="material-symbols-outlined text-sm text-on-surface-variant">
                      expand_more
                    </span>
                  </div>
                  <LockBadge locked={false} />
                </div>
              </div>
            </div>
          </section>

          {/* Adoption Analytics */}
          <section>
            <div className="flex items-center justify-between mb-6">
              <SectionHeader label="Adoption" />
              <div className="flex gap-2 p-1 bg-surface-container-low rounded-lg border border-white/5">
                {(["24h", "7d", "30d"] as const).map((range) => (
                  <button
                    key={range}
                    onClick={() => setActiveRange(range)}
                    className={`px-3 py-1.5 text-[10px] font-bold rounded ${
                      activeRange === range
                        ? "bg-[#a7c8ff]/20 text-primary-fixed-dim shadow-sm"
                        : "text-on-surface-variant/40 hover:text-on-surface"
                    }`}
                  >
                    {range.toUpperCase()}:{" "}
                    {range === "24h"
                      ? skill.analytics.calls24h.toLocaleString()
                      : range === "7d"
                        ? skill.analytics.calls7d.toLocaleString()
                        : skill.analytics.calls30d.toLocaleString()}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 mb-8">
              <div className="p-6 bg-surface-container-low rounded-xl" style={ghostBorder}>
                <div className="text-[10px] uppercase font-bold text-on-surface-variant/60 mb-1">
                  Avg Context Tokens
                </div>
                <div className="text-3xl font-headline font-bold text-on-surface">
                  {skill.analytics.avgContextTokens}
                </div>
              </div>
              <div
                className="p-6 bg-surface-container-low rounded-xl border-l-2 border-l-[#7bdc7b]"
                style={ghostBorder}
              >
                <div className="text-[10px] uppercase font-bold text-on-surface-variant/60 mb-1">
                  Active Agents
                </div>
                <div className="text-3xl font-headline font-bold text-[#7bdc7b]">
                  {skill.analytics.activeAgents}
                </div>
              </div>
            </div>
            {skill.analytics.topAgents.length > 0 && (
              <div>
                <div className="text-xs font-bold text-on-surface-variant mb-3">
                  Top Agents
                </div>
                <div className="flex flex-wrap gap-2">
                  {skill.analytics.topAgents.map((agent) => (
                    <div
                      key={agent.name}
                      className="px-3 py-1.5 bg-surface-container-highest border border-white/5 rounded-lg text-xs font-medium flex items-center gap-2"
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{
                          backgroundColor: agent.color,
                          boxShadow: `0 0 8px ${agent.color}`,
                        }}
                      />
                      {agent.name}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* Phantom is a single-tenant operator install: there is no
              workspace concept anywhere in the MCP, so there is no
              workspace assignment or override section. Skills are
              global to the install — toggle them on/off in the card
              header; deletion is below in the Danger Zone. */}

          {/* Danger Zone */}
          <section className="pb-8">
            <DangerSectionHeader label="Danger Zone" />
            <div
              className="p-5 bg-surface-container rounded-xl border border-[#ef4444]/10"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#ffb4ab]">
                    delete_forever
                  </span>
                  <div>
                    <div className="font-semibold text-[#ffb4ab]">Delete Skill</div>
                    <div className="text-xs text-on-surface-variant/70">
                      Permanently remove this skill from the platform. This action cannot be undone.
                    </div>
                  </div>
                </div>
                <button className="px-4 py-2 bg-[#ef4444]/10 border border-[#ef4444]/20 text-[#ffb4ab] rounded-lg text-xs font-bold hover:bg-[#ef4444]/20 transition-colors">
                  Delete
                </button>
              </div>
            </div>
          </section>
        </div>

        {/* Footer */}
        <footer className="p-6 border-t border-white/5 bg-surface-container-low/50 flex gap-4 shrink-0">
          <button className="flex-1 py-4 bg-primary-container hover:bg-primary-container/80 text-on-primary-container font-headline font-bold rounded-xl transition-all shadow-lg shadow-primary-fixed-dim/10">
            Save Changes
          </button>
          <button
            onClick={onClose}
            className="px-6 py-4 bg-surface-container-highest text-on-surface-variant font-headline font-bold rounded-xl transition-all hover:text-on-surface"
          >
            Cancel
          </button>
        </footer>
      </aside>
    </>
  );
}

// Convert a free-text display name into a deterministic snake_case
// filename. Used for auto-deriving the on-disk name as the operator
// types in the display-name field. Lowercase + non-alphanumeric →
// underscore + collapse runs + trim. We don't enforce uniqueness
// here — the backend rejects duplicates with a clear error.
function slugifyForFilename(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function CreateSkillPanel({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  // Creates skills. Returns
  // true on success so the parent can close us; we keep the
  // operator's draft visible on failure (alert is shown, panel
  // stays open for retry/edit).
  onCreate: (
    category: string,
    filename: string,
    content: string,
  ) => Promise<boolean>;
}) {
  const [loadingMode, setLoadingMode] = useState<LoadingMode>("always");
  const [contextPreviewOpen, setContextPreviewOpen] = useState(false);
  const [skillContent, setSkillContent] = useState("");
  // New fields required by the backend POST. Category is one of
  // foundation/scenarios/validation/workflows; filename is the .md
  // file name (we'll auto-append .md if missing). displayName is
  // optional but pre-fills the frontmatter so the new skill renders
  // with a label instead of falling back to the filename stem.
  const [createCategory, setCreateCategory] =
    useState<Exclude<CategoryKey, "all">>("scenarios");
  const [createFilename, setCreateFilename] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [creating, setCreating] = useState(false);

  // Compose the actual MD body that hits the backend. If the
  // operator left the optional fields blank we skip frontmatter
  // generation entirely — the backend will list the skill with
  // legacy heading-based display name and operators can add
  // frontmatter later via Edit.
  const handleCreate = useCallback(async () => {
    if (!createFilename.trim()) {
      alert("Filename is required.");
      return;
    }
    if (!skillContent.trim()) {
      alert("Skill content cannot be empty.");
      return;
    }
    let body = skillContent;
    if (createDisplayName.trim() || createDescription.trim()) {
      // Compose minimal frontmatter. We don't import yaml on the
      // client; we hand-build a YAML string. Strings are quoted
      // with single quotes to avoid issues with spaces.
      const fmLines = [
        `name: ${createFilename.replace(/\.md$/, "")}`,
        createDisplayName.trim() &&
          `displayName: ${JSON.stringify(createDisplayName.trim())}`,
        `category: ${createCategory}`,
        createDescription.trim() &&
          `description: ${JSON.stringify(createDescription.trim())}`,
        `source: workspace`,
        `loadingMode: ${loadingMode}`,
        `locked: false`,
      ].filter(Boolean);
      body = `---\n${fmLines.join("\n")}\n---\n\n${skillContent}`;
    }
    setCreating(true);
    const ok = await onCreate(createCategory, createFilename, body);
    setCreating(false);
    if (ok) onClose();
  }, [
    createCategory,
    createDescription,
    createDisplayName,
    createFilename,
    loadingMode,
    onClose,
    onCreate,
    skillContent,
  ]);

  const charCount = skillContent.length;
  const tokenEstimate = Math.round(charCount / 2.6);

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 z-40 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed top-0 right-0 h-full w-[55%] z-50 flex flex-col shadow-2xl rounded-l-[2rem] overflow-hidden animate-[slideInRight_0.3s_ease-out]"
        style={panelStyle}
      >
        {/* Header */}
        <div className="px-8 pt-8 pb-6 border-b border-white/10 shrink-0">
          <div className="flex justify-between items-start">
            <div>
              <h2 className="text-3xl font-bold font-headline tracking-tight text-on-surface">
                Create Skill
              </h2>
              <p className="text-on-surface-variant text-sm mt-1">
                Add a new skill to the platform registry
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-full transition-colors text-on-surface-variant"
              aria-label="Close panel"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-8 py-8 space-y-12 custom-scrollbar">
          {/* Skill Identity */}
          <section className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-1 w-12 bg-[#a7c8ff] rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim">
                Skill Identity
              </span>
            </div>
            <div className="space-y-6">
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Display Name <span className="text-[#ffb4ab]">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. SQL Injection Scenario"
                  value={createDisplayName}
                  onChange={(e) => {
                    setCreateDisplayName(e.target.value);
                    // Auto-derive filename slug from display name —
                    // operators rarely care about the on-disk
                    // filename, and a deterministic slug avoids
                    // weird-character-in-filename errors. Only
                    // overwrites if the operator hasn't manually
                    // edited the filename field.
                    if (
                      !createFilename ||
                      createFilename ===
                        slugifyForFilename(createDisplayName)
                    ) {
                      setCreateFilename(slugifyForFilename(e.target.value));
                    }
                  }}
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50"
                />
                <p className="text-[10px] text-on-surface-variant">
                  Operator-facing label shown on the card and in the chat agent&apos;s skill list.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Filename <span className="text-[#ffb4ab]">*</span>
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="sql_injection_scenario"
                    value={createFilename}
                    onChange={(e) => setCreateFilename(e.target.value)}
                    className="flex-1 bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm font-mono focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50"
                  />
                  <span className="text-xs text-on-surface-variant font-mono">.md</span>
                </div>
                <p className="text-[10px] text-on-surface-variant">
                  Canonical identifier used by the chat agent. Auto-derived from display name; edit if you need a different on-disk name.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Category
                </label>
                <div className="relative">
                  <div className="absolute left-4 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-[#a7c8ff]" />
                  <select
                    value={createCategory}
                    onChange={(e) =>
                      setCreateCategory(
                        e.target.value as Exclude<CategoryKey, "all">,
                      )
                    }
                    className="w-full bg-surface-container-highest border-none rounded-xl pl-9 pr-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface appearance-none"
                  >
                    <option value="foundation">Foundation</option>
                    <option value="scenarios">Scenarios</option>
                    <option value="validation">Validation</option>
                    <option value="workflows">Workflows</option>
                  </select>
                  <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 text-on-surface-variant pointer-events-none">
                    expand_more
                  </span>
                </div>
                <p className="text-[10px] text-on-surface-variant">
                  Determines which directory the MD file lands in under <code>bundles/spark/mcp/skills/</code>.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
                  Description
                </label>
                <textarea
                  rows={3}
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="One-line summary the chat agent will see in <available_skills>. Be concise and specific — this is what the model uses to decide whether to apply the skill."
                  className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 text-on-surface placeholder:text-on-surface-variant/50 resize-none"
                />
              </div>
            </div>
          </section>

          {/* Skill Content */}
          <section className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-1 w-12 bg-[#a7c8ff] rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim">
                Skill Content
              </span>
            </div>
            <div>
              <textarea
                rows={16}
                value={skillContent}
                onChange={(e) => setSkillContent(e.target.value)}
                placeholder="Enter the skill content that will be injected into the agent's context..."
                className="w-full bg-surface-container-lowest rounded-xl px-5 py-4 text-sm font-mono text-on-surface-variant leading-relaxed resize-none focus:ring-1 focus:ring-primary-fixed-dim/30 focus:outline-none"
                style={ghostBorder}
              />
              <div className="flex items-center justify-between mt-2 px-1">
                <div className="flex items-center gap-4 text-[10px] text-on-surface-variant">
                  <span>{charCount.toLocaleString()} / 20,000 chars</span>
                  <span>~{tokenEstimate} tokens</span>
                </div>
                <button className="text-[10px] text-primary-fixed-dim hover:underline font-medium">
                  Preview
                </button>
              </div>
            </div>
          </section>

          {/* Loading & Availability */}
          <section className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-1 w-12 bg-[#a7c8ff] rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim">
                Loading & Availability
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={() => setLoadingMode("always")}
                className={`p-4 rounded-xl cursor-pointer text-left transition-all ${
                  loadingMode === "always"
                    ? "bg-[rgba(25,99,179,0.2)] border border-[#a7c8ff]/30"
                    : "bg-surface-container-highest border border-white/5 hover:bg-[#424751]"
                }`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span
                    className="material-symbols-outlined text-primary-fixed-dim"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    bolt
                  </span>
                  <span className="text-sm font-bold text-on-surface">
                    Always Loaded
                  </span>
                </div>
                <p className="text-[10px] text-on-surface-variant/70 leading-relaxed">
                  Injected into every agent context at startup.
                </p>
              </button>
              <button
                onClick={() => setLoadingMode("on-demand")}
                className={`p-4 rounded-xl cursor-pointer text-left transition-all ${
                  loadingMode === "on-demand"
                    ? "bg-[rgba(251,188,48,0.1)] border border-[#fbbc30]/30"
                    : "bg-surface-container-highest border border-white/5 hover:bg-[#424751]"
                }`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="material-symbols-outlined text-[#fbbc30]">
                    schedule
                  </span>
                  <span className="text-sm font-bold text-on-surface">
                    On-demand
                  </span>
                </div>
                <p className="text-[10px] text-on-surface-variant/70 leading-relaxed">
                  Loaded only when explicitly requested by the agent.
                </p>
              </button>
            </div>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                <div className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-primary-fixed-dim">
                    visibility
                  </span>
                  <div>
                    <h4 className="text-sm font-medium">Availability</h4>
                    <p className="text-[10px] text-on-surface-variant">
                      Visible to all eligible agents
                    </p>
                  </div>
                </div>
                <div className="w-10 h-5 bg-primary/30 rounded-full relative">
                  <div className="absolute right-1 top-1 w-3 h-3 bg-primary rounded-full" />
                </div>
              </div>
              <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                <div className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#fbbc30]">
                    groups
                  </span>
                  <div>
                    <h4 className="text-sm font-medium">Max Concurrent Agents</h4>
                    <p className="text-[10px] text-on-surface-variant">
                      Simultaneous loads (0 = unlimited)
                    </p>
                  </div>
                </div>
                <input
                  type="number"
                  defaultValue="0"
                  min="0"
                  className="w-20 bg-surface-container border-none rounded-lg px-3 py-1.5 text-center text-xs font-mono text-on-surface focus:ring-1 focus:ring-primary/40"
                />
              </div>
              <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-xl">
                <div className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#c084fc]">
                    verified_user
                  </span>
                  <div>
                    <h4 className="text-sm font-medium">Eligible Agents</h4>
                    <p className="text-[10px] text-on-surface-variant">
                      Which agents can use this skill
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 bg-surface-container px-3 py-1.5 rounded-lg">
                  <span className="text-xs text-on-surface">All agents</span>
                  <span className="material-symbols-outlined text-sm text-on-surface-variant">
                    expand_more
                  </span>
                </div>
              </div>
            </div>
          </section>

          {/* Context Preview (Collapsible) */}
          <section className="space-y-4 pb-4">
            <button
              onClick={() => setContextPreviewOpen(!contextPreviewOpen)}
              className="flex items-center gap-3 w-full text-left"
            >
              <div className="h-1 w-12 bg-[#a7c8ff]/50 rounded-full" />
              <span className="font-label uppercase tracking-widest text-[10px] font-bold text-primary-fixed-dim/60">
                Context Preview
              </span>
              <span className="material-symbols-outlined text-sm text-on-surface-variant/40 ml-auto">
                {contextPreviewOpen ? "expand_less" : "expand_more"}
              </span>
            </button>
            {contextPreviewOpen && (
              <div
                className="bg-surface-container-lowest rounded-xl p-5 text-xs font-mono text-on-surface-variant/60 leading-relaxed"
                style={ghostBorder}
              >
                {skillContent ? (
                  <pre className="whitespace-pre-wrap">{skillContent}</pre>
                ) : (
                  <p className="text-on-surface-variant/50 italic">
                    Enter skill content above to see how it will appear in the agent context.
                  </p>
                )}
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <footer className="bg-surface-container-low px-8 py-6 flex items-center justify-between border-t border-white/5 shrink-0">
          <span className="text-[10px] text-on-surface-variant/60 italic">
            {creating
              ? "Creating skill on the agent…"
              : "All fields can be modified after creation"}
          </span>
          <div className="flex items-center gap-4">
            <button
              onClick={onClose}
              disabled={creating}
              className="px-6 py-2.5 text-sm font-medium text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={creating || !createFilename.trim() || !skillContent.trim()}
              className="flex items-center gap-2 px-8 py-2.5 bg-gradient-to-r from-[#1963b3] to-[#2D8DF0] text-on-surface rounded-xl font-bold font-headline shadow-lg shadow-[#a7c8ff]/20 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <span className="material-symbols-outlined text-sm">
                {creating ? "hourglass_empty" : "add"}
              </span>
              {creating ? "Creating…" : "Create Skill"}
            </button>
          </div>
        </footer>
      </div>
    </>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

// ─── Live → SkillDef mapping ────────────────────────────────────────────────

// Shape returned by GET /api/skills (skills_list_all on the MCP). Keys
// match `skills_crud.py::get_all_skills` after the frontmatter
// migration; skills without frontmatter fall through with empty
// strings and we apply defaults below.
interface LiveSkillRow {
  name: string;
  displayName?: string;
  category: string;
  description?: string;
  icon?: string;
  source?: string;
  loadingMode?: string;
  locked?: boolean;
  attack?: string[];
  filename: string;
  file_path: string;
  size_bytes?: number;
  modified?: number;
  has_frontmatter?: boolean;
  // Present only on plugin-contributed skills (those
  // discovered under plugins/<vendor>/*.md). Surfaces vendor
  // attribution to the UI without forcing the row's main category
  // off the standard four built-in categories.
  plugin_vendor?: string;
}

// Sensible defaults for a skill row missing frontmatter — keeps the
// card render-safe even before an operator migrates an old skill.
function liveRowToSkillDef(row: LiveSkillRow): SkillDef {
  // `plugins` joins the four built-in categories.
  // Backend surfaces plugin-contributed skills under
  // plugins/<vendor>/*.md with category="plugins" and a
  // `plugin_vendor` field on the row. Anything else (malformed
  // category in frontmatter, future categories not yet known to the
  // UI) still defaults to "scenarios" rather than crashing the
  // render — better to mis-bucket than to break the page.
  const category = (
    ["foundation", "scenarios", "validation", "workflows", "plugins"].includes(
      row.category,
    )
      ? row.category
      : "scenarios"
  ) as Exclude<CategoryKey, "all">;

  return {
    id: `${category}-${row.name}`,
    name: row.name,
    displayName: row.displayName || row.name,
    category,
    description:
      row.description ||
      "(No description in frontmatter. Edit the skill MD to add one.)",
    icon: row.icon || "extension",
    source: ((row.source as SourceType) || "platform"),
    loadingMode: ((row.loadingMode as LoadingMode) || "on-demand"),
    enabled: true,
    locked: Boolean(row.locked),
    agentCount: 1,
    calls7d: 0,
    content: `See bundles/spark/mcp/skills/${row.file_path}`,
    charCount: row.size_bytes || 0,
    tokenCount: Math.ceil((row.size_bytes || 0) / 4),
    maxConcurrentAgents: 0,
    eligibleAgents: "phantom-soc-simulation",
    analytics: {
      calls24h: 0,
      calls7d: 0,
      calls30d: 0,
      avgContextTokens: 0,
      activeAgents: 1,
      topAgents: [{ name: "phantom", color: "#1f7bff" }],
    },
  };
}

export default function SkillsPage() {
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<SkillDef | null>(null);
  const [showCreatePanel, setShowCreatePanel] = useState(false);

  // Skills are loaded live from /api/skills (which calls the
  // MCP's skills_list_all). The hardcoded `SKILLS` array above is a
  // fallback for SSR / first-paint and for environments where the
  // MCP isn't reachable yet. Once the live fetch completes we replace
  // it. New skill files added to disk appear automatically — adding
  // an entry to the array is not required.
  const [skills, setSkills] = useState<SkillDef[]>(SKILLS);
  const [liveLoadStatus, setLiveLoadStatus] = useState<
    "loading" | "live" | "fallback"
  >("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/skills", { cache: "no-store" });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const body = (await res.json()) as {
          success?: boolean;
          skills?: LiveSkillRow[];
        };
        if (cancelled) return;
        if (Array.isArray(body.skills) && body.skills.length > 0) {
          setSkills(body.skills.map(liveRowToSkillDef));
          setLiveLoadStatus("live");
        } else {
          // API returned empty — keep the fallback array. Probably a
          // first-boot edge where the volume hasn't seeded yet.
          setLiveLoadStatus("fallback");
        }
      } catch {
        if (!cancelled) setLiveLoadStatus("fallback");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleEnabled = useCallback((id: string) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s)),
    );
    // Keep the open detail panel in sync if it's the same skill —
    // otherwise the panel's availability toggle would lag the card.
    setSelectedSkill((cur) =>
      cur && cur.id === id ? { ...cur, enabled: !cur.enabled } : cur,
    );
  }, []);

  // ─── CRUD handlers ─────────────────────────────
  // All four backend operations (skills_create / skills_read /
  // skills_update / skills_delete) already exist as MCP tools and
  // are surfaced through the /api/skills route handler. This is just
  // the UI plumbing that calls them.
  //
  // The shape we send/receive:
  //   GET    /api/skills                        → list (used at mount)
  //   GET    /api/skills?file_path=foo.md       → read body content
  //   POST   /api/skills {category,filename,content}  → create
  //   PUT    /api/skills {file_path,content}    → update body
  //   DELETE /api/skills?file_path=foo.md       → soft-delete (.deleted/)
  //
  // After any write op we re-fetch the list so the page reflects the
  // new state. We don't optimistically update — the server is the
  // source of truth, especially since soft-delete + backup-on-update
  // means there's filesystem state we want to round-trip through.

  const refetchSkills = useCallback(async () => {
    try {
      const res = await fetch("/api/skills", { cache: "no-store" });
      if (!res.ok) return;
      const body = (await res.json()) as { skills?: LiveSkillRow[] };
      if (Array.isArray(body.skills)) {
        setSkills(body.skills.map(liveRowToSkillDef));
      }
    } catch {
      // Network blip — leave the existing array in place rather than
      // wiping it. Next interaction will retry.
    }
  }, []);

  const handleDownloadSkill = useCallback(async (skill: SkillDef) => {
    // Fetch the live MD body, then trigger a browser download. The
    // file_path on the skill points back at the canonical location
    // under bundles/spark/mcp/skills/<category>/<filename>.md.
    const filePath = `${skill.category}/${skill.name}.md`;
    try {
      const res = await fetch(
        `/api/skills?file_path=${encodeURIComponent(filePath)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        alert(`Download failed: ${res.status}`);
        return;
      }
      const body = (await res.json()) as {
        success: boolean;
        content?: string;
        error?: string;
      };
      if (!body.success || !body.content) {
        alert(body.error || "Download failed: empty response");
        return;
      }
      const blob = new Blob([body.content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${skill.name}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Download failed: ${err instanceof Error ? err.message : err}`);
    }
  }, []);

  const handleSaveSkill = useCallback(
    async (skill: SkillDef, newContent: string) => {
      // Update existing skill body via PUT. Backend creates a
      // .md.bak before overwriting, so manual rollback is one
      // shell command if the operator regrets the edit.
      const filePath = `${skill.category}/${skill.name}.md`;
      try {
        const res = await fetch("/api/skills", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: filePath, content: newContent }),
        });
        const body = (await res.json()) as {
          success: boolean;
          message?: string;
          error?: string;
        };
        if (!res.ok || !body.success) {
          alert(body.error || `Save failed: ${res.status}`);
          return false;
        }
        await refetchSkills();
        return true;
      } catch (err) {
        alert(`Save failed: ${err instanceof Error ? err.message : err}`);
        return false;
      }
    },
    [refetchSkills],
  );

  const handleDeleteSkill = useCallback(
    async (skill: SkillDef) => {
      if (skill.locked) {
        alert(`"${skill.displayName}" is platform-locked and can't be deleted.`);
        return;
      }
      const ok = window.confirm(
        `Delete skill "${skill.displayName}"?\n\n` +
          `The MD file moves to /app/skills/.deleted/ on the server — recoverable via\n` +
          `docker cp / docker exec, but it disappears from the agent's skill registry\n` +
          `immediately.`,
      );
      if (!ok) return;
      const filePath = `${skill.category}/${skill.name}.md`;
      try {
        const res = await fetch(
          `/api/skills?file_path=${encodeURIComponent(filePath)}`,
          { method: "DELETE" },
        );
        const body = (await res.json()) as {
          success: boolean;
          error?: string;
        };
        if (!res.ok || !body.success) {
          alert(body.error || `Delete failed: ${res.status}`);
          return;
        }
        // Close the detail panel + refresh the list.
        setSelectedSkill(null);
        await refetchSkills();
      } catch (err) {
        alert(`Delete failed: ${err instanceof Error ? err.message : err}`);
      }
    },
    [refetchSkills],
  );

  const handleCreateSkill = useCallback(
    async (
      category: string,
      filename: string,
      content: string,
    ): Promise<boolean> => {
      // Ensure .md suffix — the backend rejects without it. We could
      // strip + re-add, but it's cleaner to require operators name
      // their file the way it'll be saved.
      if (!filename.endsWith(".md")) filename += ".md";
      try {
        const res = await fetch("/api/skills", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, filename, content }),
        });
        const body = (await res.json()) as {
          success: boolean;
          error?: string;
        };
        if (!res.ok || !body.success) {
          alert(body.error || `Create failed: ${res.status}`);
          return false;
        }
        await refetchSkills();
        return true;
      } catch (err) {
        alert(`Create failed: ${err instanceof Error ? err.message : err}`);
        return false;
      }
    },
    [refetchSkills],
  );

  const filteredSkills = useMemo(() => {
    let result = [...skills];
    if (categoryFilter !== "all") {
      result = result.filter((s) => s.category === categoryFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.displayName.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q)
      );
    }
    return result;
  }, [skills, categoryFilter, searchQuery]);

  // Summary widgets derive from the LIVE skills array.
  // Hardcoded values would drift as skills are added; live derivation
  // also lets the Active count actually mean "active".
  const summaryStats = useMemo(() => {
    const categories = new Set(skills.map((s) => s.category));
    return {
      total: skills.length,
      active: skills.filter((s) => s.enabled).length,
      categories: categories.size,
    };
  }, [skills]);

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-8">
        {/* ── Page Header ──────────────────────────────────── */}
        {/* Standardized to the jobs-style pattern (icon + title +
            subtitle, no breadcrumb). Drops the previous
            Runtime > Skills navigation flow which was inconsistent
            with every other page. */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="material-symbols-outlined text-2xl text-primary">
                auto_awesome
              </span>
              <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">
                Skills
              </h1>
            </div>
            <p className="text-sm text-on-surface-variant ml-9">
              Manage skill definitions and context injection across the platform.
            </p>
          </div>
          {/* Phantom is a single-tenant agent install; there's no
              workspace concept here, so the header carries just the
              operator-actionable affordances: Import + Create. */}
          <div className="flex items-center gap-4">
            <ImportSkillButton onImported={refetchSkills} />
            <button
              onClick={() => setShowCreatePanel(true)}
              className="text-white px-6 py-2.5 rounded-xl font-bold font-headline flex items-center gap-2 shadow-[0px_20px_40px_rgba(25,99,179,0.15)] active:scale-95 transition-transform"
              style={{
                background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
              }}
            >
              <span className="material-symbols-outlined text-lg">add</span>
              Create Skill
            </button>
          </div>
        </header>

        {/* ── Summary Strip — horizontal layout (icon left, number+
            caption right). Replaces the vertical stacked layout
            where the number sat below the icon on a new line.
            Theme-aware tints (bg-primary/15 instead of hardcoded
            rgba) so the icon backgrounds reflow on theme switch. */}
        <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-primary/15 flex items-center justify-center text-primary shrink-0">
              <span className="material-symbols-outlined">auto_awesome</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Total Skills
              </p>
              <p className="text-2xl font-bold font-headline text-on-surface">
                {summaryStats.total}
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                {SUMMARY_CAPTIONS.totalCaption}
              </p>
            </div>
          </div>
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-secondary/15 flex items-center justify-center text-secondary shrink-0">
              <span className="material-symbols-outlined">check_circle</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Active
              </p>
              <p className="text-2xl font-bold font-headline text-secondary">
                {summaryStats.active}
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                Enabled platform-wide
              </p>
            </div>
          </div>
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-tertiary/15 flex items-center justify-center text-tertiary shrink-0">
              <span className="material-symbols-outlined">category</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Categories
              </p>
              <p className="text-2xl font-bold font-headline text-tertiary">
                {summaryStats.categories}
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                Skill taxonomies
              </p>
            </div>
          </div>
          <div className="p-5 rounded-2xl flex items-center gap-4" style={glassStyle}>
            <div className="h-12 w-12 rounded-xl bg-primary/15 flex items-center justify-center text-primary shrink-0">
              <span className="material-symbols-outlined">trending_up</span>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                Invocations
              </p>
              <p className="text-2xl font-bold font-headline text-primary">
                —
              </p>
              <p className="text-[11px] text-on-surface-variant/70 truncate">
                {SUMMARY_CAPTIONS.invocationsDelta}
              </p>
            </div>
          </div>
        </section>

        {/* ── Filter Bar ─────────────────────────────────────
            Theme-aware bg + text. The pill row was hardcoded
            bg-surface-container-low with on-surface-variant text — fine in dark
            mode, invisible in light (dark text on dark pill).
            Switched to bg-surface-container-low (CSS-var driven) +
            text-on-surface-variant for the inactive state, secondary
            (green) for the active chip — matches the rest of the
            app's "active = green" rule. */}
        <section className="flex flex-col md:flex-row gap-6 items-center justify-between">
          <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-surface-container-low border border-outline-variant/30">
            {CATEGORY_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setCategoryFilter(f.key)}
                className={`px-5 py-2 rounded-xl text-sm font-medium transition-colors ${
                  categoryFilter === f.key
                    ? "bg-secondary-container/40 text-secondary font-bold"
                    : "text-on-surface hover:bg-surface-container-high"
                }`}
              >
                {f.label} ({f.count})
              </button>
            ))}
          </div>
          <div className="relative w-full md:w-80">
            <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-on-surface-variant">
              search
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search skills..."
              className="w-full bg-surface-container-low py-3 pl-12 pr-4 rounded-xl border border-outline-variant/30 focus:border-primary focus:ring-0 text-sm text-on-surface placeholder:text-on-surface-variant/60"
            />
          </div>
        </section>

        {/* ── Skill Grid ────────────────────────────────────── */}
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredSkills.map((skill) => (
            <SkillCard
              key={skill.id}
              skill={skill}
              onSelect={() => setSelectedSkill(skill)}
              onToggleEnabled={() => toggleEnabled(skill.id)}
            />
          ))}
          {filteredSkills.length === 0 && (
            <div className="col-span-3 flex flex-col items-center justify-center py-16 text-center">
              <span className="material-symbols-outlined text-4xl text-on-surface-variant/30 mb-3">
                search_off
              </span>
              <p className="text-sm font-bold text-on-surface-variant">
                No skills match your filter
              </p>
              <button
                onClick={() => {
                  setCategoryFilter("all");
                  setSearchQuery("");
                }}
                className="text-xs font-bold text-primary-fixed-dim hover:underline mt-2"
              >
                Clear filters
              </button>
            </div>
          )}
        </section>
      </div>

      {/* ── Skill Detail Panel ──────────────────────────────── */}
      {selectedSkill && (
        <SkillDetailPanel
          skill={selectedSkill}
          onClose={() => setSelectedSkill(null)}
          onToggleEnabled={() => toggleEnabled(selectedSkill.id)}
          onDownload={handleDownloadSkill}
          onSave={handleSaveSkill}
          onDelete={handleDeleteSkill}
        />
      )}

      {/* ── Create Skill Panel ────────────────────────────── */}
      {showCreatePanel && (
        <CreateSkillPanel
          onClose={() => setShowCreatePanel(false)}
          onCreate={handleCreateSkill}
        />
      )}

      {/* ── Animations ─────────────────────────────────────── */}
      <style jsx>{`
        @keyframes slideInRight {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes fadeIn {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(140, 145, 157, 0.2);
          border-radius: 10px;
        }
      `}</style>
    </div>
  );
}
