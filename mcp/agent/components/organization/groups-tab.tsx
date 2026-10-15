"use client";

import { useMemo, useState } from "react";
import { filterAccounts, type AccountKind } from "@/lib/organization-types";
import {
  Chip,
  EmptyState,
  FilterSelect,
  Panel,
  ROW_CLASS,
  SearchField,
  TableShell,
  Td,
  Th,
  TruncatedNote,
  type ChipTone,
} from "./ui";
import type { OrgData } from "./use-organization";

const KIND_LABEL: Record<AccountKind, string> = {
  user: "User",
  admin: "Administrator",
  service: "Service",
  break_glass: "Break-glass",
};

const KIND_TONE: Record<AccountKind, ChipTone> = {
  user: "neutral",
  admin: "warning",
  service: "primary",
  break_glass: "danger",
};

export function GroupsTab({ data }: { data: OrgData }) {
  const groups = data.groups.rows;
  const accounts = data.accounts.rows;
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const visible = useMemo(() => filterAccounts(accounts, search, kind), [accounts, search, kind]);

  // Privileged groups first, then by size.
  const sortedGroups = useMemo(
    () =>
      [...groups].sort(
        (a, b) =>
          Number(Boolean(b.privileged)) - Number(Boolean(a.privileged)) ||
          b.members.length - a.members.length ||
          a.name.localeCompare(b.name),
      ),
    [groups],
  );

  return (
    <div className="space-y-6">
      <Panel title="Groups" icon="group_work">
        {data.groups.truncated ? <TruncatedNote shown={data.groups.returned} total={data.groups.total} /> : null}
        {groups.length === 0 ? (
          <EmptyState icon="group_off" title="No groups" />
        ) : (
          <TableShell caption="Groups and their members">
            <thead>
              <tr>
                <Th>Group</Th>
                <Th>Members</Th>
                <Th>Who</Th>
                <Th>Description</Th>
              </tr>
            </thead>
            <tbody>
              {sortedGroups.map((g) => (
                <tr
                  key={g.name}
                  className={`${ROW_CLASS} ${g.privileged ? "bg-error/5" : ""}`}
                >
                  <Td>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-[11px]">{g.name}</span>
                      {g.privileged ? <Chip tone="danger">privileged</Chip> : null}
                    </div>
                  </Td>
                  <Td mono>{g.members.length}</Td>
                  <Td className="max-w-[420px]">
                    {g.members.length === 0 ? (
                      <span className="text-on-surface-variant/60">—</span>
                    ) : (
                      <details>
                        <summary className="cursor-pointer text-on-surface-variant hover:text-on-surface">
                          Show {g.members.length === 1 ? "member" : "members"}
                        </summary>
                        <p className="mt-1 font-mono text-[11px] text-on-surface-variant break-words">
                          {g.members.join(", ")}
                        </p>
                      </details>
                    )}
                  </Td>
                  <Td className="text-on-surface-variant">{g.description ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>

      <Panel title="Accounts" icon="badge">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchField
            value={search}
            onChange={setSearch}
            label="Search accounts"
            placeholder="Search login, person, SID, host, group…"
          />
          <FilterSelect
            label="Kind"
            value={kind}
            onChange={setKind}
            options={[
              { value: "", label: "All" },
              { value: "user", label: "User" },
              { value: "admin", label: "Administrator" },
              { value: "service", label: "Service" },
              { value: "break_glass", label: "Break-glass" },
            ]}
          />
          <span className="text-xs text-on-surface-variant/60 font-mono">
            {visible.length} of {data.accounts.total}
          </span>
        </div>
        {data.accounts.truncated ? <TruncatedNote shown={data.accounts.returned} total={data.accounts.total} /> : null}
        {accounts.length === 0 ? (
          <EmptyState icon="badge" title="No accounts" />
        ) : visible.length === 0 ? (
          <EmptyState icon="search_off" title="No account matches">
            Clear the search or the kind filter.
          </EmptyState>
        ) : (
          <TableShell caption="Accounts in the organization">
            <thead>
              <tr>
                <Th>Login</Th>
                <Th>Kind</Th>
                <Th>Person</Th>
                <Th>SID</Th>
                <Th>Host</Th>
                <Th>Groups</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => (
                <tr key={`${a.kind}-${a.login}`} className={ROW_CLASS}>
                  <Td mono>{a.login}</Td>
                  <Td>
                    <Chip tone={KIND_TONE[a.kind]}>{KIND_LABEL[a.kind]}</Chip>
                  </Td>
                  <Td mono>{a.person ?? "—"}</Td>
                  <Td mono className="break-all">
                    {a.sid ?? "—"}
                  </Td>
                  <Td mono>
                    {a.host}
                    {a.host_ip ? <span className="text-on-surface-variant/60"> · {a.host_ip}</span> : null}
                  </Td>
                  <Td>
                    <div className="flex gap-1 flex-wrap">
                      {a.groups.length === 0 ? <span className="text-on-surface-variant/60">—</span> : null}
                      {a.groups.map((g) => (
                        <Chip key={g} tone={groups.find((x) => x.name === g)?.privileged ? "danger" : "neutral"}>
                          {g}
                        </Chip>
                      ))}
                    </div>
                  </Td>
                  <Td>{a.active ? <Chip tone="success">active</Chip> : <Chip tone="danger">disabled</Chip>}</Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
    </div>
  );
}
