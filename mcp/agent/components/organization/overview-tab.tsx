"use client";

import { networkAddress } from "@/lib/organization-types";
import { Chip, CopyButton, Panel, TableShell, Td, Th, ROW_CLASS, WarningList } from "./ui";
import type { OrgData } from "./use-organization";

function KeyValue({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 border-t border-outline-variant/15 first:border-t-0">
      <dt className="text-[11px] uppercase tracking-wider text-on-surface-variant/70">{label}</dt>
      <dd className="text-xs text-on-surface font-mono text-right break-all">{value || "—"}</dd>
    </div>
  );
}

function CopyList({ title, items, copyAllLabel }: { title: string; items: string[]; copyAllLabel: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-label font-bold text-on-surface uppercase tracking-wider">{title}</h3>
        {items.length > 0 ? <CopyButton text={items.join("\n")} label={copyAllLabel} /> : null}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-on-surface-variant/70">Nothing to enter.</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item) => (
            <li
              key={item}
              className="flex items-center justify-between gap-2 rounded-lg bg-surface-container-low px-3 py-1 border border-outline-variant/20"
            >
              <code className="font-mono text-xs text-on-surface">{item}</code>
              <CopyButton text={item} label={`Copy ${item}`} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function OverviewTab({ data }: { data: OrgData }) {
  const { detail, overview, cortex } = data;
  const doc = detail.document;
  const departments = Object.entries(overview.departments).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const maxDept = departments.reduce((m, [, n]) => Math.max(m, n), 1);
  const hostRoles = Object.entries(overview.hosts).sort((a, b) => b[1] - a[1]);
  const sites = doc.sites ?? [];

  return (
    <div className="space-y-6">
      <WarningList lines={overview.warnings} title="Worth a look" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="About" icon="info">
          <p className="text-sm text-on-surface-variant leading-relaxed">
            {overview.description || "No description."}
          </p>
          <dl>
            <KeyValue label="Domain" value={overview.domain.dns} />
            <KeyValue label="NetBIOS" value={overview.domain.netbios} />
            <KeyValue label="Email domain" value={overview.domain.email_domain} />
            <KeyValue label="Partner domain" value={overview.domain.partner_domain} />
            <KeyValue label="Time zone" value={overview.timezone} />
            <KeyValue label="Administrators" value={String(overview.admin_accounts)} />
            <KeyValue label="Service accounts" value={String(overview.service_accounts)} />
          </dl>
          {sites.length > 0 ? (
            <div className="space-y-1.5">
              <h3 className="text-xs font-label font-bold text-on-surface uppercase tracking-wider">Sites</h3>
              <div className="flex flex-wrap gap-1.5">
                {sites.map((s) => (
                  <Chip key={s.id} tone={s.kind === "cloud" ? "primary" : "neutral"} title={s.name}>
                    {s.id} · {s.kind}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}
          {hostRoles.length > 0 ? (
            <div className="space-y-1.5">
              <h3 className="text-xs font-label font-bold text-on-surface uppercase tracking-wider">Hosts by role</h3>
              <div className="flex flex-wrap gap-1.5">
                {hostRoles.map(([role, n]) => (
                  <Chip key={role}>
                    {role} {n}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}
        </Panel>

        <Panel title="Departments" icon="groups">
          {departments.length === 0 ? (
            <p className="text-xs text-on-surface-variant/70">No people yet.</p>
          ) : (
            <ul className="space-y-2">
              {departments.map(([name, n]) => (
                <li key={name} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-on-surface">{name}</span>
                    <span className="font-mono text-on-surface-variant">{n}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-surface-container-high overflow-hidden" aria-hidden="true">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${(n / maxDept) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Cortex setup" icon="shield">
        <p className="text-xs text-on-surface-variant leading-relaxed">
          Enter these in Cortex under <strong className="text-on-surface">Inventory &gt; Assets &gt; Network Configuration</strong>{" "}
          so internal and external addresses are told apart the same way this organization tells them apart.
        </p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <CopyList title="Internal IP ranges" items={cortex.internal_ranges} copyAllLabel="Copy all internal IP ranges" />
          <CopyList title="Domain suffixes" items={cortex.domain_suffixes} copyAllLabel="Copy all domain suffixes" />
        </div>
        <div className="space-y-2">
          <h3 className="text-xs font-label font-bold text-on-surface uppercase tracking-wider">Networks</h3>
          <TableShell caption="Networks and their address ranges">
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>VLAN</Th>
                <Th>Address range</Th>
              </tr>
            </thead>
            <tbody>
              {cortex.networks.map((n) => (
                <tr key={n.id} className={ROW_CLASS}>
                  <Td>{n.name}</Td>
                  <Td mono>{n.vlan ?? "—"}</Td>
                  <Td mono>{networkAddress({ cidrs: n.cidrs })}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        </div>
      </Panel>
    </div>
  );
}
