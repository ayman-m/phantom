/**
 * Types and pure helpers for the /organization page.
 *
 * The "organization" is the one fictitious company (people, accounts, hosts,
 * networks, sites, groups) that every Phantom log generator draws from. The
 * REST contract lives in bundles/spark/mcp/src/api/organizations.py and is
 * reached through the same-origin proxy under /api/agent/organizations.
 *
 * This file is erasable TypeScript with no `@/` imports, so
 * scripts/test-organization-types.mjs can load it with Node type stripping.
 * Nothing here touches React.
 */

// ─── Vocabulary (mirrors organization.schema.json) ───────────────────────────

export const HOST_ROLES = ["dc", "server", "dmz", "workstation", "network", "security", "cloud"] as const;
export type HostRole = (typeof HOST_ROLES)[number];

export const NETWORK_KINDS = [
  "core",
  "servers",
  "management",
  "security",
  "workstations",
  "wifi",
  "unmanaged",
  "guest",
  "vpn",
  "branch",
  "dmz",
  "cloud",
  "other",
] as const;
export type NetworkKind = (typeof NETWORK_KINDS)[number];

export const PERSON_FLAGS = ["vip", "outlier", "contractor", "leaver"] as const;
export type PersonFlag = (typeof PERSON_FLAGS)[number];

export type SiteKind = "office" | "remote" | "cloud";
export type OrgSource = "bundled" | "operator";

/** Rows the server returns per section call (its hard cap is 500). */
export const SECTION_LIMIT = 500;

// ─── Documents ───────────────────────────────────────────────────────────────

export interface OrgDomain {
  dns: string;
  netbios: string;
  sid?: string;
  email_domain?: string;
  partner_domain?: string;
}

export interface OrgLocale {
  timezone?: string;
  utc_offset_hours?: number;
  workweek?: string[];
  work_hours?: { start: string; end: string };
}

export interface OrgSite {
  id: string;
  name: string;
  city?: string | null;
  country?: string | null;
  kind: SiteKind;
}

export interface OrgNetwork {
  id: string;
  name: string;
  site?: string | null;
  kind: NetworkKind;
  vlan?: number | null;
  cidr?: string;
  range?: string;
}

export interface OrgHost {
  name: string;
  role: HostRole;
  site?: string | null;
  ip: string;
  network: string;
  os?: string;
  rid?: number;
  owner?: string;
  purpose?: string;
  domain_joined?: boolean;
  notes?: string;
}

export interface OrgPerson {
  login: string;
  given_name: string;
  family_name: string;
  display_name?: string;
  email: string;
  title: string;
  department: string;
  manager?: string | null;
  site: string;
  workstation: string;
  flags?: PersonFlag[];
}

export interface OrgDocument {
  schema_version: number;
  id: string;
  name: string;
  description?: string;
  domain: OrgDomain;
  locale?: OrgLocale;
  cortex?: { internal_ranges?: string[]; domain_suffixes?: string[] };
  sites?: OrgSite[];
  networks: OrgNetwork[];
  groups?: { name: string; privileged?: boolean; description?: string }[];
  people: OrgPerson[];
  hosts: OrgHost[];
}

// ─── Records ─────────────────────────────────────────────────────────────────

/** One entry of GET /organizations. Note `hosts` is a count here and `domain` a string. */
export interface OrgMeta {
  id: string;
  name: string;
  source: OrgSource;
  active: boolean;
  version: number;
  updated_at: string | null;
  updated_by: string | null;
  people: number;
  hosts: number;
  domain: string;
  description: string;
}

export interface OrgListResponse {
  organizations: OrgMeta[];
  active_id: string | null;
  count: number;
}

export interface OrgDetail extends OrgMeta {
  document: OrgDocument;
}

export interface OrgChangeResult extends OrgDetail {
  notes: string[];
  forked_from: string | null;
}

export interface HistoryVersion {
  seq: number;
  version: number;
  updated_at: string | null;
  updated_by: string | null;
  note: string | null;
}

export interface HistoryResponse {
  versions: HistoryVersion[];
  count?: number;
}

export interface ValidateResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ExportResponse {
  format: "yaml" | "json";
  text: string;
}

// ─── Section rows ────────────────────────────────────────────────────────────

