/**
 * FormEngine — renders a ConfigParam-style fields[] schema into a
 * dynamic form. Shared by the /connectors page so the
 * /log-destinations page can reuse the same widget vocabulary.
 *
 * Supports the standard widget set (text/url/string/number/secret/
 * password/textarea/select/radio/multi_select/boolean/array/json)
 * PLUS the new `visible_when` clause:
 *
 *   visible_when: { field: "auth_type", value: "bearer" }
 *
 * The renderer skips a field when its `visible_when.field` doesn't
 * match. Hidden fields don't validate required and aren't included in
 * the submit. Switching the discriminator value re-renders the form
 * (and the previously-entered values for the now-hidden branch stay
 * in formValues but won't submit) — operator-friendly behaviour for
 * accidental clicks.
 */

"use client";

import { useCallback, useMemo, useState } from "react";

// ── Field type definitions (matches the manifest's FieldDef) ────

export type FormFieldType =
  | "text"
  | "url"
  | "string"
  | "number"
  | "password"
  | "secret"
  | "textarea"
  | "select"
  | "radio"
  | "multi_select"
  | "boolean"
  | "array"
  | "json";

export interface FormFieldDef {
  name: string;
  display: string;
  type: FormFieldType;
  required?: boolean;
  defaultValue?: string | null;
  description?: string;
  options?: string[];
  visible_when?: { field: string; value: string | string[] };
}

export interface FormEngineProps {
  fields: FormFieldDef[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  // When true, a "***" secret field renders as a placeholder hint instead
  // of empty; useful in the edit dialog where the secret is persisted but
  // not displayed.
  secretRedactSentinel?: boolean;
  // Optional: per-field validation errors map.
  errors?: Record<string, string>;
  // Read-only mode (e.g. preview tab on /log-destinations row expansion).
  readOnly?: boolean;
}

// ── visible_when evaluator ──────────────────────────────────────

export function isFieldVisible(
  field: FormFieldDef,
  values: Record<string, string>,
): boolean {
  if (!field.visible_when) return true;
  const current = values[field.visible_when.field];
  if (current === undefined) return false;
  const allowed = field.visible_when.value;
  if (Array.isArray(allowed)) return allowed.includes(current);
  return current === allowed;
}

/**
 * Project visible-only values from a full form state. Use this before
 * submitting — hidden fields' stale values won't reach the server.
 */
export function projectVisibleValues(
  fields: FormFieldDef[],
  values: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of fields) {
    if (!isFieldVisible(f, values)) continue;
    const v = values[f.name];
    if (v === undefined || v === "") continue;
    out[f.name] = v;
  }
  return out;
}

/**
 * Returns the list of required fields that are visible but empty.
 * Form is submittable when this returns [].
 */
export function findMissingRequired(
  fields: FormFieldDef[],
  values: Record<string, string>,
): string[] {
  const missing: string[] = [];
  for (const f of fields) {
    if (!f.required) continue;
    if (!isFieldVisible(f, values)) continue;
    const v = (values[f.name] ?? f.defaultValue ?? "").toString().trim();
    if (!v) missing.push(f.name);
  }
  return missing;
}

// ── The renderer ────────────────────────────────────────────────

