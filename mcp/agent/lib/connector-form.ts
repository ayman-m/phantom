/**
 * The logic behind the connector instance form on /connectors (Create and
 * Edit share it): which fields show, which are required, what Edit starts
 * from, and what Create and Edit send.
 *
 * A field can name another field that decides whether it shows
 * (`showWhen: { field, in }`). A hidden field is never required. The http-sender
 * card uses this to offer its two kinds of destination (the XSIAM HTTP
 * collector and the Cribl integration) behind a `destinationMode` switch.
 *
 * What is sent, in short:
 *   - Create sends only the fields that are showing, and drops empty ones.
 *   - Edit replaces the whole config on the server (secrets merge per slot),
 *     so it sends every saved key again (and no field that was never saved and
 *     still holds its default): a field that is hidden keeps its saved
 *     value, unless it is marked `clearWhenHidden` (a field that would keep a
 *     hidden mode's routing alive), which is sent empty.
 *   - A secret that is untouched is sent as "***" (keep), and one that was never
 *     set is left out.
 *
 * Erasable-syntax TypeScript only, no `@/` imports, so
 * scripts/test-connector-form.mjs can import this file directly with Node's
 * type stripping.
 */

/** The sentinel the server returns for a stored secret and accepts as "keep it". */
export const MASK = "***";

export interface FormParam {
  name: string;
  type: string;
  required: boolean;
  defaultValue?: string;
  /** Show this field only while the value of `field` is one of `in`. */
  showWhen?: { field: string; in: string[] };
  /** When hidden, Edit sends this field empty (it would keep a hidden mode's routing alive). */
  clearWhenHidden?: boolean;
}

export interface SavedInstance {
  config: Record<string, unknown>;
  secrets: Record<string, unknown>;
}

export interface CreatePayload {
  /** Strings, except array, boolean and number fields, which go as real JSON values (see typedValue). */
  config: Record<string, unknown>;
  secrets: Record<string, string>;
}

export interface EditPayload {
  /** Values are strings, except a saved value the operator did not change, which keeps its stored type (a boolean stays a boolean). */
  config: Record<string, unknown>;
  secrets: Record<string, string>;
}

export function isSecretType(type: string): boolean {
  return type === "secret" || type === "password";
}

/**
 * The value the connector should receive. The form edits strings, but a
 * connector reads its settings as stored (the web connector turns allowed_domains
 * into a list with list(), which splits the string '["a.example"]' into characters),
 * so array, boolean and number fields are sent as real JSON values. Text that
 * does not parse stays text.
 */
export function typedValue(type: string, value: string): unknown {
  const t = value.trim();
  if (type === "array" || type === "multi_select") {
    try {
      const parsed = JSON.parse(t);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      /* not JSON: keep the text */
    }
    return value;
  }
  if (type === "boolean") return t === "true" ? true : t === "false" ? false : value;
  if (type === "number") return NUMBER_TEXT.test(t) ? Number(t) : value;
  return value;
}

const NUMBER_TEXT = /^-?\d+(\.\d+)?$/;

/**
 * The visible number fields whose text is not a number ("30s"). The widget is a
 * text input, and connectors read these with int() or float(), which raise on
 * anything else, so the form blocks Save until the text is a number or empty.
 * An empty number field is not an error: it is left out and the connector
 * applies its own default.
 */
export function invalidNumbers<T extends FormParam>(params: T[], values: Record<string, string>): T[] {
  return visibleParams(params, values).filter((p) => {
    if (p.type !== "number") return false;
    const v = valueOf(p, values).trim();
    return v !== "" && !NUMBER_TEXT.test(v);
  });
}

/** A saved key the card does not declare is a secret when the server holds it as one, or its name says so. */
export function isUndeclaredSecret(key: string, savedSecrets: Record<string, unknown>): boolean {
  return (
    Object.prototype.hasOwnProperty.call(savedSecrets, key) ||
    /key|token|secret|password|credential/i.test(key)
  );
}

