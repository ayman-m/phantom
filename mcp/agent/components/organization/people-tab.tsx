"use client";

import { useMemo, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import {
  PERSON_FLAGS,
  departmentsOf,
  filterPeople,
  newPersonRow,
  personEditError,
  personEditRow,
  personFormError,
  type OrgSite,
  type PersonEditForm,
  type PersonFlag,
  type PersonForm,
  type PersonRow,
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
  Panel,
  ROW_CLASS,
  SearchField,
  SelectField,
  TableShell,
  Td,
  TextField,
  Th,
  TruncatedNote,
  type ChipTone,
  type SelectOption,
} from "./ui";
import type { OrgData, OrganizationController } from "./use-organization";

const NEW_DEPARTMENT = "__new__";

const FLAG_TONE: Record<PersonFlag, ChipTone> = {
  vip: "primary",
  outlier: "warning",
  contractor: "neutral",
  leaver: "danger",
};

const FLAG_HELP: Record<PersonFlag, string> = {
  vip: "Target of phishing, BEC and MFA-fatigue scenarios",
  outlier: "Designated source of insider and in-network attacks",
  contractor: "External contractor",
  leaver: "Account is disabled; any logon by it is the finding",
};

/** Sites a person can sit at: offices and remote, not cloud accounts. */
function personSites(sites: OrgSite[] | undefined): SelectOption[] {
  return (sites ?? []).filter((s) => s.kind !== "cloud").map((s) => ({ value: s.id, label: `${s.id} · ${s.name}` }));
}

/** Pick an existing department or type a new one. */
function DepartmentField({
  value,
  onChange,
  departments,
}: {
  value: string;
  onChange: (v: string) => void;
  departments: string[];
}) {
  const [custom, setCustom] = useState(value !== "" && !departments.includes(value));
  const options: SelectOption[] = [
    { value: "", label: "Choose…" },
    ...departments.map((d) => ({ value: d, label: d })),
    { value: NEW_DEPARTMENT, label: "New department…" },
  ];
  return (
    <div className="space-y-2">
      <SelectField
        label="Department"
        value={custom ? NEW_DEPARTMENT : value}
        onChange={(v) => {
          if (v === NEW_DEPARTMENT) {
            setCustom(true);
            onChange("");
          } else {
            setCustom(false);
            onChange(v);
          }
        }}
        options={options}
      />
      {custom ? <TextField label="New department name" value={value} onChange={onChange} /> : null}
    </div>
  );
}

// ─── Add person ──────────────────────────────────────────────────────────────

const EMPTY_PERSON: PersonForm = { given_name: "", family_name: "", title: "", department: "", site: "" };

function AddPersonForm({
  ctl,
  departments,
  sites,
  builtIn,
  onDone,
  onCancel,
}: {
  ctl: OrganizationController;
  departments: string[];
  sites: SelectOption[];
  builtIn: boolean;
  onDone: (notes: string[]) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<PersonForm>(EMPTY_PERSON);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const set = <K extends keyof PersonForm>(k: K, v: PersonForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function submit() {
    const problem = personFormError(form);
    if (problem) {
      setErrors([problem]);
      return;
    }
    setBusy(true);
    setErrors([]);
    const res = await ctl.applyChanges({ upsert: { people: [newPersonRow(form)] } });
    setBusy(false);
    if (res.ok) onDone(res.value.notes);
    else setErrors(res.lines);
  }

  return (
    <Panel title="Add a person" icon="person_add">
      <p className="text-xs text-on-surface-variant leading-relaxed">
        Name, title and department are enough. The login, email address, workstation (with its host and address),
        account identifiers, groups and manager are filled in for you, and what was created is listed afterwards.
        {builtIn ? " The built-in organization is read-only, so this saves your own copy." : ""}
      </p>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <TextField label="Given name" value={form.given_name} onChange={(v) => set("given_name", v)} />
          <TextField label="Family name" value={form.family_name} onChange={(v) => set("family_name", v)} />
          <TextField label="Job title" value={form.title} onChange={(v) => set("title", v)} />
          <DepartmentField value={form.department} onChange={(v) => set("department", v)} departments={departments} />
          <SelectField
            label="Site (optional)"
            value={form.site}
            onChange={(v) => set("site", v)}
            options={[{ value: "", label: "Let Phantom choose" }, ...sites]}
          />
        </div>
        <ErrorList lines={errors} title="Could not add the person" />
        <div className="flex gap-2">
          <Button type="submit" tone="primary" icon="person_add" busy={busy}>
            Add person
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Panel>
  );
}

// ─── Edit person ─────────────────────────────────────────────────────────────

function EditPersonDialog({
  person,
  people,
  departments,
  sites,
  builtIn,
  ctl,
  onClose,
  onDone,
}: {
  person: PersonRow;
  people: PersonRow[];
  departments: string[];
  sites: SelectOption[];
  builtIn: boolean;
  ctl: OrganizationController;
  onClose: () => void;
  onDone: (notes: string[]) => void;
}) {
  const [form, setForm] = useState<PersonEditForm>({
    title: person.title,
    department: person.department,
    manager: person.manager ?? "",
    site: person.site,
    flags: person.flags ?? [],
  });
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const managerOptions: SelectOption[] = [
    { value: "", label: "No manager" },
    ...people
      .filter((p) => p.login !== person.login)
      .map((p) => ({ value: p.login, label: `${p.name} (${p.login})` })),
  ];
  const siteOptions = sites.some((s) => s.value === form.site) ? sites : [{ value: form.site, label: form.site }, ...sites];

  function toggleFlag(flag: PersonFlag, on: boolean) {
    setForm((f) => ({
      ...f,
      flags: on ? [...f.flags.filter((x) => x !== flag), flag] : f.flags.filter((x) => x !== flag),
    }));
  }

  async function submit() {
    const problem = personEditError(form);
    if (problem) {
      setErrors([problem]);
      return;
    }
    setBusy(true);
    setErrors([]);
    const res = await ctl.applyChanges({ upsert: { people: [personEditRow(person.login, form)] } });
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
      title={`Edit ${person.name}`}
      icon="edit"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" icon="save" busy={busy} onClick={() => void submit()}>
            Save
          </Button>
        </>
      }
    >
      <p className="text-xs text-on-surface-variant">
        Login <code className="font-mono text-on-surface">{person.login}</code> identifies this person and cannot be
        changed here.
        {builtIn ? " The built-in organization is read-only, so saving creates your own copy." : ""}
      </p>
      <TextField label="Job title" value={form.title} onChange={(v) => setForm((f) => ({ ...f, title: v }))} />
      <DepartmentField
        value={form.department}
        onChange={(v) => setForm((f) => ({ ...f, department: v }))}
        departments={departments}
      />
      <SelectField
        label="Manager"
        value={form.manager}
        onChange={(v) => setForm((f) => ({ ...f, manager: v }))}
        options={managerOptions}
      />
      <SelectField label="Site" value={form.site} onChange={(v) => setForm((f) => ({ ...f, site: v }))} options={siteOptions} />
      <fieldset className="space-y-2">
        <legend className="text-xs font-label text-on-surface-variant/80 mb-1">Flags</legend>
        {PERSON_FLAGS.map((flag) => (
          <CheckField
            key={flag}
            label={flag}
            hint={FLAG_HELP[flag]}
            checked={form.flags.includes(flag)}
            onChange={(on) => toggleFlag(flag, on)}
          />
        ))}
      </fieldset>
      <ErrorList lines={errors} title="Change rejected" />
    </Modal>
  );
}

// ─── Tab ─────────────────────────────────────────────────────────────────────

export function PeopleTab({ data, ctl, builtIn }: { data: OrgData; ctl: OrganizationController; builtIn: boolean }) {
  const rows = data.people.rows;
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<PersonRow | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  const departments = useMemo(() => departmentsOf(rows), [rows]);
  const sites = useMemo(() => personSites(data.detail.document.sites), [data.detail.document.sites]);
  const visible = useMemo(() => filterPeople(rows, search, department), [rows, search, department]);

  async function remove(p: PersonRow) {
    const accepted = await confirmAction({
      title: `Remove ${p.name}?`,
      message: `${p.login} is removed from the organization. Their manager takes over their reports. Their workstation stays but loses its owner.`,
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!accepted) return;
    const res = await ctl.applyChanges({ remove: { people: [p.login] } });
    if (res.ok) setNotes(res.value.notes);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <SearchField
          value={search}
          onChange={setSearch}
          label="Search people"
          placeholder="Search login, name, title, workstation, address…"
        />
        <FilterSelect
          label="Department"
          value={department}
          onChange={setDepartment}
          options={[{ value: "", label: "All" }, ...departments.map((d) => ({ value: d, label: d }))]}
        />
        <span className="text-xs text-on-surface-variant/60 font-mono">
          {visible.length} of {data.people.total}
        </span>
        <Button tone="primary" icon="person_add" onClick={() => setAdding((a) => !a)}>
          Add person
        </Button>
      </div>

      <NotesBanner notes={notes} onDismiss={() => setNotes([])} />

      {adding ? (
        <AddPersonForm
          ctl={ctl}
          departments={departments}
          sites={sites}
          builtIn={builtIn}
          onCancel={() => setAdding(false)}
          onDone={(n) => {
            setNotes(n);
            setAdding(false);
          }}
        />
      ) : null}

      {data.people.truncated ? <TruncatedNote shown={data.people.returned} total={data.people.total} /> : null}

      {rows.length === 0 ? (
        <EmptyState icon="person_off" title="No people">
          Add a person to get started.
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState icon="search_off" title="Nobody matches">
          Clear the search or the department filter.
        </EmptyState>
      ) : (
        <TableShell caption="People in the organization">
          <thead>
            <tr>
              <Th>Login</Th>
              <Th>Name</Th>
              <Th>Title</Th>
              <Th>Department</Th>
              <Th>Manager</Th>
              <Th>Site</Th>
              <Th>Workstation</Th>
              <Th>Workstation IP</Th>
              <Th>Admin login</Th>
              <Th>Flags</Th>
              <Th>
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <tr key={p.login} className={ROW_CLASS}>
                <Td mono>{p.login}</Td>
                <Td className="whitespace-nowrap">{p.name}</Td>
                <Td>{p.title}</Td>
                <Td>{p.department}</Td>
                <Td mono>{p.manager ?? "—"}</Td>
                <Td>{p.site}</Td>
                <Td mono>{p.workstation}</Td>
                <Td mono>{p.workstation_ip ?? "—"}</Td>
                <Td mono>{p.admin_login ?? "—"}</Td>
                <Td>
                  <div className="flex gap-1 flex-wrap">
                    {(p.flags ?? []).map((f) => (
                      <Chip key={f} tone={FLAG_TONE[f]} title={FLAG_HELP[f]}>
                        {f}
                      </Chip>
                    ))}
                  </div>
                </Td>
                <Td className="whitespace-nowrap text-right">
                  <IconButton icon="edit" label={`Edit ${p.name}`} onClick={() => setEditing(p)} />
                  <IconButton icon="person_remove" label={`Remove ${p.name}`} tone="danger" onClick={() => void remove(p)} />
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}

      {editing ? (
        <EditPersonDialog
          person={editing}
          people={rows}
          departments={departments}
          sites={sites}
          builtIn={builtIn}
          ctl={ctl}
          onClose={() => setEditing(null)}
          onDone={setNotes}
        />
      ) : null}
    </div>
  );
}
