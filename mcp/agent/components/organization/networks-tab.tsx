"use client";

import { useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import {
  NETWORK_KINDS,
  networkAddress,
  networkFormError,
  networkRow,
  networkToForm,
  type NetworkForm,
  type NetworkKind,
  type NetworkRow,
} from "@/lib/organization-types";
import {
  Button,
  Chip,
  EmptyState,
  ErrorList,
  IconButton,
  Modal,
  NotesBanner,
  ROW_CLASS,
  SelectField,
  TableShell,
  Td,
  TextField,
  Th,
  TruncatedNote,
  type SelectOption,
} from "./ui";
import type { OrgData, OrganizationController } from "./use-organization";

const EMPTY_NETWORK: NetworkForm = {
  id: "",
  name: "",
  kind: "servers",
  site: "",
  vlan: "",
  mode: "cidr",
  address: "",
};

function NetworkDialog({
  existing,
  data,
  builtIn,
  ctl,
  onClose,
  onDone,
}: {
  existing: NetworkRow | null;
  data: OrgData;
  builtIn: boolean;
  ctl: OrganizationController;
  onClose: () => void;
  onDone: (notes: string[]) => void;
}) {
  const isNew = existing === null;
  const [form, setForm] = useState<NetworkForm>(existing ? networkToForm(existing) : EMPTY_NETWORK);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const set = <K extends keyof NetworkForm>(k: K, v: NetworkForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  const siteOptions: SelectOption[] = [
    { value: "", label: "None" },
    ...(data.detail.document.sites ?? []).map((s) => ({ value: s.id, label: `${s.id} · ${s.name}` })),
  ];

  async function submit() {
    const problem = networkFormError(form);
    if (problem) {
      setErrors([problem]);
      return;
    }
    setBusy(true);
    setErrors([]);
    const res = await ctl.applyChanges({ upsert: { networks: [networkRow(form, isNew)] } });
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
      title={isNew ? "Add a network" : `Edit ${existing.name}`}
      icon="lan"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" icon="save" busy={busy} onClick={() => void submit()}>
            {isNew ? "Add network" : "Save"}
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
          label="Id"
          value={form.id}
          onChange={(v) => set("id", v)}
          disabled={!isNew}
          mono
          placeholder="ruh-lab"
          hint={isNew ? "Lowercase letters, digits and dashes." : "The id identifies the network and cannot be changed."}
        />
        <TextField label="Name" value={form.name} onChange={(v) => set("name", v)} placeholder="RUH lab network" />
        <SelectField
          label="Kind"
          value={form.kind}
          onChange={(v) => set("kind", v as NetworkKind)}
          options={NETWORK_KINDS.map((k) => ({ value: k, label: k }))}
        />
        <SelectField label="Site" value={form.site} onChange={(v) => set("site", v)} options={siteOptions} />
        <TextField label="VLAN (optional)" value={form.vlan} onChange={(v) => set("vlan", v)} inputMode="numeric" placeholder="100" />
        <SelectField
          label="Address type"
          value={form.mode}
          onChange={(v) => set("mode", v as NetworkForm["mode"])}
          options={[
            { value: "cidr", label: "CIDR block" },
            { value: "range", label: "Address range" },
          ]}
        />
      </div>
      <TextField
        label={form.mode === "cidr" ? "CIDR" : "Address range"}
        value={form.address}
        onChange={(v) => set("address", v)}
        mono
        placeholder={form.mode === "cidr" ? "10.20.30.0/24" : "10.20.100.0-10.20.199.255"}
      />
      <ErrorList lines={errors} title="Change rejected" />
    </Modal>
  );
}

export function NetworksTab({ data, ctl, builtIn }: { data: OrgData; ctl: OrganizationController; builtIn: boolean }) {
  const rows = data.networks.rows;
  const [dialog, setDialog] = useState<{ network: NetworkRow | null } | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  async function remove(n: NetworkRow) {
    const accepted = await confirmAction({
      title: `Remove ${n.name}?`,
      message: "The network is removed from the organization. If a host still sits on it, the server will say so and nothing changes.",
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!accepted) return;
    const res = await ctl.applyChanges({ remove: { networks: [n.id] } });
    if (res.ok) setNotes(res.value.notes);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap justify-between">
        <span className="text-xs text-on-surface-variant/60 font-mono">{data.networks.total} networks</span>
        <Button tone="primary" icon="add" onClick={() => setDialog({ network: null })}>
          Add network
        </Button>
      </div>

      <NotesBanner notes={notes} onDismiss={() => setNotes([])} />
      {data.networks.truncated ? <TruncatedNote shown={data.networks.returned} total={data.networks.total} /> : null}

      {rows.length === 0 ? (
        <EmptyState icon="lan" title="No networks">
          Add a network to get started.
        </EmptyState>
      ) : (
        <TableShell caption="Networks in the organization">
          <thead>
            <tr>
              <Th>Id</Th>
              <Th>Name</Th>
              <Th>Kind</Th>
              <Th>VLAN</Th>
              <Th>CIDR or range</Th>
              <Th>Site</Th>
              <Th>
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => (
              <tr key={n.id} className={ROW_CLASS}>
                <Td mono>{n.id}</Td>
                <Td>{n.name}</Td>
                <Td>
                  <Chip>{n.kind}</Chip>
                </Td>
                <Td mono>{n.vlan ?? "—"}</Td>
                <Td mono>{networkAddress(n)}</Td>
                <Td>{n.site ?? "—"}</Td>
                <Td className="whitespace-nowrap text-right">
                  <IconButton icon="edit" label={`Edit ${n.name}`} onClick={() => setDialog({ network: n })} />
                  <IconButton icon="delete" label={`Remove ${n.name}`} tone="danger" onClick={() => void remove(n)} />
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}

      {dialog ? (
        <NetworkDialog
          existing={dialog.network}
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