export interface SectionResponse<Row> {
  section: string;
  total: number;
  returned: number;
  truncated: boolean;
  rows: Row[];
}

/** `section?name=overview`: here `hosts` is a role to count map and `domain` an object. */
export interface OverviewSection {
  section: "overview";
  id: string;
  name: string;
  description: string;
  domain: OrgDomain;
  people: number;
  departments: Record<string, number>;
  admin_accounts: number;
  service_accounts: number;
  hosts: Record<string, number>;
  networks: number;
  sites: string[];
  timezone: string | null;
  warnings: string[];
}

export interface PersonRow {
  login: string;
  name: string;
  email: string;
  title: string;
  department: string;
  manager: string | null;
  site: string;
  workstation: string;
  workstation_ip: string | null;
  sid: string | null;
  okta_id: string | null;
  home_ip: string | null;
  groups: string[];
  admin_login?: string;
  flags?: PersonFlag[];
}

export interface HostRow extends OrgHost {
  fqdn: string | null;
}

export interface NetworkRow extends OrgNetwork {
  cidrs: string[];
}

export interface GroupRow {
  name: string;
  privileged?: boolean;
  description?: string;
  members: string[];
}

export type AccountKind = "user" | "admin" | "service" | "break_glass";

export interface AccountRow {
  login: string;
  kind: AccountKind;
  person: string | null;
  sid: string | null;
  host: string;
  host_ip: string | null;
  groups: string[];
  department: string;
  active: boolean;
  flags: PersonFlag[];
}

export interface CortexSetup {
  internal_ranges: string[];
  domain_suffixes: string[];
  networks: { id: string; name: string; vlan: number | null; cidrs: string[] }[];
}

// ─── Structured edits (POST /organizations/{id}/changes) ─────────────────────

export type CollectionName = "people" | "hosts" | "networks" | "sites" | "groups" | "service_accounts";

export interface OrgChanges {
  set?: Record<string, unknown>;
  upsert?: Partial<Record<CollectionName, Record<string, unknown>[]>>;
  remove?: Partial<Record<CollectionName, string[]>>;
}

// ─── Errors ──────────────────────────────────────────────────────────────────

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * A failed call. The server answers in two shapes: a validation failure is
 * `{error, errors[], code: "invalid"}`, a store refusal is `{error, code}`.
 * `errors` is empty in the second case.
 */
export class ApiError extends Error {
  status: number;
  code: string | null;
  errors: string[];

  constructor(message: string, status: number, code: string | null, errors: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.errors = errors;
  }
}

/** Build an ApiError from a response status and its (possibly absent) JSON body. */
export function describeError(status: number, body: unknown): ApiError {
  let message = `request failed (${status})`;
  let code: string | null = null;
  let errors: string[] = [];
  if (isRecord(body)) {
    if (typeof body.error === "string" && body.error) message = body.error;
    if (typeof body.code === "string") code = body.code;
    if (Array.isArray(body.errors)) {
      errors = body.errors.filter((e): e is string => typeof e === "string" && e.length > 0);
    }
  }
  return new ApiError(message, status, code, errors);
}

/** Every line to show for a failure: `errors[]` when the server sent them, else the message. */
export function errorLines(err: unknown): string[] {
  if (err instanceof ApiError) return err.errors.length > 0 ? err.errors : [err.message];
  if (err instanceof Error) return [err.message];
  return [String(err)];
}

/** One string for a toast: the first few lines, with a count of the rest. */
export function errorSummary(err: unknown, maxLines = 3): string {
  const lines = errorLines(err);
  if (lines.length <= maxLines) return lines.join("\n");
  return `${lines.slice(0, maxLines).join("\n")}\n…and ${lines.length - maxLines} more`;
}

// ─── Requests ────────────────────────────────────────────────────────────────

const BASE = "/api/agent/organizations";

