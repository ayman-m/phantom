"use client";

/**
 * Dialogs opened from the organization header: Duplicate, Import, History.
 */

import { useEffect, useState } from "react";
import {
  detectFormat,
  errorLines,
  formatTimestamp,
  isBuiltIn,
  orgPath,
  orgRequest,
  type HistoryResponse,
  type HistoryVersion,
  type OrgMeta,
  type ValidateResult,
} from "@/lib/organization-types";
import {
  Button,
  CheckField,
  EmptyState,
  ErrorList,
  Modal,
  SelectField,
  SkeletonBlock,
  TableShell,
  Td,
  TextField,
  Th,
  ROW_CLASS,
  WarningList,
  useDebounced,
} from "./ui";
import type { OrganizationController } from "./use-organization";

// ─── Duplicate ───────────────────────────────────────────────────────────────

export function DuplicateDialog({
  meta,
  ctl,
  onClose,
}: {
  meta: OrgMeta;
  ctl: OrganizationController;
  onClose: () => void;
}) {
  const [name, setName] = useState(`${meta.name} (copy)`);
  const [makeActive, setMakeActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  async function submit() {
    setBusy(true);
    setErrors([]);
    const res = await ctl.duplicate(meta, name, makeActive);
    setBusy(false);
    if (res.ok) onClose();
    else setErrors(res.lines);
  }

  return (
    <Modal
      title="Duplicate organization"
      icon="content_copy"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" icon="content_copy" busy={busy} onClick={() => void submit()}>
            Create copy
          </Button>
        </>
      }
    >
      <p className="text-xs text-on-surface-variant leading-relaxed">
        Makes an editable copy of <strong className="text-on-surface">{meta.name}</strong> with every person, host and
        network. The original is not changed.
      </p>
      <TextField label="Name of the copy" value={name} onChange={setName} />
      <CheckField
        label="Make the copy the active organization"
        hint="Every generator uses the active organization. Switching removes nothing."
        checked={makeActive}
        onChange={setMakeActive}
      />
      <ErrorList lines={errors} />
    </Modal>
  );
}

// ─── Import ──────────────────────────────────────────────────────────────────

type FormatChoice = "auto" | "yaml" | "json";

export function ImportDialog({ ctl, onClose }: { ctl: OrganizationController; onClose: () => void }) {
  const [text, setText] = useState("");
  const [filename, setFilename] = useState("");
  const [choice, setChoice] = useState<FormatChoice>("auto");
  const [activate, setActivate] = useState(false);
  const [replace, setReplace] = useState(false);
  const [check, setCheck] = useState<ValidateResult | null>(null);
  const [checkError, setCheckError] = useState<string[]>([]);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [existsConflict, setExistsConflict] = useState(false);

  const format = choice === "auto" ? detectFormat(text, filename) : choice;
  const debouncedText = useDebounced(text, 500);
  const validateText = ctl.validateText;

  // Validate as the operator types or loads a file, so errors show before importing.
  useEffect(() => {
    let cancelled = false;
    if (!debouncedText.trim()) {
      setCheck(null);
      setCheckError([]);
      setChecking(false);
      return;
    }
    setChecking(true);
    void (async () => {
      try {
        const fmt = choice === "auto" ? detectFormat(debouncedText, filename) : choice;
        const res = await validateText(debouncedText, fmt);
        if (cancelled) return;
        setCheck(res);
        setCheckError([]);
      } catch (err) {
        if (cancelled) return;
        setCheck(null);
        setCheckError(errorLines(err));
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedText, choice, filename, validateText]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      setText(await file.text());
      setFilename(file.name);
      setErrors([]);
    } catch (err) {
      setErrors(errorLines(err));
    }
  }

  async function submit() {
    setBusy(true);
    setErrors([]);
    setExistsConflict(false);
    const res = await ctl.importText({ text, format, activate, replace });
    setBusy(false);
    if (res.ok) {
      onClose();
      return;
    }
    setErrors(res.lines);
    // The server's refusal for an id that is taken carries code "exists".
    setExistsConflict(res.lines.some((l) => /already exists|bundled organization/i.test(l)));
  }

  const waiting = text !== debouncedText || checking;
  const canImport = text.trim().length > 0 && !waiting && check !== null && check.valid;

  return (
    <Modal
      title="Import organization"
      icon="upload_file"
      wide
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" icon="upload" busy={busy} disabled={!canImport} onClick={() => void submit()}>
            Import
          </Button>
        </>
      }
    >
      <p className="text-xs text-on-surface-variant leading-relaxed">
        Paste a YAML or JSON organization, or choose a file. It is checked as you go; nothing is stored until you click
        Import, and the active organization stays as it is unless you choose otherwise.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="org-import-file" className="text-xs font-label text-on-surface-variant/80 block">
            Choose a file
          </label>
          <input
            id="org-import-file"
            type="file"
            accept=".yaml,.yml,.json,application/json,text/yaml,text/plain"
            onChange={(e) => void onFile(e.target.files?.[0])}
            className="text-xs text-on-surface-variant file:mr-3 file:rounded-lg file:border-0 file:bg-primary/15 file:text-primary file:px-3 file:py-1.5 file:text-xs file:font-medium"
          />
        </div>
        <div className="w-40">
          <SelectField
            label="Format"
            value={choice}
            onChange={(v) => setChoice(v as FormatChoice)}
            options={[
              { value: "auto", label: `Detect (${format.toUpperCase()})` },
              { value: "yaml", label: "YAML" },
              { value: "json", label: "JSON" },
            ]}
          />
        </div>
      </div>

      <div className="space-y-1">
        <label htmlFor="org-import-text" className="text-xs font-label text-on-surface-variant/80">
          Organization document
        </label>
        <textarea
          id="org-import-text"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setErrors([]);
          }}
          placeholder={"schema_version: 1\nid: my-company\nname: My Company\n…"}
          spellCheck={false}
          className="w-full h-56 rounded-xl px-4 py-3 text-xs font-mono text-on-surface leading-relaxed outline-none resize-y custom-scrollbar bg-surface-container-low border border-outline-variant/30 focus:border-primary/50"
        />
      </div>

      {waiting ? (
        <p className="text-xs text-on-surface-variant/70" role="status">
          Checking…
        </p>
      ) : null}
      {!waiting && check?.valid ? (
        <p className="text-xs text-secondary flex items-center gap-1.5" role="status">
          <span className="material-symbols-outlined text-base" aria-hidden="true">
            check_circle
          </span>
          Valid. Ready to import.
        </p>
      ) : null}
      {!waiting && check && !check.valid ? <ErrorList lines={check.errors} title="Fix these before importing" /> : null}
      {!waiting ? <ErrorList lines={checkError} title="Could not check the document" /> : null}
      {!waiting && check?.valid ? <WarningList lines={check.warnings} title="Worth a look" /> : null}

      <div className="space-y-2">
        <CheckField
          label="Make it the active organization after import"
          hint="Every generator uses the active organization. Switching removes nothing."
          checked={activate}
          onChange={setActivate}
        />
        <CheckField
          label="Replace one of mine that has the same id"
          hint="Only your own organizations can be replaced. The previous content stays in its history."
          checked={replace}
          onChange={setReplace}
        />
      </div>

      <ErrorList lines={errors} title="Import failed" />
      {existsConflict ? (
        <p className="text-xs text-on-surface-variant">
          Change the <code className="font-mono">id</code> line in the document, or tick &ldquo;Replace one of mine&rdquo;
          if it is your own organization.
        </p>
      ) : null}
    </Modal>
  );
}

