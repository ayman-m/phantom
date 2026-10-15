#!/usr/bin/env node
/**
 * Behaviour test for lib/organization-types.ts: the pure helpers behind the
 * /organization page (error extraction for the server's two error shapes,
 * import format detection, the copy rewrite used by "Save as my copy", the
 * form-to-change-payload builders and the table filters).
 *
 * Imports the real TypeScript through Node's built-in type stripping; on an
 * older Node it skips (the build type-checks the module).
 *
 *   node scripts/test-organization-types.mjs   (npm run test:organization-types)
 */
import assert from "node:assert/strict";

if (!process.features.typescript) {
  console.log("skip: this Node cannot import .ts directly (needs type stripping)");
  process.exit(0);
}

const t = await import("../lib/organization-types.ts");

let failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log("ok   " + name);
  } catch (e) {
    failed += 1;
    console.log("FAIL " + name + "\n     " + e.message);
  }
}

// ─── Errors ──────────────────────────────────────────────────────────────────

test("a validation failure keeps its errors[] and code", () => {
  const e = t.describeError(400, { error: "2 errors", errors: ["a is wrong", "b is wrong"], code: "invalid" });
  assert.equal(e.status, 400);
  assert.equal(e.code, "invalid");
  assert.deepEqual(t.errorLines(e), ["a is wrong", "b is wrong"]);
});

test("a store refusal has no errors[], so the message is the line", () => {
  const e = t.describeError(409, { error: "the active organization cannot be deleted", code: "active" });
  assert.deepEqual(e.errors, []);
  assert.deepEqual(t.errorLines(e), ["the active organization cannot be deleted"]);
  assert.equal(e.code, "active");
});

test("an unreadable body still yields a status line", () => {
  assert.deepEqual(t.errorLines(t.describeError(502, null)), ["request failed (502)"]);
  assert.deepEqual(t.errorLines(t.describeError(500, "oops")), ["request failed (500)"]);
});

test("non-string entries in errors[] are dropped", () => {
  const e = t.describeError(400, { error: "x", errors: ["ok", 3, null, ""] });
  assert.deepEqual(e.errors, ["ok"]);
});

test("errorSummary caps the toast at three lines and counts the rest", () => {
  const e = t.describeError(400, { error: "x", errors: ["1", "2", "3", "4", "5"] });
  assert.equal(t.errorSummary(e), "1\n2\n3\n…and 2 more");
  assert.equal(t.errorSummary(t.describeError(400, { error: "x", errors: ["1", "2"] })), "1\n2");
});

// ─── Paths ───────────────────────────────────────────────────────────────────

test("orgPath encodes the id and builds the query", () => {
  assert.equal(t.orgPath("phantom-lab"), "/api/agent/organizations/phantom-lab");
  assert.equal(t.orgPath("a b", "section", { name: "people", limit: 500 }), "/api/agent/organizations/a%20b/section?name=people&limit=500");
  assert.equal(t.orgPath("active", "export", { format: "json" }), "/api/agent/organizations/active/export?format=json");
});

// ─── Import / export ─────────────────────────────────────────────────────────

test("detectFormat: extension first, then a leading brace", () => {
  assert.equal(t.detectFormat("{}", "x.yaml"), "yaml");
  assert.equal(t.detectFormat("a: 1", "x.json"), "json");
  assert.equal(t.detectFormat("  {\"id\": 1}"), "json");
  assert.equal(t.detectFormat("id: x"), "yaml");
  assert.equal(t.detectFormat("id: x", "org.YML"), "yaml");
});

test("exportFilename is filesystem safe", () => {
  assert.equal(t.exportFilename("phantom-lab", "yaml"), "phantom-lab.yaml");
  assert.equal(t.exportFilename("a/b c", "json"), "a_b_c.json");
});

test("rewriteForCopy: new id always, name only if the operator did not change it", () => {
  const copy = { id: "phantom-lab-custom-2", name: "Phantom Lab (custom 2)" };
  const unchanged = t.rewriteForCopy({ id: "phantom-lab", name: "Phantom Lab", x: 1 }, copy, "Phantom Lab");
  assert.deepEqual(unchanged, { id: copy.id, name: copy.name, x: 1 });
  const renamed = t.rewriteForCopy({ id: "phantom-lab", name: " Acme " }, copy, "Phantom Lab");
  assert.deepEqual(renamed, { id: copy.id, name: "Acme" });
  const nameless = t.rewriteForCopy({ id: "phantom-lab" }, copy, "Phantom Lab");
  assert.equal(nameless.name, copy.name);
});

