"use client";

/**
 * /help/api/[id] — endpoint detail page with a working try-it-out form.
 *
 * Three vertical sections:
 *
 *   1. Header — method + path + summary + description + risk badge.
 *   2. Try it out — auto-generated form for path/query params and
 *      the body. The Send button fires a real request through the
 *      agent UI's proxy (auth attached server-side); the response
 *      pane shows status, latency, headers, and pretty-printed body.
 *   3. Reference — request schema, all documented response shapes,
 *      and the per-endpoint OpenAPI 3.0 PathItem snippet (copy-able
 *      into a Swagger doc).
 *
 * Self-modification risk tiers (soft / destructive / credential) drive a
 * "this will modify state — operator approval required" banner above
 * the Send button so operators don't get surprised by the inline
 * approval card flow when they click.
 */

import Link from "next/link";
import { use, useMemo, useState } from "react";

import { getEndpointById, type ApiEndpoint } from "@/lib/api-catalog";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

const glassStyleSubtle = {
  background: "rgba(20, 20, 45, 0.25)",
  backdropFilter: "blur(8px)",
  border: "0.5px solid rgba(140, 145, 157, 0.1)",
} as const;

const METHOD_COLOR: Record<string, string> = {
  GET: "bg-secondary/15 text-secondary",
  POST: "bg-primary/15 text-primary",
  PUT: "bg-tertiary/15 text-tertiary",
  PATCH: "bg-tertiary/15 text-tertiary",
  DELETE: "bg-error/15 text-error",
};

const TIER_LABEL: Record<string, string> = {
  soft: "Approval-gated (soft)",
  destructive: "Destructive — approval required + cannot be undone",
  credential: "Credential operation — type CONFIRM at approval time",
};

interface ResponseInfo {
  status: number;
  statusText: string;
  body: string;
  headers: Record<string, string>;
  latencyMs: number;
  parsedBody: unknown;
}

export default function ApiEndpointDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const endpoint = getEndpointById(id);

  if (!endpoint) {
    return (
      <div className="h-screen flex items-center justify-center text-on-surface-variant">
        <div className="text-center">
          <p className="text-base">Endpoint not found.</p>
          <Link href="/help/api" className="text-primary hover:underline mt-2 inline-block">
            ← Back to API catalog
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto custom-scrollbar">
      <div className="max-w-[1200px] mx-auto px-8 py-8 space-y-6">
        <Header endpoint={endpoint} />
        <TryItOut endpoint={endpoint} />
        <Reference endpoint={endpoint} />
      </div>
    </div>
  );
}

