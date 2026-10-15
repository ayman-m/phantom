"use client";

/**
 * Organization: the one fictitious company (people, accounts, hosts,
 * networks, sites, groups) that every Phantom log generator uses, so events
 * from Okta, Windows, firewalls and cloud stitch into one story in Cortex.
 *
 * Phantom ships a read-only built-in organization. The operator can
 * duplicate it into an editable copy, import their own, switch which one is
 * active (switching deletes nothing), edit, export and undo through history.
 * State and actions live in components/organization/use-organization.tsx;
 * the REST contract is bundles/spark/mcp/src/api/organizations.py, reached
 * through /api/agent/organizations.
 */

import { useRef, useState, type KeyboardEvent } from "react";
import { isBuiltIn } from "@/lib/organization-types";
import { cn } from "@/lib/utils";
import { GroupsTab } from "@/components/organization/groups-tab";
import { OrganizationHeader } from "@/components/organization/header";
import { HostsTab } from "@/components/organization/hosts-tab";
import { NetworksTab } from "@/components/organization/networks-tab";
import { OverviewTab } from "@/components/organization/overview-tab";
import { PeopleTab } from "@/components/organization/people-tab";
import { EmptyState, LoadFailed, PageSkeleton } from "@/components/organization/ui";
import { useOrganization } from "@/components/organization/use-organization";
import { YamlTab } from "@/components/organization/yaml-tab";

type TabId = "overview" | "people" | "hosts" | "networks" | "groups" | "yaml";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "dashboard" },
  { id: "people", label: "People", icon: "group" },
  { id: "hosts", label: "Hosts", icon: "dns" },
  { id: "networks", label: "Networks", icon: "lan" },
  { id: "groups", label: "Groups & accounts", icon: "badge" },
  { id: "yaml", label: "YAML", icon: "code" },
];

export default function OrganizationPage() {
  const ctl = useOrganization();
  const [tab, setTab] = useState<TabId>("overview");
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});

  const organizations = ctl.list?.organizations ?? [];
  const selected = organizations.find((o) => o.id === ctl.selectedId) ?? null;
  const data = ctl.data;
  const builtIn = selected ? isBuiltIn(selected) : false;

  function onTabKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = TABS.length - 1;
    else return;
    e.preventDefault();
    const id = TABS[next].id;
    setTab(id);
    tabRefs.current[id]?.focus();
  }

  const tabCount = (id: TabId): number | null => {
    if (!data) return null;
    if (id === "people") return data.people.total;
    if (id === "hosts") return data.hosts.total;
    if (id === "networks") return data.networks.total;
    return null;
  };

  let body: React.ReactNode;
  if (ctl.list === null) {
    body = ctl.listError ? (
      <LoadFailed lines={ctl.listError} onRetry={() => void ctl.refresh()} />
    ) : (
      <PageSkeleton />
    );
  } else if (ctl.list.count === 0) {
    body = (
      <EmptyState icon="apartment" title="No organization yet">
        Use Import to add one.
      </EmptyState>
    );
  } else if (ctl.loadError) {
    body = <LoadFailed lines={ctl.loadError} onRetry={() => void ctl.refresh()} />;
  } else if (!data) {
    body = <PageSkeleton />;
  } else {
    body = (
      <div className="space-y-5">
        <div role="tablist" aria-label="Organization sections" className="flex gap-1 flex-wrap border-b border-outline-variant/20">
          {TABS.map((t, i) => {
            const selectedTab = tab === t.id;
            const count = tabCount(t.id);
            return (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                type="button"
                role="tab"
                id={`org-tab-${t.id}`}
                aria-selected={selectedTab}
                aria-controls={`org-panel-${t.id}`}
                tabIndex={selectedTab ? 0 : -1}
                onClick={() => setTab(t.id)}
                onKeyDown={(e) => onTabKey(e, i)}
                className={cn(
                  "inline-flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-t-lg",
                  selectedTab
                    ? "border-primary text-primary"
                    : "border-transparent text-on-surface-variant hover:text-on-surface",
                )}
              >
                <span className="material-symbols-outlined text-base" aria-hidden="true">
                  {t.icon}
                </span>
                {t.label}
                {count !== null ? <span className="font-mono text-[10px] text-on-surface-variant/60">{count}</span> : null}
              </button>
            );
          })}
        </div>
        <div role="tabpanel" id={`org-panel-${tab}`} aria-labelledby={`org-tab-${tab}`}>
          {tab === "overview" ? <OverviewTab data={data} /> : null}
          {tab === "people" ? <PeopleTab data={data} ctl={ctl} builtIn={builtIn} /> : null}
          {tab === "hosts" ? <HostsTab data={data} ctl={ctl} builtIn={builtIn} /> : null}
          {tab === "networks" ? <NetworksTab data={data} ctl={ctl} builtIn={builtIn} /> : null}
          {tab === "groups" ? <GroupsTab data={data} /> : null}
          {tab === "yaml" ? <YamlTab key={data.detail.id} data={data} ctl={ctl} builtIn={builtIn} /> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1400px] mx-auto px-8 py-8 space-y-6">
        {ctl.list !== null ? <OrganizationHeader ctl={ctl} selected={selected} data={data} /> : null}
        {body}
      </div>
    </div>
  );
}
