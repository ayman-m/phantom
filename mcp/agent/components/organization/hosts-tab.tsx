"use client";

import { useMemo, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import {
  HOST_ROLES,
  filterHosts,
  hostFormError,
  hostRow,
  type HostForm,
  type HostRole,
  type HostRow,
} from "@/lib/organization-types";
import {
  Button,
  CheckField,
  Chip,
  EmptyState,
  ErrorList,
  FilterSelect,
  IconButton,
  Modal,
  NotesBanner,
  ROW_CLASS,
  SearchField,
  SelectField,
  TableShell,
  Td,
  TextField,
  Th,
  TruncatedNote,
  type SelectOption,
} from "./ui";
import type { OrgData, OrganizationController } from "./use-organization";

const ROLE_LABEL: Record<HostRole, string> = {
  dc: "Domain controller",
  server: "Server",
  dmz: "DMZ",
  workstation: "Workstation",
  network: "Network device",
  security: "Security tool",
  cloud: "Cloud",
};

function HostDialog({
  existing,
  data,
  builtIn,
  ctl,
  onClose,
  onDone,
}: {
  existing: HostRow | null;
  data: OrgData;
  builtIn: boolean;
  ctl: OrganizationController;
  onClose: () => void;
  onDone: (notes: string[]) => void;
}) {
  const networks = data.detail.document.networks;
  const sites = data.detail.document.sites ?? [];
  const [form, setForm] = useState<HostForm>({
    name: existing?.name ?? "",
    role: existing?.role ?? "server",
    ip: existing?.ip ?? "",
    network: existing?.network ?? networks[0]?.id ?? "",
    site: existing?.site ?? "",
    os: existing?.os ?? "",
    purpose: existing?.purpose ?? "",
    owner: existing?.owner ?? "",
    domain_joined: existing?.domain_joined ?? false,
  });
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const set = <K extends keyof HostForm>(k: K, v: HostForm[K]) => setForm((f) => ({ ...f, [k]: v }));
  const isNew = existing === null;

  const networkOptions: SelectOption[] = networks.map((n) => ({ value: n.id, label: `${n.name} (${n.id})` }));
  const siteOptions: SelectOption[] = [
    { value: "", label: "None" },
    ...sites.map((s) => ({ value: s.id, label: `${s.id} · ${s.name}` })),
  ];
  const ownerOptions: SelectOption[] = [
    { value: "", label: "No owner" },
    ...data.people.rows.map((p) => ({ value: p.login, label: `${p.name} (${p.login})` })),
  ];

  async function submit() {
    const problem = hostFormError(form);
    if (problem) {
      setErrors([problem]);
      return;
    }
    setBusy(true);
    setErrors([]);
    const res = await ctl.applyChanges({ upsert: { hosts: [hostRow(form, isNew)] } });
    setBusy(false);
    if (res.ok) {
      onDone(res.value.notes);
      onClose();
    } else {
      setErrors(res.lines);
    }
  }

  return (
    <Modal
      title={isNew ? "Add a host" : `Edit ${existing.name}`}
      icon="dns"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" icon="save" busy={busy} onClick={() => void submit()}>
            {isNew ? "Add host" : "Save"}
          </Button>
        </>
      }
    >
      {builtIn ? (
        <p className="text-xs text-on-surface-variant">
          The built-in organization is read-only, so saving creates your own copy.
        </p>
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <TextField
          label="Name"
          value={form.name}
          onChange={(v) => set("name", v)}
          disabled={!isNew}
          mono
          hint={isNew ? undefined : "The name identifies the host and cannot be changed."}
        />
        <SelectField
          label="Role"
          value={form.role}
          onChange={(v) => set("role", v as HostRole)}
          options={HOST_ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))}
        />
        <TextField label="IP address" value={form.ip} onChange={(v) => set("ip", v)} mono placeholder="10.20.1.30" />
        <SelectField label="Network" value={form.network} onChange={(v) => set("network", v)} options={networkOptions} />
        <SelectField label="Site" value={form.site} onChange={(v) => set("site", v)} options={siteOptions} />
        <TextField label="Operating system" value={form.os} onChange={(v) => set("os", v)} placeholder="Windows Server 2022" />
      </div>
      <TextField label="Purpose" value={form.purpose} onChange={(v) => set("purpose", v)} placeholder="File server" />
      {form.role === "workstation" ? (
        <SelectField
          label="Owner"
          value={form.owner}
          onChange={(v) => set("owner", v)}
          options={ownerOptions}
          hint="The person who uses this workstation."
        />
      ) : null}
      <CheckField label="Joined to the domain" checked={form.domain_joined} onChange={(v) => set("domain_joined", v)} />
      <ErrorList lines={errors} title="Change rejected" />
    </Modal>
  );
}