// ─── Forms to payloads ───────────────────────────────────────────────────────

test("a new person sends only what was filled in", () => {
  const row = t.newPersonRow({ given_name: " Ali ", family_name: "Nasser", title: "Analyst", department: "IT", site: "" });
  assert.deepEqual(row, { given_name: "Ali", family_name: "Nasser", title: "Analyst", department: "IT" });
  assert.equal(t.newPersonRow({ given_name: "A", family_name: "B", title: "C", department: "D", site: "JED" }).site, "JED");
});

test("person form errors name the missing field", () => {
  const ok = { given_name: "A", family_name: "B", title: "C", department: "D", site: "" };
  assert.equal(t.personFormError(ok), null);
  assert.match(t.personFormError({ ...ok, family_name: " " }), /family name/i);
  assert.match(t.personFormError({ ...ok, department: "" }), /department/i);
});

test("editing a person clears the manager with null and replaces flags", () => {
  const row = t.personEditRow("nalharbi", { title: "T", department: "D", manager: "", site: "RUH", flags: ["vip"] });
  assert.deepEqual(row, { login: "nalharbi", title: "T", department: "D", manager: null, flags: ["vip"], site: "RUH" });
  const set = t.personEditRow("nalharbi", { title: "T", department: "D", manager: "malessa", site: "", flags: [] });
  assert.equal(set.manager, "malessa");
  assert.deepEqual(set.flags, []);
  assert.equal("site" in set, false);
});

const HOST = { name: "PHSRV-X1", role: "server", ip: "10.20.1.30", network: "ruh-servers", site: "", os: "", purpose: "", owner: "", domain_joined: true };

test("a new host omits blanks; an edit nulls them so the old value is cleared", () => {
  assert.deepEqual(t.hostRow(HOST, true), { name: "PHSRV-X1", role: "server", ip: "10.20.1.30", network: "ruh-servers", domain_joined: true });
  const edit = t.hostRow(HOST, false);
  assert.equal(edit.site, null);
  assert.equal(edit.os, null);
  assert.equal(edit.purpose, null);
  assert.equal(edit.owner, null);
});

test("only a workstation keeps an owner", () => {
  assert.equal(t.hostRow({ ...HOST, role: "workstation", owner: "nalharbi" }, true).owner, "nalharbi");
  assert.equal(t.hostRow({ ...HOST, role: "server", owner: "nalharbi" }, true).owner, undefined);
  assert.equal(t.hostRow({ ...HOST, role: "server", owner: "nalharbi" }, false).owner, null);
});

test("host form requires name, ip and network", () => {
  assert.equal(t.hostFormError(HOST), null);
  assert.match(t.hostFormError({ ...HOST, name: "" }), /name/i);
  assert.match(t.hostFormError({ ...HOST, ip: "" }), /ip/i);
  assert.match(t.hostFormError({ ...HOST, network: "" }), /network/i);
});

const NET = { id: "lab", name: "Lab", kind: "servers", site: "", vlan: "", mode: "cidr", address: "10.9.0.0/24" };

test("a new network sends the cidr only", () => {
  assert.deepEqual(t.networkRow(NET, true), { id: "lab", name: "Lab", kind: "servers", cidr: "10.9.0.0/24" });
});

test("switching a network from cidr to range nulls the cidr (and back)", () => {
  const toRange = t.networkRow({ ...NET, mode: "range", address: "10.9.0.1-10.9.0.99" }, false);
  assert.equal(toRange.range, "10.9.0.1-10.9.0.99");
  assert.equal(toRange.cidr, null);
  const toCidr = t.networkRow(NET, false);
  assert.equal(toCidr.cidr, "10.9.0.0/24");
  assert.equal(toCidr.range, null);
  assert.equal(toCidr.vlan, null);
  assert.equal(toCidr.site, null);
});

test("vlan becomes a number and is validated", () => {
  assert.equal(t.networkRow({ ...NET, vlan: "150" }, true).vlan, 150);
  assert.match(t.networkFormError({ ...NET, vlan: "12a" }), /vlan/i);
  assert.equal(t.networkFormError(NET), null);
  assert.match(t.networkFormError({ ...NET, address: "" }), /cidr/i);
  assert.match(t.networkFormError({ ...NET, mode: "range", address: "" }), /range/i);
});

