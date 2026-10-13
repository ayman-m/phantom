"use client";

/**
 * The fields of a connector instance form. /connectors uses it for Create and
 * for Edit, so the two show the same fields in the same widgets. Which fields
 * show, and what counts as filled in, comes from lib/connector-form.ts.
 */

import { useState } from "react";
import { MASK, invalidNumbers, isSecretType, valueOf, visibleParams } from "@/lib/connector-form";

const SECRET_PLACEHOLDER = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022";

export interface ConfigParam {
  display: string;
  name: string;
  // Supports "array" for list-of-string fields like the
  // web connector's allowed_domains. Renders as a chip-list editor
  // (one chip per entry, add/remove buttons) — much friendlier than
  // a raw JSON-array <input>. The form's value for an array field is
  // a JSON-stringified array (matches the existing string-only
  // `configValues: Record<string, string>` shape so we don't have to
  // refactor every consumer).
  //
  // Widget taxonomy. Every field type must be in this union AND handled
  // by renderConfigField; a type missing from the switch would fall
  // through and return undefined, rendering a label with no input. The
  // full widget vocabulary, codified here AND in renderConfigField:
  //
  //   text     → short text input (default for unknown types too)
  //   url      → text input + inputMode="url" hint
  //   string   → text input (alias for "text"; legacy synthetic-card
  //              types kept working by treating them as plain text)
  //   number   → text input + inputMode="numeric" hint
  //   password → masked input with eye toggle (synonym of "secret")
  //   secret   → masked input with eye toggle (existing — kept for
  //              backwards-compat with persisted call sites)
  //   textarea → multiline <textarea> for long strings (e.g. JSON
  //              service-account blobs, PEM certs)
  //   select   → single-select <select> when options[] is present
  //   radio    → radio button group for 2-3 options
  //   multi_select → chip-list with dropdown selector for array fields
  //                  with an enum of allowed options
  //   boolean  → toggle switch
  //   array    → free-form chip-list editor (no enum)
  //
  // Adding a new variant? Update this union AND the renderConfigField
  // switch in the same change. Silent drift between the two is the
  // bug this rule prevents; keep both edits in the same diff.
  type:
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
    | "array";
  required: boolean;
  defaultValue?: string;
  options?: string[];
  /** Per-field help text rendered under the input. The
   *  setup-screen pulls description from the configSchema; the
   *  connectors-page InstanceModal didn't surface it before this
   *  change. Optional so existing fields without docs stay clean. */
  description?: string;
  /** Words shown for each option value. A radio or select shows the value itself when absent. */
  optionLabels?: Record<string, string>;
  /** Show this field only while the value of `field` is one of `in`. Hidden fields are never required (lib/connector-form.ts). */
  showWhen?: { field: string; in: string[] };
  /** When hidden, Edit sends this field empty because it would keep a hidden mode's routing alive. */
  clearWhenHidden?: boolean;
}