/** `/api/agent/organizations/{id}[/action][?query]`; `id` may be "active". */
export function orgPath(id: string, action?: string, query?: Record<string, string | number>): string {
  let path = `${BASE}/${encodeURIComponent(id)}`;
  if (action) path += `/${action}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) qs.set(k, String(v));
    path += `?${qs.toString()}`;
  }
  return path;
}

export const ORGANIZATIONS_PATH = BASE;
export const VALIDATE_PATH = `${BASE}/validate`;

export interface OrgRequestInit {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

/** Same-origin JSON call. Throws ApiError on any non-2xx answer. */
export async function orgRequest<T>(path: string, init: OrgRequestInit = {}): Promise<T> {
  const hasBody = init.body !== undefined;
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers: hasBody ? { "Content-Type": "application/json" } : undefined,
    body: hasBody ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
    signal: init.signal,
  });
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) throw describeError(res.status, parsed);
  return parsed as T;
}

// ─── Import / export ─────────────────────────────────────────────────────────

/** YAML or JSON: the file extension wins, else a leading "{" means JSON. */
export function detectFormat(text: string, filename?: string): "yaml" | "json" {
  const name = (filename ?? "").toLowerCase();
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".yaml") || name.endsWith(".yml")) return "yaml";
  return text.trimStart().startsWith("{") ? "json" : "yaml";
}

export function exportFilename(id: string, format: "yaml" | "json"): string {
  const safe = id.replace(/[^A-Za-z0-9._-]/g, "_") || "organization";
  return `${safe}.${format === "json" ? "json" : "yaml"}`;
}

/**
 * The document to store in a freshly made copy. The copy has its own id (the
 * server picks one, never the source's), so the edited document's id is
 * replaced. The name is replaced too unless the operator changed it.
 */
export function rewriteForCopy(
  doc: Record<string, unknown>,
  copy: { id: string; name: string },
  sourceName: string,
): Record<string, unknown> {
  const edited = typeof doc.name === "string" ? doc.name.trim() : "";
  return { ...doc, id: copy.id, name: edited && edited !== sourceName ? edited : copy.name };
}

// ─── Forms to change payloads ────────────────────────────────────────────────
//
// Upsert is an RFC 7386 merge-patch on an existing row: `null` deletes a key,
// an array replaces the old one, and the identity key (login / host name /
// network id) selects the row, so it is never edited. New rows omit blanks;
// edits send null for a blank so the old value is cleared.

export interface PersonForm {
  given_name: string;
  family_name: string;
  title: string;
  department: string;
  site: string;
}

export interface PersonEditForm {
  title: string;
  department: string;
  manager: string;
  site: string;
  flags: PersonFlag[];
}

export function newPersonRow(form: PersonForm): Record<string, unknown> {
  const row: Record<string, unknown> = {
    given_name: form.given_name.trim(),
    family_name: form.family_name.trim(),
    title: form.title.trim(),
    department: form.department.trim(),
  };
  if (form.site) row.site = form.site;
  return row;
}

export function personFormError(form: PersonForm): string | null {
  if (!form.given_name.trim()) return "Enter a given name.";
  if (!form.family_name.trim()) return "Enter a family name.";
  if (!form.title.trim()) return "Enter a job title.";
  if (!form.department.trim()) return "Choose or enter a department.";
  return null;
}

export function personEditRow(login: string, form: PersonEditForm): Record<string, unknown> {
  const row: Record<string, unknown> = {
    login,
    title: form.title.trim(),
    department: form.department.trim(),
    manager: form.manager || null,
    flags: [...form.flags],
  };
  if (form.site) row.site = form.site;
  return row;
}

export function personEditError(form: PersonEditForm): string | null {
  if (!form.title.trim()) return "Enter a job title.";
  if (!form.department.trim()) return "Choose or enter a department.";
  return null;
}

export interface HostForm {
  name: string;
  role: HostRole;
  ip: string;
  network: string;
  site: string;
  os: string;
  purpose: string;
  owner: string;
  domain_joined: boolean;
}

export function hostRow(form: HostForm, isNew: boolean): Record<string, unknown> {
  const row: Record<string, unknown> = {
    name: form.name.trim(),
    role: form.role,
    ip: form.ip.trim(),
    network: form.network,
    domain_joined: form.domain_joined,
  };
  const optional: [string, string][] = [
    ["site", form.site],
    ["os", form.os.trim()],
    ["purpose", form.purpose.trim()],
    // Only a workstation has an owner; any other role clears a stale one.
    ["owner", form.role === "workstation" ? form.owner : ""],
  ];
  for (const [key, value] of optional) {
    if (value) row[key] = value;
    else if (!isNew) row[key] = null;
  }
  return row;
}

export function hostFormError(form: HostForm): string | null {
  if (!form.name.trim()) return "Enter a host name.";
  if (!form.ip.trim()) return "Enter an IP address.";
  if (!form.network) return "Choose a network.";
  return null;
}

export interface NetworkForm {
  id: string;
  name: string;
  kind: NetworkKind;
  site: string;
  vlan: string;
  mode: "cidr" | "range";
  address: string;
}

export function networkRow(form: NetworkForm, isNew: boolean): Record<string, unknown> {
  const row: Record<string, unknown> = {
    id: form.id.trim(),
    name: form.name.trim(),
    kind: form.kind,
  };
  if (form.site) row.site = form.site;
  else if (!isNew) row.site = null;
  const vlan = form.vlan.trim();
  if (vlan) row.vlan = Number(vlan);
  else if (!isNew) row.vlan = null;
  // A network has either a cidr or a range. Switching one for the other must
  // clear the old key, or the merged row would carry both and be rejected.
  const address = form.address.trim();
  if (form.mode === "cidr") {
    row.cidr = address;
    if (!isNew) row.range = null;
  } else {
    row.range = address;
    if (!isNew) row.cidr = null;
  }
  return row;
}

export function networkFormError(form: NetworkForm): string | null {
  if (!form.id.trim()) return "Enter an id (lowercase letters, digits and dashes).";
  if (!form.name.trim()) return "Enter a name.";
  if (!form.address.trim()) return form.mode === "cidr" ? "Enter a CIDR such as 10.20.0.0/24." : "Enter a range such as 10.20.0.1-10.20.0.99.";
  const vlan = form.vlan.trim();
  if (vlan && !/^\d+$/.test(vlan)) return "VLAN must be a whole number.";
  return null;
}

export function networkToForm(n: OrgNetwork): NetworkForm {
  return {
    id: n.id,
    name: n.name,
    kind: n.kind,
    site: n.site ?? "",
    vlan: n.vlan === null || n.vlan === undefined ? "" : String(n.vlan),
    mode: n.range && !n.cidr ? "range" : "cidr",
    address: n.cidr ?? n.range ?? "",
  };
}

/** "10.20.0.0/24" or "10.20.100.0-10.20.199.255". */
export function networkAddress(n: { cidr?: string; range?: string; cidrs?: string[] }): string {
  if (n.cidr) return n.cidr;
  if (n.range) return n.range;
  return (n.cidrs ?? []).join(", ");
}

// ─── Filtering and grouping (client side; tables hold up to ~100 rows) ───────

export function matchesSearch(values: (string | null | undefined)[], needle: string): boolean {
  const q = needle.trim().toLowerCase();
  if (!q) return true;
  return values.some((v) => (v ?? "").toLowerCase().includes(q));
}

export function filterPeople(rows: PersonRow[], search: string, department: string): PersonRow[] {
  return rows.filter(
    (p) =>
      (!department || p.department === department) &&
      matchesSearch(
        [p.login, p.name, p.email, p.title, p.department, p.manager, p.site, p.workstation, p.workstation_ip, p.admin_login],
        search,
      ),
  );
}

export function filterHosts(rows: HostRow[], search: string, role: string): HostRow[] {
  return rows.filter(
    (h) =>
      (!role || h.role === role) &&
      matchesSearch([h.name, h.role, h.ip, h.network, h.site, h.owner, h.purpose, h.os, h.fqdn], search),
  );
}

export function filterAccounts(rows: AccountRow[], search: string, kind: string): AccountRow[] {
  return rows.filter(
    (a) =>
      (!kind || a.kind === kind) &&
      matchesSearch([a.login, a.person, a.sid, a.host, a.host_ip, ...a.groups], search),
  );
}

/** Distinct departments, alphabetically. */
export function departmentsOf(rows: { department: string }[]): string[] {
  return [...new Set(rows.map((r) => r.department).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

/** "Sara Almutairi (salmutairi)"; falls back to the login when the person is unknown. */
export function personLabel(rows: PersonRow[], login: string | null | undefined): string {
  if (!login) return "";
  const p = rows.find((r) => r.login.toLowerCase() === login.toLowerCase());
  return p ? `${p.name} (${p.login})` : login;
}

/** Local time, or an em dash when the server sent nothing parseable. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString();
}

export function isBuiltIn(meta: { source: OrgSource }): boolean {
  return meta.source === "bundled";
}
