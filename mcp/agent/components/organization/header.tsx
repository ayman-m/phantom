"use client";

/**
 * Page header: the organization switcher, the selected organization's name,
 * badges and counts, and its actions (activate, duplicate, import, export,
 * history, delete).
 */

import { useState } from "react";
import { notify } from "@/lib/stores/notifications";
import {
  errorSummary,
  exportFilename,
  isBuiltIn,
  orgPath,
  orgRequest,
  type ExportResponse,
  type OrgMeta,
} from "@/lib/organization-types";
import { cn } from "@/lib/utils";
import { DuplicateDialog, HistoryDialog, ImportDialog } from "./dialogs";
import { Banner, Button, Chip, Panel } from "./ui";
import type { OrgData, OrganizationController } from "./use-organization";

export function SourceBadge({ meta }: { meta: OrgMeta }) {
  return isBuiltIn(meta) ? <Chip tone="neutral">Built-in</Chip> : <Chip tone="primary">Yours</Chip>;
}

export function OrganizationHeader({
  ctl,
  selected,
  data,
}: {
  ctl: OrganizationController;
  selected: OrgMeta | null;
  data: OrgData | null;
}) {
  const [dialog, setDialog] = useState<"import" | "duplicate" | "history" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const organizations = ctl.list?.organizations ?? [];

  async function download(meta: OrgMeta, format: "yaml" | "json") {
    setBusy(`export-${format}`);
    try {
      const res = await orgRequest<ExportResponse>(orgPath(meta.id, "export", { format }));
      const blob = new Blob([res.text], {
        type: format === "json" ? "application/json" : "application/yaml",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = exportFilename(meta.id, format);
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      notify("success", "Exported", `${meta.name} saved as ${exportFilename(meta.id, format)}.`);
    } catch (err) {
      notify("error", "Export failed", errorSummary(err));
    } finally {
      setBusy(null);
    }
  }

  async function activate(meta: OrgMeta) {
    setBusy("activate");
    await ctl.activate(meta);
    setBusy(null);
  }

  async function remove(meta: OrgMeta) {
    setBusy("delete");
    await ctl.deleteOrg(meta);
    setBusy(null);
  }

  const builtIn = selected ? isBuiltIn(selected) : false;
  const networkCount = data ? data.detail.document.networks.length : null;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="material-symbols-outlined text-2xl text-primary" aria-hidden="true">
              apartment
            </span>
            <h1 className="font-headline text-3xl font-bold tracking-tight text-on-surface">Organization</h1>
          </div>
          <p className="text-sm text-on-surface-variant ml-9 max-w-3xl">
            The one fictitious company every log generator uses, so events from Okta, Windows, firewalls and cloud
            tell a single story in Cortex.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button icon="refresh" onClick={() => void ctl.refresh()}>
            Refresh
          </Button>
          <Button tone="primary" icon="upload_file" onClick={() => setDialog("import")}>
            Import
          </Button>
        </div>
      </div>

      {/* Switcher: choosing one only changes what is on screen. */}
      <Panel title="Organizations" icon="swap_horiz">
        {organizations.length === 0 ? (
          <p className="text-xs text-on-surface-variant">No organizations yet. Import one to get started.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3" role="group" aria-label="Organizations">
            {organizations.map((o) => {
              const isSelected = o.id === selected?.id;
              return (
                <button
                  key={o.id}
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => ctl.select(o.id)}
                  className={cn(
                    "text-left rounded-xl px-4 py-3 border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                    isSelected
                      ? "border-primary/50 bg-primary/10"
                      : "border-outline-variant/30 bg-surface-container-low hover:bg-surface-container",
                  )}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-on-surface truncate">{o.name}</span>
                    <SourceBadge meta={o} />
                    {o.active ? <Chip tone="success">Active</Chip> : null}
                  </div>
                  <div className="text-[11px] text-on-surface-variant/70 font-mono mt-1">
                    {o.people} people · {o.hosts} hosts · {o.domain}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </Panel>

      {selected ? (
        <Panel>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="min-w-0 space-y-2">
              <div className="flex items-center gap-2.5 flex-wrap">
                <h2 className="font-headline text-xl font-bold text-on-surface">{selected.name}</h2>
                <SourceBadge meta={selected} />
                {selected.active ? <Chip tone="success">Active</Chip> : null}
                <Chip tone="neutral" title="Version">
                  v{selected.version}
                </Chip>
              </div>
              <div className="flex items-center gap-4 flex-wrap text-xs text-on-surface-variant">
                <span>
                  <strong className="text-on-surface font-mono">{selected.people}</strong> people
                </span>
                <span>
                  <strong className="text-on-surface font-mono">{selected.hosts}</strong> hosts
                </span>
                <span>
                  <strong className="text-on-surface font-mono">{networkCount ?? "—"}</strong> networks
                </span>
                <span className="font-mono text-on-surface-variant/70">{selected.domain}</span>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {!selected.active ? (
                <Button
                  tone="primary"
                  icon="bolt"
                  busy={busy === "activate"}
                  onClick={() => void activate(selected)}
                  title="Every generator will use this organization. Switching removes nothing."
                >
                  Make active
                </Button>
              ) : null}
              <Button icon="content_copy" onClick={() => setDialog("duplicate")}>
                Duplicate
              </Button>
              <Button icon="download" busy={busy === "export-yaml"} onClick={() => void download(selected, "yaml")}>
                Export YAML
              </Button>
              <Button icon="data_object" busy={busy === "export-json"} onClick={() => void download(selected, "json")}>
                Export JSON
              </Button>
              <Button icon="history" onClick={() => setDialog("history")}>
                History
              </Button>
              <Button
                tone="danger"
                icon="delete"
                busy={busy === "delete"}
                disabled={builtIn || selected.active}
                title={
                  builtIn
                    ? "The built-in organization cannot be deleted"
                    : selected.active
                      ? "Make another organization active first"
                      : "Delete this organization"
                }
                onClick={() => void remove(selected)}
              >
                Delete
              </Button>
            </div>
          </div>
          {!selected.active ? (
            <p className="text-[11px] text-on-surface-variant/70">
              Generators currently use the active organization. Make this one active to switch; switching removes
              nothing.
            </p>
          ) : null}
        </Panel>
      ) : null}

      {builtIn ? (
        <Banner tone="info" icon="lock">
          {selected?.name} is built in and read-only. Any edit saves your own copy.
        </Banner>
      ) : null}

      {dialog === "import" ? <ImportDialog ctl={ctl} onClose={() => setDialog(null)} /> : null}
      {dialog === "duplicate" && selected ? (
        <DuplicateDialog meta={selected} ctl={ctl} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === "history" && selected ? (
        <HistoryDialog meta={selected} ctl={ctl} onClose={() => setDialog(null)} />
      ) : null}
    </div>
  );
}