function Header({ endpoint }: { endpoint: ApiEndpoint }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs">
        <Link href="/help" className="text-on-surface-variant/60 hover:text-on-surface transition-colors">
          Help
        </Link>
        <span className="text-on-surface-variant/40">/</span>
        <Link href="/help/api" className="text-on-surface-variant/60 hover:text-on-surface transition-colors">
          API
        </Link>
        <span className="text-on-surface-variant/40">/</span>
        <span className="text-on-surface-variant">{endpoint.id}</span>
      </div>

      <div className="flex items-start gap-3 flex-wrap">
        <span
          className={
            "rounded-md px-2.5 py-1 text-[11px] font-mono font-bold uppercase tracking-wider mt-1 " +
            METHOD_COLOR[endpoint.method]
          }
        >
          {endpoint.method}
        </span>
        <code className="text-base font-mono text-on-surface break-all">{endpoint.path}</code>
      </div>

      <h1 className="text-xl font-headline font-bold text-on-surface">
        {endpoint.summary}
      </h1>
      <p className="text-sm text-on-surface-variant leading-relaxed max-w-3xl">
        {endpoint.description}
      </p>

      {endpoint.riskTier ? (
        <div
          className={
            "rounded-lg px-4 py-3 text-xs flex items-start gap-3 " +
            (endpoint.riskTier === "destructive" || endpoint.riskTier === "credential"
              ? "bg-error/10 text-error border border-error/30"
              : "bg-tertiary/10 text-tertiary border border-tertiary/30")
          }
        >
          <span className="material-symbols-outlined text-base">
            {endpoint.riskTier === "credential" ? "key" : "warning"}
          </span>
          <div className="flex-1">
            <strong className="font-headline">
              {TIER_LABEL[endpoint.riskTier]}
            </strong>
            <p className="opacity-80 mt-1">
              When the agent invokes this from chat the inline approval card gates the call.
              When you invoke it directly via Try it Out, you bypass the agent path —
              the operator (you) is implicitly the approver.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TryItOut({ endpoint }: { endpoint: ApiEndpoint }) {
  const [pathValues, setPathValues] = useState<Record<string, string>>(
    () =>
      Object.fromEntries(
        (endpoint.pathParams ?? []).map((p) => [p.name, String(p.example ?? "")]),
      ),
  );
  const [queryValues, setQueryValues] = useState<Record<string, string>>(
    () =>
      Object.fromEntries(
        (endpoint.queryParams ?? []).map((p) => [
          p.name,
          p.example !== undefined ? String(p.example) : "",
        ]),
      ),
  );
  const [bodyText, setBodyText] = useState<string>(() =>
    endpoint.body ? JSON.stringify(endpoint.body.example, null, 2) : "",
  );
  const [pending, setPending] = useState(false);
  const [response, setResponse] = useState<ResponseInfo | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const interpolatedPath = useMemo(() => {
    let p = endpoint.path;
    for (const [k, v] of Object.entries(pathValues)) {
      p = p.replace(`{${k}}`, encodeURIComponent(v || ""));
    }
    return p.split("?")[0];
  }, [endpoint.path, pathValues]);

  const queryString = useMemo(() => {
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(queryValues)) {
      if (v !== "") usp.set(k, v);
    }
    const s = usp.toString();
    return s ? `?${s}` : "";
  }, [queryValues]);

  const finalUrl = interpolatedPath + queryString;

  async function send() {
    setPending(true);
    setErrorMsg(null);
    setResponse(null);
    const t0 = performance.now();
    try {
      let parsedBody: unknown = undefined;
      if (endpoint.body && bodyText.trim() !== "") {
        try {
          parsedBody = JSON.parse(bodyText);
        } catch (parseErr) {
          throw new Error(
            `Body is not valid JSON: ${
              parseErr instanceof Error ? parseErr.message : parseErr
            }`,
          );
        }
      }
      const r = await fetch(finalUrl, {
        method: endpoint.method,
        headers:
          parsedBody !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: parsedBody !== undefined ? JSON.stringify(parsedBody) : undefined,
      });
      const text = await r.text();
      const headers: Record<string, string> = {};
      r.headers.forEach((v, k) => {
        headers[k] = v;
      });
      let parsed: unknown = text;
      try {
        parsed = JSON.parse(text);
      } catch {
        // not JSON; keep as text
      }
      setResponse({
        status: r.status,
        statusText: r.statusText,
        body: text,
        parsedBody: parsed,
        headers,
        latencyMs: Math.round(performance.now() - t0),
      });
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4 rounded-2xl p-5" style={glassStyle}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-sm font-headline font-bold text-on-surface uppercase tracking-wider">
          Try it out
        </h2>
        <span className="text-[11px] text-on-surface-variant/60 font-mono break-all">
          {endpoint.method} {finalUrl}
        </span>
      </div>

      {(endpoint.pathParams ?? []).length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
            Path parameters
          </div>
          <div className="grid gap-2">
            {endpoint.pathParams!.map((p) => (
              <ParamInput
                key={p.name}
                name={p.name}
                description={p.description}
                value={pathValues[p.name] ?? ""}
                onChange={(v) => setPathValues((prev) => ({ ...prev, [p.name]: v }))}
                enumValues={p.enum}
                required
              />
            ))}
          </div>
        </div>
      )}

      {(endpoint.queryParams ?? []).length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
            Query parameters
          </div>
          <div className="grid gap-2">
            {endpoint.queryParams!.map((p) => (
              <ParamInput
                key={p.name}
                name={p.name}
                description={p.description}
                value={queryValues[p.name] ?? ""}
                onChange={(v) => setQueryValues((prev) => ({ ...prev, [p.name]: v }))}
                enumValues={p.enum}
                required={!!p.required}
              />
            ))}
          </div>
        </div>
      )}

      {endpoint.body ? (
        <div className="space-y-2">
          <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
            Request body ({endpoint.body.contentType})
          </div>
          <textarea
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
            rows={Math.min(20, Math.max(6, bodyText.split("\n").length))}
            spellCheck={false}
            className="w-full px-3 py-2 text-xs font-mono bg-surface-container-lowest/50 rounded-lg border border-on-surface/10 outline-none focus:border-primary/50 text-on-surface resize-y"
          />
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <button
          onClick={() => void send()}
          disabled={pending}
          className="px-4 py-2 rounded-lg text-xs font-headline font-bold uppercase tracking-widest bg-primary text-on-primary hover:opacity-90 transition-opacity disabled:opacity-50 active:scale-95"
        >
          {pending ? "Sending…" : "Send request"}
        </button>
        {errorMsg ? (
          <span className="text-xs text-error">{errorMsg}</span>
        ) : response ? (
          <span className="text-xs text-on-surface-variant/70 font-mono">
            HTTP {response.status} {response.statusText} · {response.latencyMs}ms
          </span>
        ) : null}
      </div>

      {response ? <ResponseViewer response={response} /> : null}
    </div>
  );
}

function ParamInput({
  name,
  description,
  value,
  onChange,
  enumValues,
  required,
}: {
  name: string;
  description: string;
  value: string;
  onChange: (v: string) => void;
  enumValues?: string[];
  required: boolean;
}) {
  const inputId = `param-${name}`;
  return (
    <div className="grid grid-cols-[180px_1fr] gap-3 items-start">
      <label htmlFor={inputId} className="text-xs font-mono text-on-surface-variant pt-2">
        <span className="text-primary">{name}</span>
        {required ? <span className="text-error ml-0.5">*</span> : null}
        <div className="text-[10px] text-on-surface-variant/60 font-sans mt-0.5 leading-relaxed">
          {description}
        </div>
      </label>
      {enumValues && enumValues.length > 0 ? (
        <select
          id={inputId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="px-3 py-2 text-xs font-mono bg-surface-container-lowest/50 rounded-lg border border-on-surface/10 outline-none focus:border-primary/50 text-on-surface"
        >
          <option value="">(none)</option>
          {enumValues.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={inputId}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="px-3 py-2 text-xs font-mono bg-surface-container-lowest/50 rounded-lg border border-on-surface/10 outline-none focus:border-primary/50 text-on-surface"
        />
      )}
    </div>
  );
}

function ResponseViewer({ response }: { response: ResponseInfo }) {
  const isOk = response.status >= 200 && response.status < 300;
  const pretty = useMemo(() => {
    try {
      return JSON.stringify(response.parsedBody, null, 2);
    } catch {
      return response.body;
    }
  }, [response]);

  return (
    <div className="space-y-2">
      <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant flex items-center gap-2">
        Response
        <span
          className={
            "rounded-full px-2 py-0.5 text-[10px] font-medium " +
            (isOk ? "bg-secondary/15 text-secondary" : "bg-error/15 text-error")
          }
        >
          {response.status} {response.statusText}
        </span>
      </div>
      <pre
        className="rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap break-all max-h-[480px] overflow-auto text-on-surface-variant"
        style={glassStyleSubtle}
      >
        {pretty}
      </pre>
      <details className="text-[11px]">
        <summary className="cursor-pointer text-on-surface-variant/60 hover:text-on-surface transition-colors">
          Response headers ({Object.keys(response.headers).length})
        </summary>
        <pre
          className="mt-1 px-3 py-2 text-[11px] font-mono text-on-surface-variant"
          style={glassStyleSubtle}
        >
          {Object.entries(response.headers)
            .map(([k, v]) => `${k}: ${v}`)
            .join("\n")}
        </pre>
      </details>
    </div>
  );
}

function Reference({ endpoint }: { endpoint: ApiEndpoint }) {
  const snippet = useMemo(() => {
    const op: Record<string, unknown> = {
      operationId: endpoint.id,
      summary: endpoint.summary,
      description: endpoint.description,
      tags: [endpoint.category],
    };
    const parameters: unknown[] = [];
    for (const p of endpoint.pathParams ?? []) {
      parameters.push({
        name: p.name,
        in: "path",
        required: true,
        description: p.description,
        schema: { type: p.type, ...(p.enum ? { enum: p.enum } : {}) },
      });
    }
    for (const p of endpoint.queryParams ?? []) {
      parameters.push({
        name: p.name,
        in: "query",
        required: !!p.required,
        description: p.description,
        schema: { type: p.type, ...(p.enum ? { enum: p.enum } : {}) },
      });
    }
    if (parameters.length > 0) op.parameters = parameters;
    if (endpoint.body) {
      op.requestBody = {
        required: true,
        content: {
          [endpoint.body.contentType]: {
            schema: endpoint.body.schema,
            example: endpoint.body.example,
          },
        },
      };
    }
    op.responses = Object.fromEntries(
      endpoint.responses.map((r) => [
        r.status,
        r.example !== undefined
          ? {
              description: r.description,
              content: { "application/json": { example: r.example } },
            }
          : { description: r.description },
      ]),
    );
    if (endpoint.riskTier) op["x-phantom-risk-tier"] = endpoint.riskTier;
    return JSON.stringify(
      {
        [endpoint.path.split("?")[0]]: { [endpoint.method.toLowerCase()]: op },
      },
      null,
      2,
    );
  }, [endpoint]);

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-headline font-bold text-on-surface uppercase tracking-wider">
        Reference
      </h2>

      {endpoint.body ? (
        <div className="rounded-2xl p-5 space-y-2" style={glassStyle}>
          <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
            Request schema
          </div>
          <pre
            className="rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap text-on-surface-variant"
            style={glassStyleSubtle}
          >
            {JSON.stringify(endpoint.body.schema, null, 2)}
          </pre>
        </div>
      ) : null}

      <div className="rounded-2xl p-5 space-y-3" style={glassStyle}>
        <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
          Responses
        </div>
        <div className="space-y-3">
          {endpoint.responses.map((r) => (
            <div key={r.status} className="rounded-lg p-3" style={glassStyleSubtle}>
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={
                    "rounded-md px-2 py-0.5 text-[10px] font-mono font-bold " +
                    (r.status.startsWith("2")
                      ? "bg-secondary/15 text-secondary"
                      : "bg-error/15 text-error")
                  }
                >
                  {r.status}
                </span>
                <span className="text-xs text-on-surface">{r.description}</span>
              </div>
              {r.example !== undefined ? (
                <pre className="text-xs font-mono whitespace-pre-wrap text-on-surface-variant mt-2">
                  {JSON.stringify(r.example, null, 2)}
                </pre>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-2xl p-5 space-y-2" style={glassStyle}>
        <div className="flex items-center justify-between">
          <div className="text-[10px] font-headline uppercase tracking-widest text-on-surface-variant">
            OpenAPI 3.0 PathItem
          </div>
          <button
            onClick={() => navigator.clipboard.writeText(snippet)}
            className="px-2 py-1 rounded-md text-[10px] font-medium uppercase tracking-wider text-on-surface-variant hover:text-on-surface transition-colors"
            style={glassStyleSubtle}
          >
            <span className="material-symbols-outlined text-sm align-middle mr-1">
              content_copy
            </span>
            Copy
          </button>
        </div>
        <pre
          className="rounded-lg px-3 py-2 text-xs font-mono whitespace-pre-wrap text-on-surface-variant max-h-[400px] overflow-auto"
          style={glassStyleSubtle}
        >
          {snippet}
        </pre>
      </div>
    </div>
  );
}
