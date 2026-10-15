"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorLines,
  orgPath,
  orgRequest,
  type ExportResponse,
  type ValidateResult,
} from "@/lib/organization-types";
import {
  Banner,
  Button,
  CopyButton,
  ErrorList,
  Panel,
  SkeletonBlock,
  WarningList,
  useDebounced,
} from "./ui";
import type { OrgData, OrganizationController } from "./use-organization";

/**
 * Whole-document editor. The text starts from the server's YAML export and is
 * checked against the server as you type. Saving an organization of the
 * operator's replaces it in place; saving the built-in one stores the edit as
 * a new copy and makes it active.
 *
 * Mounted with `key={organization id}`, so switching organizations starts a
 * fresh editor. When the same organization changes underneath unsaved edits,
 * the edits are kept and a banner offers to reload.
 */
export function YamlTab({ data, ctl, builtIn }: { data: OrgData; ctl: OrganizationController; builtIn: boolean }) {
  const meta = data.detail;
  const [text, setText] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [loadError, setLoadError] = useState<string[]>([]);
  const [result, setResult] = useState<ValidateResult | null>(null);
  const [checkError, setCheckError] = useState<string[]>([]);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErrors, setSaveErrors] = useState<string[]>([]);
  const [reloadTick, setReloadTick] = useState(0);

  const textRef = useRef<string | null>(null);
  const baselineRef = useRef<string | null>(null);
  const remoteRef = useRef<string | null>(null);

  const edit = useCallback((next: string) => {
    textRef.current = next;
    setText(next);
  }, []);

  const adopt = useCallback((remote: string) => {
    textRef.current = remote;
    baselineRef.current = remote;
    remoteRef.current = null;
    setText(remote);
    setBaseline(remote);
    setStale(false);
  }, []);

  // Load the export on mount and whenever the stored version moves.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await orgRequest<ExportResponse>(orgPath(meta.id, "export", { format: "yaml" }));
        if (cancelled) return;
        setLoadError([]);
        const untouched = textRef.current === null || textRef.current === baselineRef.current;
        if (untouched) adopt(res.text);
        else if (res.text !== baselineRef.current) {
          remoteRef.current = res.text;
          setStale(true);
        }
      } catch (err) {
        if (!cancelled) setLoadError(errorLines(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meta.id, meta.version, reloadTick, adopt]);

  const validateText = ctl.validateText;
  const runValidate = useCallback(
    async (value: string, isCurrent: () => boolean) => {
      setValidating(true);
      try {
        const res = await validateText(value, "yaml");
        if (!isCurrent()) return;
        setResult(res);
        setCheckError([]);
      } catch (err) {
        if (!isCurrent()) return;
        setResult(null);
        setCheckError(errorLines(err));
      } finally {
        if (isCurrent()) setValidating(false);
      }
    },
    [validateText],
  );

  // Validate on a debounce, so typing does not send one call per keystroke.
  const debounced = useDebounced(text, 600);
  useEffect(() => {
    if (debounced === null || !debounced.trim()) {
      setResult(null);
      setValidating(false);
      return;
    }
    let live = true;
    void runValidate(debounced, () => live);
    return () => {
      live = false;
    };
  }, [debounced, runValidate]);

  const dirty = text !== null && text !== baseline;
  const settled = text === debounced && !validating;
  const canSave = dirty && settled && result !== null && result.valid && !saving;

  async function save() {
    if (text === null) return;
    setSaving(true);
    setSaveErrors([]);
    const saved = text;
    const res = await ctl.saveYaml(saved, meta);
    setSaving(false);
    if (res.ok) {
      // The reload that follows adopts the server's normalized YAML.
      baselineRef.current = saved;
    } else if (res.lines.length > 0) {
      setSaveErrors(res.lines);
    }
  }

  function revert() {
    const target = stale && remoteRef.current !== null ? remoteRef.current : baseline;
    if (target !== null) adopt(target);
    setSaveErrors([]);
  }

  if (text === null) {
    return loadError.length > 0 ? (
      <div className="space-y-3">
        <ErrorList lines={loadError} title="Could not load the document" />
        <Button tone="primary" icon="refresh" onClick={() => setReloadTick((t) => t + 1)}>
          Retry
        </Button>
      </div>
    ) : (
      <SkeletonBlock className="h-[480px]" />
    );
  }

  const lineCount = text.split("\n").length;

  return (
    <div className="space-y-4">
      {stale ? (
        <Banner tone="warning" icon="sync_problem">
          This organization changed after you opened the editor. Your edits are kept; use Revert to load the latest
          version instead.
        </Banner>
      ) : null}

      <Panel
        title="Document"
        icon="code"
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-on-surface-variant/50 font-mono uppercase tracking-wider">
              YAML · {lineCount} lines{dirty ? " · edited" : ""}
            </span>
            <CopyButton text={text} label="Copy the document" />
          </div>
        }
      >
        {builtIn ? (
          <p className="text-xs text-on-surface-variant leading-relaxed">
            {meta.name} is built in and read-only. Saving stores your edit as a new copy and makes it active.
          </p>
        ) : null}

        <div className="space-y-1">
          <label htmlFor="org-yaml-editor" className="sr-only">
            Organization document (YAML)
          </label>
          <textarea
            id="org-yaml-editor"
            value={text}
            onChange={(e) => {
              edit(e.target.value);
              setSaveErrors([]);
            }}
            spellCheck={false}
            className="w-full h-[560px] rounded-xl px-4 py-3 text-xs font-mono text-on-surface leading-relaxed outline-none resize-y custom-scrollbar bg-surface-container-low border border-outline-variant/30 focus:border-primary/50"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            icon="task_alt"
            busy={validating}
            onClick={() => {
              let live = true;
              void runValidate(text, () => live).finally(() => {
                live = false;
              });
            }}
          >
            Validate
          </Button>
          <Button tone="primary" icon="save" busy={saving} disabled={!canSave} onClick={() => void save()}>
            {builtIn ? "Save as my copy" : "Save"}
          </Button>
          <Button icon="undo" disabled={!dirty && !stale} onClick={revert}>
            Revert
          </Button>
          <span className="text-xs text-on-surface-variant/70" role="status">
            {validating || text !== debounced
              ? "Checking…"
              : result?.valid
                ? dirty
                  ? "Valid. Ready to save."
                  : "Valid."
                : ""}
          </span>
        </div>

        {result && !result.valid ? <ErrorList lines={result.errors} title="Fix these before saving" /> : null}
        <ErrorList lines={checkError} title="Could not check the document" />
        {result?.valid ? <WarningList lines={result.warnings} title="Worth a look" /> : null}
        <ErrorList lines={saveErrors} title="Save failed" />
      </Panel>
    </div>
  );
}