// Chip-list editor for `type: "array"` config fields.
// The form's value model is `Record<string, string>` (everything
// serialized for the eventual JSON.stringify when POSTing the
// instance), so this component reads/writes a JSON-stringified
// array. Empty string and unparseable JSON both decode to []. Add
// via Enter on the input or the + button; remove via × on each
// chip. Comma-separated paste is split into multiple chips.
function ChipListField({
  param,
  value,
  onChange,
}: {
  param: ConfigParam;
  value: string;
  onChange: (name: string, value: string) => void;
}) {
  let parsed: string[] = [];
  try {
    const decoded = value ? JSON.parse(value) : [];
    if (Array.isArray(decoded)) {
      parsed = decoded.filter((v): v is string => typeof v === "string");
    }
  } catch {
    parsed = [];
  }
  const [draft, setDraft] = useState("");
  const commitDraft = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    // Comma-separated paste expands into multiple chips. Whitespace
    // around each entry is trimmed; empty entries dropped.
    const additions = trimmed
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !parsed.includes(s));
    if (additions.length === 0) {
      setDraft("");
      return;
    }
    onChange(param.name, JSON.stringify([...parsed, ...additions]));
    setDraft("");
  };
  const removeAt = (idx: number) => {
    const next = parsed.filter((_, i) => i !== idx);
    onChange(param.name, JSON.stringify(next));
  };

  return (
    <div className="space-y-2">
      {/* Existing chips. Empty list shows nothing — the input below
          is enough affordance. */}
      {parsed.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {parsed.map((entry, idx) => (
            <span
              key={`${entry}-${idx}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-primary/15 text-primary border border-primary/25"
            >
              <span className="font-mono">{entry}</span>
              <button
                type="button"
                onClick={() => removeAt(idx)}
                className="hover:bg-primary/20 rounded-full p-0.5 transition-colors"
                aria-label={`Remove ${entry}`}
              >
                <span className="material-symbols-outlined text-[14px]">
                  close
                </span>
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
            }
          }}
          onBlur={commitDraft}
          placeholder={
            param.defaultValue ||
            `e.g., intel.example.com, .vendor.example (comma-separated for many)`
          }
          className="flex-1 bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
          style={{ border: "0.5px solid var(--glass-border)" }}
        />
        <button
          type="button"
          onClick={commitDraft}
          disabled={!draft.trim()}
          className="px-4 py-3 rounded-xl bg-primary/10 hover:bg-primary/20 text-primary text-xs uppercase tracking-widest font-label disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Add
        </button>
      </div>
      {param.description && (
        <p className="text-[11px] text-on-surface-variant px-1 leading-relaxed">
          {param.description}
        </p>
      )}
    </div>
  );
}

export function ConfigFieldInput({
  param,
  value,
  onChange,
  secretSet = false,
  showSecret = false,
  onToggleSecret,
}: {
  param: ConfigParam;
  /** The current value (the default already applied by the caller). */
  value: string;
  onChange: (name: string, value: string) => void;
  /** The server already holds a value for this secret slot. */
  secretSet?: boolean;
  showSecret?: boolean;
  onToggleSecret?: () => void;
}) {

  // Widget vocabulary — every case in
  // the ConfigParam.type union must be handled here, or the field
  // would render as a label-only ghost because the function
  // implicitly returns undefined. The default branch below catches any
  // drift between the union and the renderer.
  switch (param.type) {
    // ─── Short text input (with inputMode hints for url / numeric) ───
    // Text / url / string / number all share the same plain
    // <input> renderer. The inputMode hint flips mobile keyboards
    // appropriately and is a strong a11y signal for desktop AT, but
    // doesn't gate desktop typing — so the URL field stays free-form
    // enough to accept "localhost:3001" or http://internal hostnames.
    case "text":
    case "url":
    case "string":
    case "number": {
      const inputMode =
        param.type === "url"
          ? "url"
          : param.type === "number"
            ? "numeric"
            : "text";
      return (
        <input
          type="text"
          inputMode={inputMode}
          value={value}
          onChange={(e) => onChange(param.name, e.target.value)}
          className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
          style={{ border: "0.5px solid var(--glass-border)" }}
          placeholder={param.defaultValue ?? `Enter ${param.display.toLowerCase()}`}
        />
      );
    }
    // ─── Masked input with eye-toggle reveal ─────────────────────────
    // "password" is a synonym for "secret" so connector
    // authors can use the more conventional name. Both go through
    // identical rendering. The eye toggle uses showSecret
    // — keyed by name so multiple masked fields on the same form
    // toggle independently.
    case "secret":
    case "password":
      return (
        <div className="relative">
          <input
            type={showSecret ? "text" : "password"}
            value={value === MASK ? "" : value}
            onChange={(e) => onChange(param.name, e.target.value)}
            className="w-full bg-surface-container-highest border-none rounded-xl px-4 pr-12 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
            style={{ border: "0.5px solid var(--glass-border)" }}
            placeholder={secretSet ? SECRET_PLACEHOLDER : `Enter ${param.display.toLowerCase()}`}
          />
          <button
            type="button"
            onClick={() => onToggleSecret?.()}
            className="absolute right-4 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
            aria-label={showSecret ? "Hide value" : "Show value"}
          >
            <span className="material-symbols-outlined text-lg">
              {showSecret ? "visibility_off" : "visibility"}
            </span>
          </button>
        </div>
      );
    // ─── Multiline <textarea> for long strings ───────────────────────
    // For JSON service-account blobs, PEM certs, multi-line
    // tokens. Auto-resizes via rows={4} initial + the existing
    // resize-y CSS. Doesn't include a syntax-highlighting layer (kept
    // simple — operators paste raw values; validation happens at
    // Test Connection time).
    case "textarea":
      return (
        <textarea
          value={value}
          onChange={(e) => onChange(param.name, e.target.value)}
          rows={4}
          className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline font-mono resize-y"
          style={{ border: "0.5px solid var(--glass-border)" }}
          placeholder={`Enter ${param.display.toLowerCase()}`}
        />
      );
    case "boolean":
      return (
        <div className="flex items-center justify-between p-4 rounded-xl" style={{ background: "var(--glass-bg)" }}>
          <div>
            <div className="text-sm font-medium text-on-surface">{param.display}</div>
            <div className="text-xs text-on-surface-variant mt-0.5">
              {value === "true" ? "Enabled" : "Disabled"} — toggle to change
            </div>
          </div>
          <button
            type="button"
            onClick={() => onChange(param.name, value === "true" ? "false" : "true")}
            className="relative inline-flex items-center"
            aria-label={`Toggle ${param.display}`}
          >
            <div
              className={`w-11 h-6 rounded-full transition-all ${
                value === "true" ? "bg-primary/40" : "bg-surface-container-highest"
              }`}
            >
              <div
                className={`absolute top-[2px] w-5 h-5 rounded-full transition-all ${
                  value === "true"
                    ? "left-[22px] bg-primary"
                    : "left-[2px] bg-outline"
                }`}
              />
            </div>
          </button>
        </div>
      );
    case "select":
      return (
        <div className="relative">
          <select
            value={value}
            onChange={(e) => onChange(param.name, e.target.value)}
            className="w-full appearance-none bg-surface-container-highest border-none rounded-xl px-4 py-3 pr-10 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface"
            style={{ border: "0.5px solid var(--glass-border)" }}
          >
            <option value="" disabled>Select {param.display.toLowerCase()}</option>
            {param.options?.map((opt) => (
              <option key={opt} value={opt}>{param.optionLabels?.[opt] ?? opt}</option>
            ))}
          </select>
          <span className="material-symbols-outlined absolute right-3 top-3.5 pointer-events-none text-on-surface-variant text-lg">
            expand_more
          </span>
        </div>
      );
    // ─── Radio button group ──────────────────────────────────────────
    // When a select-style field has 2-3 options and connector
    // authors want them VISIBLE at a glance instead of hidden behind a
    // dropdown click. options[] required; falls through to plain text
    // input when options aren't declared (defensive against
    // misconfigured synthetic cards).
    case "radio":
      if (!param.options || param.options.length === 0) {
        return (
          <p className="text-xs text-error italic">
            radio field missing options[] — falling back to plain text. Fix the connector card.
          </p>
        );
      }
      return (
        <div className="flex flex-wrap gap-2">
          {param.options.map((opt) => {
            const checked = value === opt;
            return (
              <label
                key={opt}
                className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm cursor-pointer transition-all ${
                  checked
                    ? "bg-primary/10 text-primary"
                    : "bg-surface-container-highest text-on-surface hover:bg-surface-variant/50"
                }`}
                style={{
                  border: checked
                    ? "0.5px solid rgba(167, 200, 255, 0.4)"
                    : "0.5px solid var(--glass-border)",
                }}
              >
                <input
                  type="radio"
                  name={param.name}
                  value={opt}
                  checked={checked}
                  onChange={() => onChange(param.name, opt)}
                  className="appearance-none w-4 h-4 rounded-full border border-outline checked:border-primary checked:bg-primary checked:shadow-[inset_0_0_0_3px_var(--m3-surface-container)] transition-all"
                />
                <span>{param.optionLabels?.[opt] ?? opt}</span>
              </label>
            );
          })}
        </div>
      );
    // ─── Multi-select chip list ──────────────────────────────────────
    // Bridges the gap between "array" (free-form chips, any
    // string) and "select" (single value). When the connector has an
    // explicit enum of valid choices but operators can pick multiple,
    // this renders a checkbox-style chip group + the selection serializes
    // as a JSON array string matching configValues' string-only shape.
    // Falls through to a warning if options[] isn't declared.
    case "multi_select": {
      if (!param.options || param.options.length === 0) {
        return (
          <p className="text-xs text-error italic">
            multi_select field missing options[] — fix the connector card to declare allowed values.
          </p>
        );
      }
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
        onChange(param.name, JSON.stringify(next));
      };
      return (
        <div className="flex flex-wrap gap-2">
          {param.options.map((opt) => {
            const isOn = selected.includes(opt);
            return (
              <button
                key={opt}
                type="button"
                onClick={() => toggle(opt)}
                className={`px-3 py-2 rounded-full text-xs transition-all ${
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
                {isOn && <span className="material-symbols-outlined text-xs mr-1 align-middle">check</span>}
                {opt}
              </button>
            );
          })}
        </div>
      );
    }
    case "array":
      // Chip-list editor for list-of-string fields. The
      // value is a JSON-stringified array (see `configValues`'s
      // string-only shape). Empty / unparseable input → empty list.
      // Add via Enter or the Add button; remove via the × on each
      // chip. Used by the web connector's allowed_domains to
      // present "vetted browsing hosts" as concrete chips instead
      // of a raw JSON blob the operator has to format correctly.
      return <ChipListField param={param} value={value} onChange={onChange} />;
    // ─── Default: unknown type → fall back to plain text + warn ────
    // Belt-and-suspenders. If a future field type lands in
    // the union without a matching switch case, we render SOMETHING
    // (a text input) rather than a label-only ghost, and surface the
    // gap to the operator so they can report it. The TypeScript union
    // makes this branch unreachable at compile time, but the
    // ConfigParam values come from JSON.parse'd API responses where
    // an out-of-band string could slip through.
    default: {
      const unknownType = (param as { type?: string }).type ?? "unset";
      return (
        <>
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(param.name, e.target.value)}
            className="w-full bg-surface-container-highest border-none rounded-xl px-4 py-3 text-sm focus:ring-1 focus:ring-primary/40 transition-all outline-none text-on-surface placeholder:text-outline"
            style={{ border: "0.5px solid var(--glass-border)" }}
            placeholder={`Enter ${param.display.toLowerCase()}`}
          />
          <p className="text-[10px] text-error italic mt-1">
            unknown widget type &quot;{unknownType}&quot; — rendered as text input. Update the connector card to use a supported widget.
          </p>
        </>
      );
    }
  }
}

/**
 * Every field that shows for the current values, in declaration order: label,
 * widget, a parameter-name footnote and the field's description. Boolean fields
 * skip the label since their toggle shows the display name inline.
 *
 * `setSecrets` names the secret slots the server already holds; they show a
 * placeholder instead of a value, and typing replaces them.
 */
export function ConfigFormFields({
  params,
  values,
  onChange,
  connectorName,
  setSecrets = [],
}: {
  params: ConfigParam[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  connectorName: string;
  setSecrets?: readonly string[];
}) {
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const toggleSecret = (name: string) => setShowSecrets((prev) => ({ ...prev, [name]: !prev[name] }));
  const badNumbers = new Set(invalidNumbers(params, values).map((p) => p.name));

  return (
    <div className="grid gap-6">
      {visibleParams(params, values).map((param) => {
        const secret = isSecretType(param.type);
        const widget = (
          <ConfigFieldInput
            param={param}
            value={valueOf(param, values)}
            onChange={onChange}
            secretSet={secret && setSecrets.includes(param.name)}
            showSecret={!!showSecrets[param.name]}
            onToggleSecret={() => toggleSecret(param.name)}
          />
        );
        if (param.type === "boolean") {
          return (
            <div key={param.name} className="space-y-2">
              {widget}
              {param.description && (
                <p className="text-[11px] text-on-surface-variant px-1 leading-relaxed">{param.description}</p>
              )}
            </div>
          );
        }
        return (
          <div key={param.name} className="space-y-2">
            <label className="text-[10px] uppercase tracking-widest font-label text-on-surface-variant">
              {param.display}
              {param.required && <span className="text-error ml-1">*</span>}
            </label>
            {widget}
            <p className="text-[10px] text-on-surface-variant/60 italic ml-1">
              {secret
                ? setSecrets.includes(param.name)
                  ? "A value is saved. Type a new one to replace it."
                  : `Encrypted credentials for ${connectorName}`
                : `Parameter: ${param.name}`}
            </p>
            {badNumbers.has(param.name) && (
              <p className="text-[11px] text-error px-1" role="alert">
                Enter a number, for example {param.defaultValue ?? "30"}, or leave it empty to use the default.
              </p>
            )}
            {param.description && param.type !== "array" && (
              <p className="text-[11px] text-on-surface-variant px-1 leading-relaxed">{param.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