test("networkToForm and networkAddress read a range-only network", () => {
  const range = { id: "u", name: "U", kind: "unmanaged", vlan: 199, range: "10.20.100.0-10.20.199.255" };
  const form = t.networkToForm(range);
  assert.equal(form.mode, "range");
  assert.equal(form.address, range.range);
  assert.equal(form.vlan, "199");
  assert.equal(t.networkAddress(range), range.range);
  assert.equal(t.networkAddress({ cidr: "10.0.0.0/8" }), "10.0.0.0/8");
  assert.equal(t.networkAddress({ cidrs: ["10.0.0.0/24", "10.0.1.0/24"] }), "10.0.0.0/24, 10.0.1.0/24");
});

// ─── Filters ─────────────────────────────────────────────────────────────────

const PEOPLE = [
  { login: "nalharbi", name: "Noura Alharbi", email: "n@x", title: "Finance Manager", department: "Finance", manager: "malessa", site: "RUH", workstation: "PHWS-001", workstation_ip: "10.20.16.20", sid: null, okta_id: null, home_ip: null, groups: [], admin_login: undefined },
  { login: "kalotaibi", name: "Khalid Alotaibi", email: "k@x", title: "HR Manager", department: "HR", manager: null, site: "JED", workstation: "PHWS-002", workstation_ip: "10.21.1.5", sid: null, okta_id: null, home_ip: null, groups: [], admin_login: "adm.kalotaibi" },
];

test("filterPeople combines the department filter with a free-text search", () => {
  assert.equal(t.filterPeople(PEOPLE, "", "").length, 2);
  assert.deepEqual(t.filterPeople(PEOPLE, "", "HR").map((p) => p.login), ["kalotaibi"]);
  assert.deepEqual(t.filterPeople(PEOPLE, "10.20.16", "").map((p) => p.login), ["nalharbi"]);
  assert.deepEqual(t.filterPeople(PEOPLE, "ADM.K", "").map((p) => p.login), ["kalotaibi"]);
  assert.equal(t.filterPeople(PEOPLE, "nobody", "").length, 0);
  assert.equal(t.filterPeople(PEOPLE, "noura", "HR").length, 0);
});

test("filterHosts matches on role and across fields", () => {
  const hosts = [
    { name: "PHDC01", role: "dc", ip: "10.20.0.10", network: "ruh-core", site: "RUH", purpose: "Domain controller", fqdn: "phdc01.phantom.lab" },
    { name: "PHWS-001", role: "workstation", ip: "10.20.16.20", network: "ruh-workstations", site: "RUH", owner: "nalharbi", fqdn: null },
  ];
  assert.deepEqual(t.filterHosts(hosts, "", "dc").map((h) => h.name), ["PHDC01"]);
  assert.deepEqual(t.filterHosts(hosts, "nalharbi", "").map((h) => h.name), ["PHWS-001"]);
  assert.deepEqual(t.filterHosts(hosts, "controller", "").map((h) => h.name), ["PHDC01"]);
});

test("filterAccounts searches groups and filters by kind", () => {
  const rows = [
    { login: "a", kind: "user", person: "a", sid: "S-1", host: "H1", host_ip: null, groups: ["SG-IT"], department: "IT", active: true, flags: [] },
    { login: "adm.a", kind: "admin", person: "a", sid: "S-2", host: "H1", host_ip: null, groups: ["Domain Admins"], department: "IT", active: true, flags: [] },
  ];
  assert.deepEqual(t.filterAccounts(rows, "domain admins", "").map((r) => r.login), ["adm.a"]);
  assert.deepEqual(t.filterAccounts(rows, "", "user").map((r) => r.login), ["a"]);
});

test("departmentsOf is distinct and sorted", () => {
  assert.deepEqual(t.departmentsOf([{ department: "IT" }, { department: "Finance" }, { department: "IT" }, { department: "" }]), ["Finance", "IT"]);
});

test("personLabel falls back to the login", () => {
  assert.equal(t.personLabel(PEOPLE, "NALHARBI"), "Noura Alharbi (nalharbi)");
  assert.equal(t.personLabel(PEOPLE, "ghost"), "ghost");
  assert.equal(t.personLabel(PEOPLE, null), "");
});

test("formatTimestamp tolerates missing and unparseable values", () => {
  assert.equal(t.formatTimestamp(null), "—");
  assert.equal(t.formatTimestamp("not a date"), "not a date");
  assert.notEqual(t.formatTimestamp("2026-10-15T10:00:00Z"), "—");
});

if (failed > 0) {
  console.log(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log("\nall organization-types tests passed");