// ─── History ─────────────────────────────────────────────────────────────────

export function HistoryDialog({
  meta,
  ctl,
  onClose,
}: {
  meta: OrgMeta;
  ctl: OrganizationController;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<HistoryVersion[] | null>(null);
  const [error, setError] = useState<string[]>([]);
  const [busySeq, setBusySeq] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const builtIn = isBuiltIn(meta);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await orgRequest<HistoryResponse>(orgPath(meta.id, "history", { limit: 50 }));
        if (!cancelled) {
          setVersions(res.versions);
          setError([]);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorLines(err));
          setVersions([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meta.id, meta.version, tick]);

  async function restore(v: HistoryVersion) {
    setBusySeq(v.seq);
    const res = await ctl.restore(meta, v.seq, v.version);
    setBusySeq(null);
    if (res.ok) setTick((t) => t + 1);
  }

  return (
    <Modal title={`History of ${meta.name}`} icon="history" wide onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <p className="text-xs text-on-surface-variant leading-relaxed">
        Every save keeps the previous content. Restoring one puts it back as a new version, so a restore can be undone
        too. Current version: <strong className="text-on-surface">{meta.version}</strong>.
      </p>
      {builtIn ? (
        <p className="text-xs text-on-surface-variant/80">
          The built-in organization is read-only, so it has nothing to restore. Duplicate it to start an editable history.
        </p>
      ) : null}
      <ErrorList lines={error} />
      {versions === null ? (
        <SkeletonBlock className="h-32" />
      ) : versions.length === 0 ? (
        <EmptyState icon="history" title="No earlier versions">
          Saved edits will appear here.
        </EmptyState>
      ) : (
        <TableShell caption="Earlier versions">
          <thead>
            <tr>
              <Th>Version</Th>
              <Th>Saved</Th>
              <Th>By</Th>
              <Th>Change</Th>
              <Th>
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.seq} className={ROW_CLASS}>
                <Td mono>{v.version}</Td>
                <Td className="whitespace-nowrap">{formatTimestamp(v.updated_at)}</Td>
                <Td>{v.updated_by ?? "—"}</Td>
                <Td className="max-w-[320px] truncate" >
                  <span title={v.note ?? undefined}>{v.note ?? "—"}</span>
                </Td>
                <Td className="text-right">
                  <Button
                    icon="restore"
                    busy={busySeq === v.seq}
                    disabled={builtIn || busySeq !== null}
                    title={builtIn ? "The built-in organization cannot be restored" : `Restore version ${v.version}`}
                    onClick={() => void restore(v)}
                  >
                    Restore
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
    </Modal>
  );
}
