/**
 * Backup endpoint — produces a downloadable zip snapshot of every
 * operator-owned data surface so the deployment can be restored
 * (potentially on a different host) via POST /api/agent/restore.
 *
 * Sections (one file per section in the zip root):
 *   - manifest.json        zip metadata + version + warning
 *   - personality.json     SqlitePersonalityStore blob
 *   - instances.json       InstanceStore rows + cleartext secrets
 *   - memory.json          Memory entries (embeddings stripped — they
 *                          are dim-bound and the destination re-embeds
 *                          on next semantic search)
 *   - jobs.json            Runtime job definitions (manifest jobs are
 *                          NOT exported; they reseed from manifest.yaml
 *                          at boot)
 *   - skills/              Tree of MD files preserving category subdir
 *   - knowledge/           Tree of KB doc MDs preserving kb-name subdir
 *   - data_sources/        operator-owned data-source state:
 *                            user/<id>.json   parsed YAML doc per
 *                                            operator-uploaded data
 *                                            source (origin=user only;
 *                                            bundle YAMLs re-arrive in
 *                                            the destination's image)
 *                            installed.json   [{pack_name, rule_name,
 *                                            dataset_name}, ...] of
 *                                            packs currently installed
 *                                            in data_sources.db. Restore
 *                                            re-runs install per row so
 *                                            the destination ends up
 *                                            with the same install set.
 *   - operator_state.json  the operator's workflow state from
 *                          operator_state.db (journeys marked tested,
 *                          saved metric bookmarks): every key with its
 *                          value. Not a secret, not platform catalogue
 *                          (see lib/operator-state-backup.ts).
 *
 * Auth: cookie session check at the route level. A backup with
 * cleartext secrets must not be reachable to anonymous callers.
 *
 * Secrets handling: instances.json contains cleartext
 * secrets. The backup zip is operator-sensitive — the manifest
 * carries an explicit warning so downstream tooling can also flag
 * it. On restore the destination's SecretStore re-encrypts under
 * the destination's PHANTOM_SECRET_KEK, so the zip is portable
 * across deployments with different KEKs.
 *
 * Embedding handling: memory entries' raw embedding BLOBs are
 * NOT exported. They're tied to the source deployment's embedder
 * dimensionality; importing them into a deployment with a
 * different embedder would corrupt search.
 */

import { NextResponse } from "next/server";

import JSZip from "jszip";

import { PhantomMCPClient } from "@/lib/mcp-client";
import {
  OPERATOR_STATE_FILE,
  buildOperatorStateSection,
} from "@/lib/operator-state-backup";
import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

const SCHEMA_VERSION = 1;

export const dynamic = "force-dynamic";
export const maxDuration = 120;

interface McpResolved {
  base: string;
  token: string;
  streamUrl: string;
}

async function _resolveMcp(): Promise<McpResolved | NextResponse> {
  const cfg = await getEffectiveRuntimeConfig();
  const mcpToken =
    (cfg.MCP_TOKEN || "").trim() || process.env.MCP_TOKEN?.trim() || "";
  if (!mcpToken) {
    return NextResponse.json(
      { error: "MCP_TOKEN not configured" },
      { status: 503 },
    );
  }
  const streamUrl =
    (cfg.MCP_URL || "").trim() ||
    process.env.MCP_URL?.trim() ||
    "http://phantom-mcp:8080/api/v1/stream/mcp";
  const base = deriveMcpBaseUrl(streamUrl);
  if (!base) {
    return NextResponse.json({ error: "bad MCP URL" }, { status: 500 });
  }
  return { base, token: mcpToken, streamUrl };
}

interface MemoryEntry {
  id?: string;
  key?: string;
  value?: unknown;
  scope?: string;
  embedding?: unknown;
  [k: string]: unknown;
}

interface JobEntry {
  source?: string;
  [k: string]: unknown;
}

interface SkillListItem {
  name: string;
  category: string;
  file_path: string;
  [k: string]: unknown;
}

interface KbSummary {
  name: string;
  doc_count?: number;
  [k: string]: unknown;
}

interface KbDocStub {
  doc_id: string;
  title?: string;
  [k: string]: unknown;
}