export function FormEngine({
  fields,
  values,
  onChange,
  secretRedactSentinel = false,
  errors,
  readOnly = false,
}: FormEngineProps) {
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});

  const visibleFields = useMemo(
    () => fields.filter((f) => isFieldVisible(f, values)),
    [fields, values],
  );

  const toggleSecret = useCallback((name: string) => {
    setShowSecret((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  return (
    <div className="grid gap-6">
      {visibleFields.map((field) => (
        <FieldRow
          key={field.name}
          field={field}
          value={values[field.name] ?? field.defaultValue ?? ""}
          onChange={(v) => onChange(field.name, v)}
          showSecret={showSecret[field.name] ?? false}
          onToggleSecret={() => toggleSecret(field.name)}
          secretRedactSentinel={secretRedactSentinel}
          error={errors?.[field.name]}
          readOnly={readOnly}
        />
      ))}
    </div>
  );
}

// ── Per-field rendering ────────────────────────────────────────

interface FieldRowProps {
  field: FormFieldDef;
  value: string;
  onChange: (v: string) => void;
  showSecret: boolean;
  onToggleSecret: () => void;
  secretRedactSentinel: boolean;
  error?: string;
  readOnly: boolean;
}

function FieldRow({
  field,
  value,
  onChange,
  showSecret,
  onToggleSecret,
  secretRedactSentinel,
  error,
  readOnly,
}: FieldRowProps) {
  const labelEl = (
    <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
      {field.display}
      {field.required && <span className="text-error ml-1">*</span>}
    </label>
  );

  const hint = field.description ? (
    <p className="text-[11px] text-on-surface-variant/70 italic ml-1 leading-relaxed">
      {field.description}
    </p>
  ) : null;

  const errorEl = error ? (
    <p className="text-[10px] text-error italic ml-1">{error}</p>
  ) : null;

  // Boolean fields have their own card-style label inline; no separate label.
  if (field.type === "boolean") {
    const isOn = value === "true" || value === "1";
    return (
      <div className="space-y-2">
        <button
          type="button"
          disabled={readOnly}
          onClick={() => onChange(isOn ? "false" : "true")}
          className="w-full flex items-center justify-between p-4 rounded-xl text-left transition-colors hover:bg-surface-container-highest disabled:opacity-50"
          style={{
            background: "var(--m3-surface-container)",
            border: "0.5px solid var(--glass-border)",
          }}
        >
          <div className="flex flex-col gap-0.5">
            <span className="text-sm text-on-surface">{field.display}</span>
            {field.description && (
              <span className="text-[11px] text-on-surface-variant/60">
                {field.description}
              </span>
            )}
          </div>
          <div
            className="w-11 h-6 rounded-full relative p-1 transition-colors shrink-0"
            style={{
              background: isOn
                ? "rgba(3, 115, 33, 0.3)"
                : "var(--glass-border)",
            }}
          >
            <div
              className="w-4 h-4 rounded-full transition-all"
              style={{
                background: isOn ? "white" : "rgba(140, 145, 157, 0.4)",
                transform: isOn ? "translateX(20px)" : "translateX(0)",
              }}
            />
          </div>
        </button>
        {errorEl}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {labelEl}
      <FieldInput
        field={field}
        value={value}
        onChange={onChange}
        showSecret={showSecret}
        onToggleSecret={onToggleSecret}
        secretRedactSentinel={secretRedactSentinel}
        readOnly={readOnly}
      />
      {hint}
      {errorEl}
    </div>
  );
}

function FieldInput({
  field,
  value,
  onChange,
  showSecret,
  onToggleSecret,
  secretRedactSentinel,
  readOnly,
}: Omit<FieldRowProps, "error">) {
  const commonInputClass =
    "w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline disabled:opacity-50";
  const commonStyle = { border: "0.5px solid var(--glass-border)" };

  switch (field.type) {
    case "text":
    case "string":
    case "url":
    case "number":
      return (
        <input
          type="text"
          value={value}
          disabled={readOnly}
          inputMode={
            field.type === "url"
              ? "url"
              : field.type === "number"
                ? "numeric"
                : undefined
          }
          onChange={(e) => onChange(e.target.value)}
          className={commonInputClass}
          style={commonStyle}
          placeholder={field.defaultValue ?? `Enter ${field.display.toLowerCase()}`}
        />
      );

    case "secret":
    case "password": {
      const placeholderForRedacted =
        secretRedactSentinel && (value === "***" || value === "")
          ? "(unchanged — type a new value to rotate)"
          : `Enter ${field.display.toLowerCase()}`;
      return (
        <div className="relative">
          <input
            type={showSecret ? "text" : "password"}
            value={value === "***" && !showSecret ? "" : value}
            disabled={readOnly}
            onChange={(e) => onChange(e.target.value)}
            className={`${commonInputClass} pr-12`}
            style={commonStyle}
            placeholder={placeholderForRedacted}
            autoComplete="new-password"
          />
          {!readOnly && (
            <button
              type="button"
              onClick={onToggleSecret}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white/5 transition-colors"
              aria-label={showSecret ? "Hide" : "Show"}
            >
              <span className="material-symbols-outlined text-base">
                {showSecret ? "visibility_off" : "visibility"}
              </span>
            </button>
          )}
        </div>
      );
    }

    case "textarea":
      return (
        <textarea
          value={value}
          disabled={readOnly}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          className={`${commonInputClass} resize-y min-h-[96px] font-mono text-xs`}
          style={commonStyle}
          placeholder={field.defaultValue ?? ""}
        />
      );

    case "select":
      return (
        <select
          value={value}
          disabled={readOnly}
          onChange={(e) => onChange(e.target.value)}
          className={`${commonInputClass} appearance-none pr-10`}
          style={{
            ...commonStyle,
            backgroundImage:
              "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='%238c919d' d='M6 9L2 5h8z'/></svg>\")",
            backgroundRepeat: "no-repeat",
            backgroundPosition: "right 1rem center",
          }}
        >
          {!field.required && <option value="">— none —</option>}
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      );

    case "radio":
      return (
        <div className="flex flex-wrap gap-2">
          {(field.options ?? []).map((opt) => {
            const isOn = value === opt;
            return (
              <button
                key={opt}
                type="button"
                disabled={readOnly}
                onClick={() => onChange(opt)}
                className={`px-3 py-2 rounded-full text-xs transition-all disabled:opacity-50 ${
                  isOn
                    ? "bg-primary/15 text-primary"
                    : "bg-surface-container-highest text-on-surface-variant hover:bg-surface-variant/50"
                }`}
                style={{
                  border: isOn
                    ? "0.5px solid rgba(167, 200, 255, 0.4)"
                    : "0.5px solid var(--glass-border)",
                }}
              >
                {opt}
              </button>
            );
          })}
        </div>
      );

    case "multi_select": {
      let selected: string[] = [];
      try {
        const parsed = JSON.parse(value || "[]");
        if (Array.isArray(parsed)) selected = parsed.map(String);
      } catch {
        selected = [];
      }
      const toggle = (opt: string) => {
        const next = selected.includes(opt)
          ? selected.filter((s) => s !== opt)
          : [...selected, opt];
        onChange(JSON.stringify(next));
      };
      return (
        <div className="flex flex-wrap gap-2">
          {(field.options ?? []).map((opt) => {
            const isOn = selected.includes(opt);
            return (
              <button
                key={opt}
                type="button"
                disabled={readOnly}
                onClick={() => toggle(opt)}
                className={`px-3 py-2 rounded-full text-xs transition-all disabled:opacity-50 ${
                  isOn
                    ? "bg-primary/15 text-primary"
                    : "bg-surface-container-highest text-on-surface-variant hover:bg-surface-variant/50"
                }`}
                style={{
                  border: isOn
                    ? "0.5px solid rgba(167, 200, 255, 0.4)"
                    : "0.5px solid var(--glass-border)",
                }}
              >
                {isOn && (
                  <span className="material-symbols-outlined text-xs mr-1 align-middle">
                    check
                  </span>
                )}
                {opt}
              </button>
            );
          })}
        </div>
      );
    }

    case "array":
    case "json":
      // Both render as a textarea for now; future work could extract
      // a ChipListField like /connectors has.
      return (
        <textarea
          value={value}
          disabled={readOnly}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          className={`${commonInputClass} resize-y min-h-[72px] font-mono text-xs`}
          style={commonStyle}
          placeholder={
            field.type === "json"
              ? '{"key": "value"}'
              : '["item1", "item2"]'
          }
        />
      );

    default: {
      const unknown = field.type as string;
      return (
        <>
          <input
            type="text"
            value={value}
            disabled={readOnly}
            onChange={(e) => onChange(e.target.value)}
            className={commonInputClass}
            style={commonStyle}
          />
          <p className="text-[10px] text-error italic mt-1">
            unknown widget type &quot;{unknown}&quot; — rendered as text
          </p>
        </>
      );
    }
  }
}
