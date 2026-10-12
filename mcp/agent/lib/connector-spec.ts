/**
 * Turns the raw parts of a connector.yaml into the card shape /connectors
 * renders (`MarketplaceConnector`, lib/api/marketplace.ts).
 *
 * Two callers:
 *   - app/api/marketplace/connectors/route.ts overlays the live
 *     `spec.tools[]` of each bundle connector on its curated card;
 *   - app/api/agent/marketplace/catalog/user/route.ts builds the whole card
 *     for a connector the operator uploaded, from the `detail` object the
 *     MCP's marketplace catalogue returns for origin "user" entries.
 *
 * Erasable-syntax TypeScript only, so scripts/test-connector-spec.mjs can
 * import this file directly with Node's type stripping.
 */

import type { MarketplaceConnector } from "./api/marketplace";

type Tool = MarketplaceConnector["tools"][number];
type ConfigField = MarketplaceConnector["config"][number];

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

/** `spec.tools[]` of a connector.yaml -> the tool rows the detail panel lists. */
export function toolsFromSpec(rawTools: unknown): Tool[] {
  if (!Array.isArray(rawTools)) return [];
  const out: Tool[] = [];
  for (const raw of rawTools) {
    const t = asRecord(raw);
    const name = typeof t.name === "string" ? t.name : null;
    if (!name) continue;
    const m = typeof t.method === "string" ? t.method : "";
    const method = m.startsWith("GET")
      ? "GET"
      : m.startsWith("PUT")
        ? "PUT"
        : m.startsWith("DELETE")
          ? "DELETE"
          : "POST";
    const description =
      typeof t.description === "string"
        ? t.description.trim().split("\n")[0].slice(0, 220)
        : "";
    const args: Tool["args"] = [];
    if (Array.isArray(t.args)) {
      for (const rawArg of t.args) {
        const a = asRecord(rawArg);
        const aname = typeof a.name === "string" ? a.name : null;
        if (!aname) continue;
        args.push({
          name: aname,
          type: typeof a.type === "string" ? a.type : "string",
          description: typeof a.description === "string" ? a.description : "",
          required: a.required === true,
          defaultValue:
            typeof a.defaultValue === "string"
              ? a.defaultValue
              : typeof a.default === "string"
                ? a.default
                : undefined,
        });
      }
    }
    out.push({ name, method, description, args });
  }
  return out;
}

const WIDGET_TYPES = new Set(["url", "textarea", "password", "secret"]);

/** `configSchema` + `secretSlots` -> the fields of the create-instance form. */
export function configFromSpec(configSchema: unknown, secretSlots: unknown): ConfigField[] {
  const schema = asRecord(configSchema);
  const props = asRecord(schema.properties);
  const required = new Set(
    Array.isArray(schema.required)
      ? schema.required.filter((r): r is string => typeof r === "string")
      : [],
  );
  const fields: ConfigField[] = [];
  for (const [key, rawProp] of Object.entries(props)) {
    const prop = asRecord(rawProp);
    const widget = typeof prop.widget === "string" ? prop.widget : "";
    const jsonType = typeof prop.type === "string" ? prop.type : "string";
    const options = Array.isArray(prop.enum) ? prop.enum.map(String) : undefined;
    let type: string;
    if (WIDGET_TYPES.has(widget)) type = widget;
    else if (options && options.length > 0) type = "select";
    else if (jsonType === "number" || jsonType === "integer") type = "number";
    else if (jsonType === "boolean") type = "boolean";
    else if (jsonType === "array") type = "array";
    else type = "string";
    const dflt = prop.default;
    fields.push({
      display: typeof prop.title === "string" && prop.title ? prop.title : key,
      name: key,
      type,
      required: required.has(key),
      defaultValue:
        dflt === undefined || dflt === null || dflt === "" ? undefined : String(dflt),
      options,
      description: typeof prop.description === "string" ? prop.description : undefined,
    });
  }
  if (Array.isArray(secretSlots)) {
    for (const rawSlot of secretSlots) {
      const slot = asRecord(rawSlot);
      const name = typeof slot.name === "string" ? slot.name : null;
      if (!name) continue;
      fields.push({
        display: name,
        name,
        type: "secret",
        required: slot.required === true,
        description: typeof slot.description === "string" ? slot.description : undefined,
      });
    }
  }
  return fields;
}

/** One row of `GET /api/v1/marketplace` for an origin "user" connector. */
export interface UserCatalogueRow {
  id: string;
  version?: string;
  display_name?: string;
  description?: string;
  tags?: string[];
  installed?: boolean;
  detail?: {
    image?: string;
    language?: string;
    config_schema?: unknown;
    secret_slots?: unknown;
    tools?: unknown;
  };
}

/** The marketplace card for a connector the operator uploaded. */
export function userConnectorCard(row: UserCatalogueRow): MarketplaceConnector {
  const detail = row.detail ?? {};
  const tools = toolsFromSpec(detail.tools);
  const config = configFromSpec(detail.config_schema, detail.secret_slots);
  const version = row.version || "0.0.0";
  const image = detail.image ?? "";
  const description = row.description || row.display_name || row.id;
  return {
    id: row.id,
    name: row.display_name || row.id,
    type: "tool",
    version,
    publisher: "Uploaded",
    description,
    longDescription: description,
    category: "Services",
    tags: Array.isArray(row.tags) ? row.tags.filter((t) => typeof t === "string") : [],
    icon: "extension",
    iconColor: "#60a5fa",
    iconBg: "rgba(96, 165, 250, 0.12)",
    toolCount: tools.length,
    installs: "uploaded",
    installCount: 0,
    status: row.installed ? "installed" : "not_installed",
    reliability: "custom",
    authType: config.some((c) => c.type === "secret") ? "Per-instance secrets" : "None",
    tools,
    config,
    versions: [{ version, date: "", changes: ["Uploaded connector."] }],
    setupGuide: image
      ? `Install this connector, then create an instance on the Instances tab. Creating the instance pulls ${image} and starts its container.`
      : "Install this connector, then create an instance on the Instances tab.",
    dockerImage: image,
    runtime: "container",
    sdkLanguage: detail.language ?? "",
    sdkPackage: "",
    ingestion: { enabled: false, mode: "", description: "" },
    topAgents: [],
    origin: "user",
  };
}