function text(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** What the field shows: the typed value, else its default, else empty. */
export function valueOf(param: FormParam, values: Record<string, string>): string {
  return values[param.name] ?? param.defaultValue ?? "";
}

/** Whether the field shows. The controlling field is read the same way as any other, default included. */
export function isVisible(
  param: FormParam,
  params: FormParam[],
  values: Record<string, string>,
): boolean {
  const rule = param.showWhen;
  if (!rule) return true;
  const controller = params.find((p) => p.name === rule.field);
  const current = controller ? valueOf(controller, values) : (values[rule.field] ?? "");
  return rule.in.includes(current);
}

export function visibleParams<T extends FormParam>(params: T[], values: Record<string, string>): T[] {
  return params.filter((p) => isVisible(p, params, values));
}

/**
 * The visible required fields that are still empty. A default counts as a value
 * (the form shows it), and so does a secret the server already holds
 * (`setSecrets`) or one that carries the keep sentinel.
 */
export function missingRequired<T extends FormParam>(
  params: T[],
  values: Record<string, string>,
  setSecrets: readonly string[] = [],
): T[] {
  return visibleParams(params, values).filter((p) => {
    if (!p.required) return false;
    if (isSecretType(p.type) && setSecrets.includes(p.name)) return false;
    return valueOf(p, values).trim() === "";
  });
}

/** Whether a saved JSON list has at least one entry ("[]", empty text and text that is not a list have none). */
function hasEntries(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  try {
    const parsed = JSON.parse(text(value));
    return Array.isArray(parsed) && parsed.length > 0;
  } catch {
    return false;
  }
}

/**
 * Which destinations an http-sender instance saved without a mode is using.
 * The collector side is a collector URL or a list of additional destinations
 * with at least one entry (a saved "[]" is not one);
 * the Cribl side counts only when the Cribl URL is set AND the Cribl token is
 * saved (a Cribl URL with no token is half-configured and must not open a
 * mode that then demands a collector or blocks Save). Both sides is "both",
 * only the Cribl side is "cribl", anything else is "http".
 */
export function inferDestinationMode(
  config: Record<string, unknown>,
  secrets: Record<string, unknown> = {},
): "http" | "cribl" | "both" {
  const collector =
    text(config.collectorUrl).trim() !== "" || hasEntries(config.additionalDestinations);
  const cribl =
    text(config.criblUrl).trim() !== "" && Object.prototype.hasOwnProperty.call(secrets, "criblToken");
  if (collector && cribl) return "both";
  if (cribl) return "cribl";
  return "http";
}

/**
 * What Edit starts from: every declared field's default, then the saved config
 * (with the inferred mode when an older instance has none), then the masked
 * secret slots the server reports. A field or slot never set stays at its
 * default or empty, so it can be filled in.
 */
export function seedEditValues(
  connectorId: string,
  params: FormParam[],
  saved: SavedInstance,
): Record<string, string> {
  const values: Record<string, string> = {};
  for (const p of params) {
    if (p.defaultValue !== undefined) values[p.name] = p.defaultValue;
  }
  for (const [k, v] of Object.entries(saved.config)) values[k] = text(v);
  if (
    connectorId === "http-sender" &&
    params.some((p) => p.name === "destinationMode") &&
    !Object.prototype.hasOwnProperty.call(saved.config, "destinationMode")
  ) {
    values.destinationMode = inferDestinationMode(saved.config, saved.secrets);
  }
  for (const k of Object.keys(saved.secrets)) values[k] = MASK;
  return values;
}

/** The body for creating an instance: the fields that show, empty ones dropped. */
export function buildCreatePayload(params: FormParam[], values: Record<string, string>): CreatePayload {
  const out: CreatePayload = { config: {}, secrets: {} };
  for (const p of visibleParams(params, values)) {
    const v = values[p.name];
    if (v === undefined || v === "") continue;
    if (p.type === "number" && v.trim() === "") continue;
    if (isSecretType(p.type)) out.secrets[p.name] = v;
    else out.config[p.name] = typedValue(p.type, v);
  }
  return out;
}

/**
 * The body for saving (and for a dry-run Test Connection in) the Edit dialog.
 * The server replaces `config` wholesale, so every saved key goes back.
 */
export function buildEditPayload(
  params: FormParam[],
  values: Record<string, string>,
  saved: SavedInstance,
): EditPayload {
  const out: EditPayload = { config: {}, secrets: {} };
  const declared = new Set(params.map((p) => p.name));
  const had = (obj: Record<string, unknown>, k: string) => Object.prototype.hasOwnProperty.call(obj, k);
  // The form edits strings; a value the operator did not touch goes back as it was stored.
  const keep = (k: string, v: string): unknown =>
    had(saved.config, k) && text(saved.config[k]) === v ? saved.config[k] : v;

  for (const p of params) {
    const visible = isVisible(p, params, values);
    if (isSecretType(p.type)) {
      const held = had(saved.secrets, p.name);
      const v = visible ? (values[p.name] ?? "") : "";
      if (v === "" || v === MASK || v === "****") {
        if (held) out.secrets[p.name] = MASK;
      } else {
        out.secrets[p.name] = v;
      }
      continue;
    }
    const v = !visible && p.clearWhenHidden ? "" : valueOf(p, values);
    // A field that was never saved and still holds its default (or nothing) is
    // left out: the config is replaced wholesale, and the connector applies the
    // default itself. Only saved keys and fields the operator filled in go back.
    const saveable = had(saved.config, p.name) || (v !== "" && v !== (p.defaultValue ?? ""));
    if (!saveable) continue;
    // An empty number is left out, even if one was saved: int("") raises in the
    // connector, and with the key gone it applies its own default.
    if (p.type === "number" && v.trim() === "") continue;
    const typed = typedValue(p.type, v);
    out.config[p.name] = typed !== v ? typed : keep(p.name, v);
  }

  // Saved keys the card does not declare (an uploaded connector, an older
  // instance) go back as they are, or as edited in the dialog.
  for (const k of Object.keys(saved.config)) {
    if (declared.has(k)) continue;
    if (isUndeclaredSecret(k, saved.secrets)) {
      const v = values[k] ?? MASK;
      out.secrets[k] = v === "" || v === "****" ? MASK : v;
    } else {
      out.config[k] = keep(k, values[k] ?? text(saved.config[k]));
    }
  }
  for (const k of Object.keys(saved.secrets)) {
    if (declared.has(k) || had(out.secrets, k)) continue;
    const v = values[k] ?? MASK;
    out.secrets[k] = v === "" || v === "****" ? MASK : v;
  }
  return out;
}
