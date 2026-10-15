"use client";

/**
 * State and actions behind the /organization page.
 *
 * "Viewed" and "active" are different things: `selectedId` is the
 * organization on screen (it starts at the active one), `active` on a record
 * says which one every generator uses. Switching the view changes nothing on
 * the server; Activate does.
 *
 * Every mutation reports through `notify()`: a success toast, or the exact
 * server text on failure. Actions resolve to a MutationResult so a form can
 * also show the same lines inline and stay open.
 */

import yaml from "js-yaml";
import { useCallback, useEffect, useState } from "react";
import { confirmAction } from "@/lib/stores/confirm";
import { notify } from "@/lib/stores/notifications";
import {
  ApiError,
  ORGANIZATIONS_PATH,
  SECTION_LIMIT,
  VALIDATE_PATH,
  errorLines,
  errorSummary,
  isBuiltIn,
  orgPath,
  orgRequest,
  rewriteForCopy,
  type AccountRow,
  type CortexSetup,
  type GroupRow,
  type HostRow,
  type NetworkRow,
  type OrgChangeResult,
  type OrgChanges,
  type OrgDetail,
  type OrgListResponse,
  type OrgMeta,
  type OverviewSection,
  type PersonRow,
  type SectionResponse,
  type ValidateResult,
} from "@/lib/organization-types";

export interface OrgData {
  detail: OrgDetail;
  overview: OverviewSection;
  cortex: CortexSetup;
  people: SectionResponse<PersonRow>;
  hosts: SectionResponse<HostRow>;
  networks: SectionResponse<NetworkRow>;
  groups: SectionResponse<GroupRow>;
  accounts: SectionResponse<AccountRow>;
}

export type MutationResult<T> = { ok: true; value: T } | { ok: false; lines: string[] };

async function attempt<T>(fn: () => Promise<T>, failTitle: string): Promise<MutationResult<T>> {
  try {
    return { ok: true, value: await fn() };
  } catch (err) {
    notify("error", failTitle, errorSummary(err));
    return { ok: false, lines: errorLines(err) };
  }
}

function section<Row>(id: string, name: string, signal: AbortSignal): Promise<SectionResponse<Row>> {
  return orgRequest<SectionResponse<Row>>(orgPath(id, "section", { name, limit: SECTION_LIMIT, detail: 1, max_bytes: 2000000 }), { signal });
}

async function fetchOrgData(id: string, signal: AbortSignal): Promise<OrgData> {
  const [detail, overview, cortex, people, hosts, networks, groups, accounts] = await Promise.all([
    orgRequest<OrgDetail>(orgPath(id), { signal }),
    orgRequest<OverviewSection>(orgPath(id, "section", { name: "overview" }), { signal }),
    orgRequest<CortexSetup>(orgPath(id, "cortex-setup"), { signal }),
    section<PersonRow>(id, "people", signal),
    section<HostRow>(id, "hosts", signal),
    section<NetworkRow>(id, "networks", signal),
    section<GroupRow>(id, "groups", signal),
    section<AccountRow>(id, "accounts", signal),
  ]);
  return { detail, overview, cortex, people, hosts, networks, groups, accounts };
}

