/**
 * Generate an OpenAPI 3.0 spec object from the api-catalog.
 *
 * The /api/agent/openapi endpoint serves the JSON output. The /help/api
 * detail page renders a per-endpoint snippet from the same generator
 * (operators can copy a single PathItem into their own Swagger doc).
 */

import { API_ENDPOINTS, type ApiEndpoint, type ParamSpec } from "./api-catalog";

interface OpenApiServer {
  url: string;
  description: string;
}

interface OpenApiInfo {
  title: string;
  version: string;
  description: string;
  contact?: { name: string; url?: string };
  license?: { name: string; url?: string };
}

export interface OpenApiSpec {
  openapi: "3.0.3";
  info: OpenApiInfo;
  servers: OpenApiServer[];
  tags: Array<{ name: string; description?: string }>;
  paths: Record<string, Record<string, unknown>>;
  components: {
    securitySchemes: Record<string, unknown>;
    schemas: Record<string, unknown>;
  };
  security: Array<Record<string, string[]>>;
}

/** Convert /api/agent/jobs/{jobName}/runs → /api/agent/jobs/{jobName}/runs (already OpenAPI form). */
function normalizePath(p: string): string {
  // The catalog already uses {param} syntax. Strip query strings off
  // for the path key — OpenAPI declares query params separately.
  return p.split("?")[0];
}

function paramToOpenApi(p: ParamSpec, location: "path" | "query") {
  const schema: Record<string, unknown> = { type: p.type };
  if (p.enum && p.enum.length > 0) schema.enum = p.enum;
  if (p.example !== undefined) schema.example = p.example;
  return {
    name: p.name,
    in: location,
    required: location === "path" ? true : !!p.required,
    description: p.description,
    schema,
  };
}

function endpointToOperation(e: ApiEndpoint): Record<string, unknown> {
  const params = [
    ...(e.pathParams ?? []).map((p) => paramToOpenApi(p, "path")),
    ...(e.queryParams ?? []).map((p) => paramToOpenApi(p, "query")),
  ];

  const op: Record<string, unknown> = {
    operationId: e.id,
    summary: e.summary,
    description: e.description,
    tags: e.tags ?? [e.category],
  };
  if (params.length > 0) op.parameters = params;

  if (e.body) {
    op.requestBody = {
      required: true,
      content: {
        [e.body.contentType]: {
          schema: e.body.schema,
          example: e.body.example,
        },
      },
    };
  }

  const responses: Record<string, unknown> = {};
  for (const r of e.responses) {
    const respBody: Record<string, unknown> = { description: r.description };
    if (r.example !== undefined) {
      respBody.content = {
        "application/json": {
          example: r.example,
        },
      };
    }
    responses[r.status] = respBody;
  }
  op.responses = responses;

  // Self-modification metadata as x-phantom-* extensions so OpenAPI consumers
  // can render UI hints (color-code destructive ops, surface
  // approval-required badges) without needing the catalog directly.
  if (e.riskTier) op["x-phantom-risk-tier"] = e.riskTier;
  if (e.requiresApproval) op["x-phantom-requires-approval"] = true;

  return op;
}

export function generateOpenApiSpec(opts?: {
  serverUrl?: string;
  version?: string;
}): OpenApiSpec {
  const serverUrl = opts?.serverUrl ?? "http://localhost:3000";
  const version = opts?.version ?? "1.0.0";

  // Aggregate endpoints by normalized path. OpenAPI's path object is
  // method-keyed: { "/jobs": { get: {...}, post: {...} } }.
  const paths: Record<string, Record<string, unknown>> = {};
  for (const e of API_ENDPOINTS) {
    const p = normalizePath(e.path);
    paths[p] = paths[p] ?? {};
    paths[p][e.method.toLowerCase()] = endpointToOperation(e);
  }

  // Group categories into OpenAPI tags so Swagger UI / Redoc render
  // them as collapsible sections.
  const seen = new Set<string>();
  const tags: Array<{ name: string; description?: string }> = [];
  for (const e of API_ENDPOINTS) {
    if (seen.has(e.category)) continue;
    seen.add(e.category);
    tags.push({ name: e.category, description: undefined });
  }

  return {
    openapi: "3.0.3",
    info: {
      title: "Phantom Agent API",
      version,
      description:
        "Operator-facing REST surface for the Phantom SOC simulation " +
        "agent. The agent UI proxies (`/api/agent/*`) attach the bundle's " +
        "MCP_TOKEN server-side and forward to the embedded MCP at " +
        "`/api/v1/*`. Everything documented here goes through the proxy " +
        "(no token needed in the browser).",
      contact: { name: "ayman-m", url: "https://github.com/ayman-m/phantom" },
      license: { name: "Apache-2.0" },
    },
    servers: [{ url: serverUrl, description: "Local agent UI" }],
    tags,
    paths,
    components: {
      securitySchemes: {
        cookieAuth: {
          type: "apiKey",
          in: "cookie",
          name: "session",
          description:
            "Operator UI session cookie set by /api/auth/login. The proxy " +
            "validates the cookie and attaches the bundle MCP_TOKEN to the " +
            "upstream MCP request.",
        },
        bearerAuth: {
          type: "http",
          scheme: "bearer",
          description:
            "Direct MCP bearer (`/api/v1/*`). Use `MCP_TOKEN` from the " +
            "bundle env. Most operators should use the cookieAuth + " +
            "/api/agent/* proxy path instead.",
        },
      },
      schemas: {},
    },
    security: [{ cookieAuth: [] }],
  };
}