interface KbDocFull {
  doc_id: string;
  title?: string;
  content?: string;
  metadata?: unknown;
  [k: string]: unknown;
}

interface UserDataSourceSummary {
  id: string;
  pack_name: string;
  rule_name: string;
  dataset_name: string;
  origin?: string;
  [k: string]: unknown;
}

interface UserDataSourceFull {
  ok: boolean;
  data_source: UserDataSourceSummary;
  doc: Record<string, unknown>;
}

interface InstalledDataSourceRow {
  pack_name: string;
  rule_name: string;
  dataset_name: string;
  [k: string]: unknown;
}

const parseToolResult = <T,>(result: {
  content: Array<{ text: string }>;
}): T => {
  const raw = result.content?.[0]?.text || "{}";
  return JSON.parse(raw) as T;
};

export async function GET() {
  // Auth: enforced upstream by middleware.ts. This response contains every
  // connector secret in CLEARTEXT, so the gate before this handler is the
  // only thing protecting them.
  //
  // The gate is complete only because "/api/agent/backup" is listed in
  // CREDENTIAL_PREFIXES (lib/agent-scopes.ts). Middleware also admits
  // API-key callers, so without that prefix any agent:read key could GET
  // the zip and read every stored credential. The path does not look
  // credential-shaped, but the DATA is.
  //
  // Note the flag is hardcoded below rather than taken from the caller, so
  // stripping include_secrets at the proxy does NOT cover this route. It
  // needs the prefix gate.

  const resolved = await _resolveMcp();
  if (resolved instanceof NextResponse) return resolved;

  // Bind to a narrowed const so the closures below don't trip the
  // TypeScript "could be NextResponse" union check on every reference.
  const mcp: McpResolved = resolved;
  const auth = { Authorization: `Bearer ${mcp.token}` };
  const mcpClient = new PhantomMCPClient(mcp.streamUrl, mcp.token);

  /** Fetch a /api/v1/* JSON resource with bearer auth. */
  async function mcpJson<T = unknown>(path: string): Promise<T> {
    const resp = await fetch(`${mcp.base}${path}`, {
      headers: auth,
      signal: AbortSignal.timeout(15000),
    });
    if (!resp.ok) {
      throw new Error(`MCP ${path} returned HTTP ${resp.status}`);
    }
    return (await resp.json()) as T;
  }

  const warnings: string[] = [];
  const sectionCounts: Record<string, number> = {};

  try {
    const zip = new JSZip();

    // ── Section 1: Personality (single-row blob) ─────────────────────
    try {
      const personality = await mcpJson<unknown>("/api/v1/personality");
      zip.file("personality.json", JSON.stringify(personality, null, 2));
      sectionCounts.personality = 1;
    } catch (e) {
      warnings.push(
        `personality skipped: ${e instanceof Error ? e.message : String(e)}`,
      );
      sectionCounts.personality = 0;
    }

    // ── Section 2: Instances + cleartext secrets ─────────────────────
    // ?include_secrets=true is the backup flag on the MCP
    // side. Defaults to redacted everywhere else.
    try {
      const instances = await mcpJson<{ instances?: unknown[] }>(
        "/api/v1/instances?include_secrets=true",
      );
      zip.file("instances.json", JSON.stringify(instances, null, 2));
      sectionCounts.instances = instances.instances?.length ?? 0;
    } catch (e) {
      warnings.push(
        `instances skipped: ${e instanceof Error ? e.message : String(e)}`,
      );
      sectionCounts.instances = 0;
    }

    // ── Section 3: Memory (embeddings stripped) ──────────────────────
    try {
      const memory = await mcpJson<{ memories?: MemoryEntry[] }>(
        "/api/v1/memories",
      );
      const cleaned = {
        ...memory,
        memories: (memory.memories ?? []).map((m) => {
          const { embedding: _embedding, ...rest } = m;
          return rest;
        }),
      };
      zip.file("memory.json", JSON.stringify(cleaned, null, 2));
      sectionCounts.memory = cleaned.memories.length;
    } catch (e) {
      warnings.push(
        `memory skipped: ${e instanceof Error ? e.message : String(e)}`,
      );
      sectionCounts.memory = 0;
    }

    // ── Section 4: Jobs (runtime only) ───────────────────────────────
    try {
      const jobs = await mcpJson<{ jobs?: JobEntry[] }>("/api/v1/jobs");
      const filtered = {
        ...jobs,
        jobs: (jobs.jobs ?? []).filter((j) => j.source === "runtime"),
      };
      zip.file("jobs.json", JSON.stringify(filtered, null, 2));
      sectionCounts.jobs = filtered.jobs.length;
    } catch (e) {
      warnings.push(
        `jobs skipped: ${e instanceof Error ? e.message : String(e)}`,
      );
      sectionCounts.jobs = 0;
    }

    // ── Section 5: Skills (MD tree, preserves category subdir) ───────
    try {
      const listResult = await mcpClient.callTool("skills_list_all", {});
      const listed = parseToolResult<SkillListItem[]>(listResult);
      let count = 0;
      for (const s of listed) {
        try {
          const readResult = await mcpClient.callTool("skills_read", {
            file_path: s.file_path,
          });
          const parsed = parseToolResult<{
            success?: boolean;
            content?: string;
          }>(readResult);
          if (parsed.success && typeof parsed.content === "string") {
            zip.file(`skills/${s.file_path}`, parsed.content);
            count += 1;
          }
        } catch (e) {
          warnings.push(
            `skill ${s.file_path} skipped: ${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
      }
      sectionCounts.skills = count;
    } catch (e) {
      warnings.push(
        `skills section skipped: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      sectionCounts.skills = 0;
    }

    // ── Section 6: Knowledge bundles (source MDs by KB name) ─────────
    // The kb.db is a derived cache rebuilt at boot from /app/bundle/kbs/
    // source files. We export the doc content (which is what the MCP
    // exposes) so the zip is a complete reference snapshot. On restore
    // the destination compares against its image-baked KB; mismatches
    // are surfaced as warnings rather than written (the bundle path
    // is read-only).
    try {
      const kbs = await mcpJson<{ kbs?: KbSummary[] }>("/api/v1/kbs");
      let count = 0;
      for (const kb of kbs.kbs ?? []) {
        try {
          const docs = await mcpJson<{ docs?: KbDocStub[] }>(
            `/api/v1/kbs/${encodeURIComponent(kb.name)}/docs`,
          );
          for (const d of docs.docs ?? []) {
            try {
              const full = await mcpJson<KbDocFull>(
                `/api/v1/kbs/${encodeURIComponent(
                  kb.name,
                )}/docs/${encodeURIComponent(d.doc_id)}`,
              );
              if (typeof full.content === "string") {
                const safeId = d.doc_id.replace(/[/\\]/g, "_");
                zip.file(
                  `knowledge/${kb.name}/${safeId}.md`,
                  full.content,
                );
                count += 1;
              }
            } catch (e) {
              warnings.push(
                `kb doc ${kb.name}/${d.doc_id} skipped: ${
                  e instanceof Error ? e.message : String(e)
                }`,
              );
            }
          }
        } catch (e) {
          warnings.push(
            `kb ${kb.name} skipped: ${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
      }
      sectionCounts.knowledge = count;
    } catch (e) {
      warnings.push(
        `knowledge section skipped: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      sectionCounts.knowledge = 0;
    }

    // ── Section 7: Data sources — user uploads + install set ─
    // Bundle YAMLs are part of the destination image; only user uploads
    // need to travel. The install set (which packs are in data_sources.db)
    // is captured as 3-tuples for re-install on the destination.
    try {
      // User-uploaded YAMLs (origin=user)
      const userList = await mcpJson<{ data_sources?: UserDataSourceSummary[] }>(
        "/api/v1/data-sources/user",
      );
      let userCount = 0;
      for (const ds of userList.data_sources ?? []) {
        try {
          const full = await mcpJson<UserDataSourceFull>(
            `/api/v1/data-sources/user/${encodeURIComponent(ds.id)}`,
          );
          if (full.doc) {
            const safeId = ds.id.replace(/[/\\]/g, "_");
            zip.file(
              `data_sources/user/${safeId}.json`,
              JSON.stringify(full.doc, null, 2),
            );
            userCount += 1;
          }
        } catch (e) {
          warnings.push(
            `user data source ${ds.id} skipped: ${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
      }
      sectionCounts.data_sources_user = userCount;

      // Install set — 3-tuples for re-install on restore
      const installed = await mcpJson<{
        data_sources?: InstalledDataSourceRow[];
      }>("/api/v1/data-sources");
      const installSet = (installed.data_sources ?? []).map((r) => ({
        pack_name: r.pack_name,
        rule_name: r.rule_name,
        dataset_name: r.dataset_name,
      }));
      zip.file(
        "data_sources/installed.json",
        JSON.stringify(
          {
            count: installSet.length,
            packs: installSet,
            note:
              "Restore re-runs POST /api/v1/data-sources/install for " +
              "each entry. Idempotent: already-installed packs are " +
              "skipped via the store's upsert semantics.",
          },
          null,
          2,
        ),
      );
      sectionCounts.data_sources_installed = installSet.length;
    } catch (e) {
      warnings.push(
        `data_sources section skipped: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      sectionCounts.data_sources_user = 0;
      sectionCounts.data_sources_installed = 0;
    }

    // ── Section 8: Operator workflow state ───────────────────────────
    // operator_state.db: tested-journey marks, metric bookmarks, ... Every
    // key travels so the operator's progress follows them to a new install.
    try {
      const state = buildOperatorStateSection(
        await mcpJson<unknown>("/api/v1/operator-state"),
      );
      zip.file(OPERATOR_STATE_FILE, JSON.stringify(state, null, 2));
      sectionCounts.operator_state = state.count;
    } catch (e) {
      warnings.push(
        `operator_state skipped: ${e instanceof Error ? e.message : String(e)}`,
      );
      sectionCounts.operator_state = 0;
    }

    // ── Manifest (last so section_counts is fully populated) ─────────
    const manifest = {
      schema_version: SCHEMA_VERSION,
      phantom_version:
        process.env.PHANTOM_VERSION ||
        process.env.NEXT_PUBLIC_PHANTOM_VERSION ||
        "unknown",
      created_at: new Date().toISOString(),
      sections: [
        "personality",
        "instances",
        "memory",
        "jobs",
        "skills",
        "knowledge",
        "data_sources",
        "operator_state",
      ],
      section_counts: sectionCounts,
      warning:
        "This zip contains cleartext secrets (connector API keys, " +
        "webhook keys, etc). Treat as sensitive. Do not commit to " +
        "version control or share over unencrypted channels.",
      restore_order: [
        "personality",
        "instances",
        "skills",
        "memory",
        "knowledge",
        "data_sources",
        "operator_state",
        "jobs",
      ],
      restore_notes: [
        "Memory entries are restored without embeddings; the " +
          "destination re-embeds on next semantic search.",
        "Knowledge bundles are read-only at runtime; the restore " +
          "compares against the destination image without writing.",
        "Manifest jobs (source=manifest) are not exported — they " +
          "reseed from manifest.yaml at boot.",
        "Data sources: only user-uploaded YAMLs (origin=user) are " +
          "exported. Bundle YAMLs re-arrive in the destination's " +
          "image. The install set is exported as 3-tuples; restore " +
          "re-runs the install endpoint per row.",
        "Operator state (tested-journey marks, metric bookmarks) is " +
          "exported key by key; restore keeps a key the destination " +
          "already holds unless overwrite is chosen.",
      ],
      ...(warnings.length ? { backup_warnings: warnings } : {}),
    };
    zip.file("manifest.json", JSON.stringify(manifest, null, 2));

    // Generate as ArrayBuffer directly — NextResponse's BodyInit
    // accepts ArrayBuffer (BufferSource) without the "missing
    // URLSearchParams properties" TS noise that Uint8Array trips.
    const bytes = await zip.generateAsync({ type: "arraybuffer" });

    const stamp = new Date()
      .toISOString()
      .slice(0, 19)
      .replace(/[:.]/g, "-");
    const filename = `phantom-backup-${stamp}.zip`;

    return new NextResponse(bytes, {
      status: 200,
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
        "X-Phantom-Backup-Schema": String(SCHEMA_VERSION),
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "backup failed" },
      { status: 500 },
    );
  }
}