export function useOrganization() {
  const [list, setList] = useState<OrgListResponse | null>(null);
  const [listError, setListError] = useState<string[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [data, setData] = useState<OrgData | null>(null);
  const [loadError, setLoadError] = useState<string[] | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const loadList = useCallback(async (): Promise<OrgListResponse | null> => {
    try {
      const l = await orgRequest<OrgListResponse>(ORGANIZATIONS_PATH);
      setList(l);
      setListError(null);
      return l;
    } catch (err) {
      setListError(errorLines(err));
      return null;
    }
  }, []);

  // First load: the list, then the active organization is the one on screen.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const l = await loadList();
      if (cancelled || !l) return;
      setSelectedId((prev) => prev ?? l.active_id ?? l.organizations[0]?.id ?? null);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadList]);

  // The organization on screen. A late answer for an organization the
  // operator has already left is dropped (the request is aborted).
  useEffect(() => {
    if (!selectedId) return;
    const ctl = new AbortController();
    setLoadError(null);
    void (async () => {
      try {
        const next = await fetchOrgData(selectedId, ctl.signal);
        if (!ctl.signal.aborted) setData(next);
      } catch (err) {
        if (!ctl.signal.aborted) setLoadError(errorLines(err));
      }
    })();
    return () => ctl.abort();
  }, [selectedId, reloadTick]);

  const refresh = useCallback(async () => {
    const l = await loadList();
    // A failed first load leaves nothing selected; a retry picks the active one.
    if (l) setSelectedId((prev) => prev ?? l.active_id ?? l.organizations[0]?.id ?? null);
    setReloadTick((t) => t + 1);
  }, [loadList]);

  const select = useCallback((id: string) => setSelectedId(id), []);

  const ready = data !== null && selectedId !== null && data.detail.id === selectedId;

  // ── Switching, copying, importing, deleting ────────────────────────────────

  const activate = useCallback(
    async (meta: OrgMeta): Promise<MutationResult<OrgDetail>> => {
      const res = await attempt(
        () => orgRequest<OrgDetail>(orgPath(meta.id, "activate"), { method: "POST" }),
        "Could not switch organization",
      );
      if (res.ok) {
        notify("success", `${meta.name} is now active`, "Every generator uses it from now on. Switching removes nothing.");
        await refresh();
      }
      return res;
    },
    [refresh],
  );

  const duplicate = useCallback(
    async (meta: OrgMeta, newName: string, makeActive: boolean): Promise<MutationResult<OrgDetail>> => {
      const res = await attempt(async () => {
        const copy = await orgRequest<OrgDetail>(orgPath(meta.id, "fork"), {
          method: "POST",
          body: newName.trim() ? { new_name: newName.trim() } : {},
        });
        if (makeActive) return orgRequest<OrgDetail>(orgPath(copy.id, "activate"), { method: "POST" });
        return copy;
      }, "Could not duplicate the organization");
      if (res.ok) {
        notify("success", "Copy created", `${res.value.name} is yours to edit.${makeActive ? " It is now active." : ""}`);
        setSelectedId(res.value.id);
        await refresh();
      }
      return res;
    },
    [refresh],
  );

  const importText = useCallback(
    async (input: {
      text: string;
      format: "yaml" | "json";
      activate: boolean;
      replace: boolean;
    }): Promise<MutationResult<OrgDetail>> => {
      const res = await attempt(
        () => orgRequest<OrgDetail>(ORGANIZATIONS_PATH, { method: "POST", body: input }),
        "Import failed",
      );
      if (res.ok) {
        notify("success", "Organization imported", `${res.value.name}${input.activate ? " is now active." : " was added."}`);
        setSelectedId(res.value.id);
        await refresh();
      }
      return res;
    },
    [refresh],
  );

  const validateText = useCallback(
    (text: string, format: "yaml" | "json"): Promise<ValidateResult> =>
      orgRequest<ValidateResult>(VALIDATE_PATH, { method: "POST", body: { text, format } }),
    [],
  );

  const deleteOrg = useCallback(
    async (meta: OrgMeta): Promise<boolean> => {
      const accepted = await confirmAction({
        title: `Delete "${meta.name}"?`,
        message: "This removes the organization and its history. The built-in organization is not affected.",
        confirmLabel: "Delete",
        tone: "danger",
      });
      if (!accepted) return false;
      const res = await attempt(
        () => orgRequest<{ deleted: string }>(orgPath(meta.id), { method: "DELETE" }),
        "Could not delete the organization",
      );
      if (!res.ok) return false;
      notify("success", "Organization deleted", meta.name);
      const l = await loadList();
      setSelectedId(l?.active_id ?? l?.organizations[0]?.id ?? null);
      setReloadTick((t) => t + 1);
      return true;
    },
    [loadList],
  );

  const restore = useCallback(
    async (meta: OrgMeta, seq: number, version: number): Promise<MutationResult<OrgDetail>> => {
      const accepted = await confirmAction({
        title: `Restore version ${version}?`,
        message: "The current content is kept in history, so the restore can be undone.",
        confirmLabel: "Restore",
      });
      if (!accepted) return { ok: false, lines: [] };
      const res = await attempt(
        () => orgRequest<OrgDetail>(orgPath(meta.id, "restore"), { method: "POST", body: { seq } }),
        "Could not restore that version",
      );
      if (res.ok) {
        notify("success", "Version restored", `${meta.name} is back to version ${version}.`);
        await refresh();
      }
      return res;
    },
    [refresh],
  );

  // ── Editing ────────────────────────────────────────────────────────────────

  /**
   * Structured edit. Editing the built-in organization saves a copy: the
   * response then carries `forked_from` and the copy's own id, which the page
   * switches to. The copy becomes active only if the built-in one was.
   */
  const applyChanges = useCallback(
    async (changes: OrgChanges, note?: string): Promise<MutationResult<OrgChangeResult>> => {
      if (!selectedId) return { ok: false, lines: ["No organization is selected."] };
      const res = await attempt(
        () =>
          orgRequest<OrgChangeResult>(orgPath(selectedId, "changes"), {
            method: "POST",
            body: note ? { changes, note } : { changes },
          }),
        "Change rejected",
      );
      if (!res.ok) return res;
      const out = res.value;
      if (out.forked_from) {
        notify(
          "info",
          "Saved as your own copy",
          `Phantom Lab is built in and read-only, so your change went to "${out.name}". ` +
            (out.active ? "It is now the active organization." : "The active organization is unchanged."),
        );
        setSelectedId(out.id);
      }
      notify("success", "Saved", out.notes.length > 0 ? out.notes.join("\n") : out.name);
      await refresh();
      return res;
    },
    [selectedId, refresh],
  );

  /**
   * Save the YAML editor. An organization of the operator's is replaced in
   * place. The built-in one is read-only, so it is checked first (no copy is
   * left behind by a bad edit), then copied, the edit stored in the copy, and
   * the copy activated.
   */
  const saveYaml = useCallback(
    async (text: string, meta: OrgMeta): Promise<MutationResult<OrgDetail>> => {
      if (!isBuiltIn(meta)) {
        const res = await attempt(
          () =>
            orgRequest<OrgDetail>(orgPath(meta.id), {
              method: "PUT",
              body: { text, format: "yaml", note: "Edited in the YAML editor" },
            }),
          "Save failed",
        );
        if (res.ok) {
          notify("success", "Saved", `${res.value.name} is now at version ${res.value.version}.`);
          await refresh();
        }
        return res;
      }

      let copyId: string | null = null;
      const res = await attempt(async () => {
        const check = await validateText(text, "yaml");
        if (!check.valid) {
          const lines = check.errors.length > 0 ? check.errors : ["The document is not valid."];
          throw new ApiError(lines[0], 400, "invalid", lines);
        }
        const parsed = yaml.load(text, { schema: yaml.JSON_SCHEMA });
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new ApiError("The document must be a YAML mapping.", 400, "invalid", []);
        }
        const copy = await orgRequest<OrgDetail>(orgPath(meta.id, "fork"), { method: "POST", body: {} });
        copyId = copy.id;
        const doc = rewriteForCopy(parsed as Record<string, unknown>, { id: copy.id, name: copy.name }, meta.name);
        await orgRequest<OrgDetail>(orgPath(copy.id), {
          method: "PUT",
          body: { document: doc, note: "Edited in the YAML editor" },
        });
        return orgRequest<OrgDetail>(orgPath(copy.id, "activate"), { method: "POST" });
      }, "Save failed");

      if (!res.ok) {
        // Do not leave an unused copy behind after a failed save.
        if (copyId) {
          try {
            await orgRequest(orgPath(copyId), { method: "DELETE" });
          } catch {
            // The copy is harmless; the operator can delete it from the switcher.
          }
        }
        return res;
      }
      notify("info", "Saved as your own copy", `${res.value.name} holds your edit and is now active.`);
      setSelectedId(res.value.id);
      await refresh();
      return res;
    },
    [refresh, validateText],
  );

  return {
    list,
    listError,
    selectedId,
    data: ready ? data : null,
    loading: selectedId !== null && !ready && loadError === null,
    loadError,
    select,
    refresh,
    activate,
    duplicate,
    importText,
    validateText,
    deleteOrg,
    restore,
    applyChanges,
    saveYaml,
  };
}

export type OrganizationController = ReturnType<typeof useOrganization>;