export function HostsTab({ data, ctl, builtIn }: { data: OrgData; ctl: OrganizationController; builtIn: boolean }) {
  const rows = data.hosts.rows;
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [dialog, setDialog] = useState<{ host: HostRow | null } | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  const visible = useMemo(() => filterHosts(rows, search, role), [rows, search, role]);
  const roleOptions: SelectOption[] = [
    { value: "", label: "All" },
    ...HOST_ROLES.filter((r) => rows.some((h) => h.role === r)).map((r) => ({ value: r, label: r })),
  ];

  async function remove(h: HostRow) {
    const accepted = await confirmAction({
      title: `Remove ${h.name}?`,
      message: "The host is removed from the organization. If a person or account still uses it, the server will say so and nothing changes.",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!accepted) return;
    const res = await ctl.applyChanges({ remove: { hosts: [h.name] } });
    if (res.ok) setNotes(res.value.notes);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <SearchField
          value={search}
          onChange={setSearch}
          label="Search hosts"
          placeholder="Search name, role, IP, network, site, owner, purpose…"
        />
        <FilterSelect label="Role" value={role} onChange={setRole} options={roleOptions} />
        <span className="text-xs text-on-surface-variant/60 font-mono">
          {visible.length} of {data.hosts.total}
        </span>
        <Button tone="primary" icon="add" onClick={() => setDialog({ host: null })}>
          Add host
        </Button>
      </div>

      <NotesBanner notes={notes} onDismiss={() => setNotes([])} />
      {data.hosts.truncated ? <TruncatedNote shown={data.hosts.returned} total={data.hosts.total} /> : null}

      {rows.length === 0 ? (
        <EmptyState icon="dns" title="No hosts">
          Add a host to get started.
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState icon="search_off" title="No host matches">
          Clear the search or the role filter.
        </EmptyState>
      ) : (
        <TableShell caption="Hosts in the organization">
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Role</Th>
              <Th>IP address</Th>
              <Th>Network</Th>
              <Th>Site</Th>
              <Th>OS</Th>
              <Th>Owner</Th>
              <Th>Purpose</Th>
              <Th>
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {visible.map((h) => (
              <tr key={h.name} className={ROW_CLASS}>
                <Td mono>{h.name}</Td>
                <Td>
                  <Chip>{h.role}</Chip>
                </Td>
                <Td mono>{h.ip}</Td>
                <Td mono>{h.network}</Td>
                <Td>{h.site ?? "—"}</Td>
                <Td>{h.os ?? "—"}</Td>
                <Td mono>{h.owner ?? "—"}</Td>
                <Td>{h.purpose ?? "—"}</Td>
                <Td className="whitespace-nowrap text-right">
                  <IconButton icon="edit" label={`Edit ${h.name}`} onClick={() => setDialog({ host: h })} />
                  <IconButton icon="delete" label={`Remove ${h.name}`} tone="danger" onClick={() => void remove(h)} />
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}

      {dialog ? (
        <HostDialog
          existing={dialog.host}
          data={data}
          builtIn={builtIn}
          ctl={ctl}
          onClose={() => setDialog(null)}
          onDone={setNotes}
        />
      ) : null}
    </div>
  );
}
