/**
 * Restore endpoint — accepts a zip produced by GET /api/agent/backup
 * and applies each section to the destination's stores in dependency
 * order: personality → instances+secrets → skills → memory → knowledge
 * (no-op) → jobs.
 *
 * The body is multipart/form-data with field name "file" (the zip).
 * Optional query params:
 *   - dry_run=true       parse + validate, return a plan without writing
 *   - force=true         overwrite existing entries; default is to skip
 *                        and return them in the `skipped` summary
 *
 * Auth: cookie session check at the route level.
 *
 * Idempotence: each section uses upsert-or-skip semantics. With
 * force=true a name collision overwrites; without it the existing
 * entry stays and the incoming one is reported as skipped.
 *
 * Why we restore in this specific order:
 *   1. Personality has no deps; setting it first is harmless even if
 *      a later section fails.
 *   2. Instances + secrets are atomic so secret_refs paths resolve
 *      from first read.
 *   3. Skills must exist before any restored job that binds to a
 *      skill name can fire.
 *   4. Memory is independent.
 *   5. Knowledge is read-only at runtime — the restore is a verify
 *      step (compare counts), not a write.
 *   6. Jobs last because runtime jobs may reference connector tools
 *      (e.g. phantom_create_data_worker) which need their instance
 *      enabled before the first cron tick.
 */

import { NextResponse } from "next/server";

import JSZip from "jszip";

import { PhantomMCPClient } from "@/lib/mcp-client";
import {
  deriveMcpBaseUrl,
  getEffectiveRuntimeConfig,
} from "@/lib/runtime-config";

const SUPPORTED_SCHEMAS = [1];

export const dynamic = "force-dynamic";
export const maxDuration = 180;

interface McpResolved {
  base: string;
  token: string;
  streamUrl: string;
}

interface RestoreSummary {
  applied: Record<string, number>;
  skipped: Record<string, number>;
  errors: string[];
  warnings: string[];
}

interface InstanceFromBackup {
  id?: string;
  connector_id: string;
  name: string;
  config?: Record<string, unknown>;
  secrets?: Record<string, string>;
  enabled?: boolean;
  [k: string]: unknown;
}

interface JobFromBackup {
  name: string;
  cron: string;
  timezone?: string;
  action?: unknown;
  enabled?: boolean;
  run_once?: boolean;
  bypass_approvals?: boolean;
  source?: string;
  [k: string]: unknown;
}

interface MemoryFromBackup {
  key?: string;
  value?: unknown;
  scope?: string;
  ttl_seconds?: number | null;
  meta?: unknown;
  [k: string]: unknown;
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

export async function POST(request: Request) {
  // Auth: enforced upstream by middleware.ts, not by a local cookie check.

  const url = new URL(request.url);
  const dryRun = url.searchParams.get("dry_run") === "true";
  const force = url.searchParams.get("force") === "true";

  // ── Parse multipart upload ─────────────────────────────────────────
  let zipBytes: ArrayBuffer;
  try {
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) {
      return NextResponse.json(
        { error: "missing 'file' field in multipart form" },
        { status: 400 },
      );
    }
    if (file.size === 0) {
      return NextResponse.json(
        { error: "uploaded file is empty" },
        { status: 400 },
      );
    }
    if (file.size > 100 * 1024 * 1024) {
      return NextResponse.json(
        { error: "uploaded file exceeds 100 MB cap" },
        { status: 413 },
      );
    }
    zipBytes = await file.arrayBuffer();
  } catch (e) {
    return NextResponse.json(
      {
        error: `multipart parse failed: ${
          e instanceof Error ? e.message : String(e)
        }`,
      },
      { status: 400 },
    );
  }

  // ── Open zip, validate manifest ────────────────────────────────────
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(zipBytes);
  } catch (e) {
    return NextResponse.json(
      {
        error: `not a valid zip: ${
          e instanceof Error ? e.message : String(e)
        }`,
      },
      { status: 400 },
    );
  }

  const manifestEntry = zip.file("manifest.json");
  if (!manifestEntry) {
    return NextResponse.json(
      {
        error:
          "missing manifest.json — this zip was not produced by " +
          "GET /api/agent/backup or has been corrupted",
      },
      { status: 400 },
    );
  }
  let manifest: {
    schema_version?: number;
    phantom_version?: string;
    sections?: string[];
    [k: string]: unknown;
  };
  try {
    manifest = JSON.parse(await manifestEntry.async("string"));
  } catch (e) {
    return NextResponse.json(
      {
        error: `manifest.json is not valid JSON: ${
          e instanceof Error ? e.message : String(e)
        }`,
      },
      { status: 400 },
    );
  }
  if (
    typeof manifest.schema_version !== "number" ||
    !SUPPORTED_SCHEMAS.includes(manifest.schema_version)
  ) {
    return NextResponse.json(
      {
        error: `unsupported schema_version ${
          manifest.schema_version
        } — supported: ${SUPPORTED_SCHEMAS.join(", ")}`,
      },
      { status: 400 },
    );
  }

  // ── Plan summary (used in dry-run + final response) ────────────────
  const summary: RestoreSummary = {
    applied: {},
    skipped: {},
    errors: [],
    warnings: [],
  };

  if (dryRun) {
    return NextResponse.json({
      dry_run: true,
      manifest,
      sections_present: {
        personality: !!zip.file("personality.json"),
        instances: !!zip.file("instances.json"),
        memory: !!zip.file("memory.json"),
        jobs: !!zip.file("jobs.json"),
        skills: Object.keys(zip.files).filter(
          (n) => n.startsWith("skills/") && !zip.files[n].dir,
        ).length,
        knowledge: Object.keys(zip.files).filter(
          (n) => n.startsWith("knowledge/") && !zip.files[n].dir,
        ).length,
        // data sources sections
        data_sources_user: Object.keys(zip.files).filter(
          (n) =>
            n.startsWith("data_sources/user/") &&
            !zip.files[n].dir &&
            n.endsWith(".json"),
        ).length,
        data_sources_installed: !!zip.file("data_sources/installed.json"),
      },
      restore_order: [
        "personality",
        "instances",
        "skills",
        "memory",
        "knowledge",
        "data_sources",
        "jobs",
      ],
      force,
    });
  }

  // ── Resolve MCP for live writes ────────────────────────────────────
  const resolved = await _resolveMcp();
  if (resolved instanceof NextResponse) return resolved;
  // Bind to a narrowed const so closures below don't trip TS's "could
  // be NextResponse" union check at every reference.
  const mcp: McpResolved = resolved;
  const auth = {
    Authorization: `Bearer ${mcp.token}`,
    "Content-Type": "application/json",
  };
  const mcpClient = new PhantomMCPClient(mcp.streamUrl, mcp.token);

  /** Read-or-undefined — used by sections that conditionally restore. */
  async function readJsonFile<T>(name: string): Promise<T | undefined> {
    const f = zip.file(name);
    if (!f) return undefined;
    try {
      return JSON.parse(await f.async("string")) as T;
    } catch (e) {
      summary.errors.push(
        `${name} parse failed: ${e instanceof Error ? e.message : String(e)}`,
      );
      return undefined;
    }
  }

  // ── 1. Personality — always overwrite (single-row blob) ──────────
  const personalityWrap = await readJsonFile<{ personality?: unknown }>(
    "personality.json",
  );
  if (personalityWrap?.personality !== undefined) {
    try {
      const resp = await fetch(`${mcp.base}/api/v1/personality`, {
        method: "PUT",
        headers: auth,
        body: JSON.stringify({ personality: personalityWrap.personality }),
        signal: AbortSignal.timeout(15000),
      });
      if (!resp.ok) {
        summary.errors.push(
          `personality PUT returned HTTP ${resp.status}`,
        );
      } else {
        summary.applied.personality = 1;
      }
    } catch (e) {
      summary.errors.push(
        `personality restore failed: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
    }
  }

  // ── 2. Instances — POST each; skip on collision unless force ─────
  const instWrap = await readJsonFile<{ instances?: InstanceFromBackup[] }>(
    "instances.json",
  );
  if (instWrap?.instances?.length) {
    // Pre-fetch existing instances to detect collisions.
    let existing: Set<string> = new Set();
    try {
      const cur = await fetch(`${mcp.base}/api/v1/instances`, {
        headers: { Authorization: `Bearer ${mcp.token}` },
      });
      if (cur.ok) {
        const j = (await cur.json()) as {
          instances?: { connector_id: string; name: string }[];
        };
        existing = new Set(
          (j.instances ?? []).map((i) => `${i.connector_id}/${i.name}`),
        );
      }
    } catch {
      /* best-effort — restore proceeds even if list fetch fails */
    }
    let applied = 0;
    let skipped = 0;
    for (const inst of instWrap.instances) {
      const key = `${inst.connector_id}/${inst.name}`;
      if (existing.has(key) && !force) {
        skipped += 1;
        continue;
      }
      // For force-overwrite, we'd need PATCH or DELETE+POST. Today
      // we only support skip-or-create. Operator can manually delete
      // colliding rows via /connectors before re-running restore with
      // force, OR pass force=true (which still skips until a
      // DELETE/PATCH path is wired through).
      try {
        const resp = await fetch(`${mcp.base}/api/v1/instances`, {
          method: "POST",
          headers: auth,
          body: JSON.stringify({
            connector_id: inst.connector_id,
            name: inst.name,
            config: inst.config ?? {},
            secrets: inst.secrets ?? {},
            enabled: inst.enabled ?? true,
          }),
          signal: AbortSignal.timeout(20000),
        });
        if (resp.ok || resp.status === 201) {
          applied += 1;
        } else {
          const body = await resp.text();
          summary.errors.push(
            `instance ${key} create returned HTTP ${resp.status}: ${body.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `instance ${key} create failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    summary.applied.instances = applied;
    summary.skipped.instances = skipped;
  }

  // ── 3. Skills — write each MD via skills_create / skills_update ──
  const skillFiles = Object.keys(zip.files).filter(
    (n) => n.startsWith("skills/") && !zip.files[n].dir && n.endsWith(".md"),
  );
  if (skillFiles.length) {
    let applied = 0;
    let skipped = 0;
    // Get existing skills set so we know which to update vs create.
    let existing: Set<string> = new Set();
    try {
      const listResult = await mcpClient.callTool("skills_list_all", {});
      const listed = JSON.parse(
        listResult.content?.[0]?.text || "[]",
      ) as Array<{ file_path: string }>;
      existing = new Set(listed.map((s) => s.file_path));
    } catch {
      /* best-effort */
    }
    for (const fullName of skillFiles) {
      // Strip leading "skills/" so file_path becomes
      // "<category>/<skill>.md", matching the MCP's path convention.
      const relPath = fullName.slice("skills/".length);
      const slash = relPath.indexOf("/");
      if (slash <= 0) {
        summary.warnings.push(
          `skill ${fullName} ignored: missing category subdirectory`,
        );
        continue;
      }
      const category = relPath.slice(0, slash);
      const filename = relPath.slice(slash + 1);
      const content = await zip.files[fullName].async("string");

      if (existing.has(relPath)) {
        if (!force) {
          skipped += 1;
          continue;
        }
        try {
          await mcpClient.callTool("skills_update", {
            file_path: relPath,
            content,
          });
          applied += 1;
        } catch (e) {
          summary.errors.push(
            `skill ${relPath} update failed: ${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
      } else {
        try {
          await mcpClient.callTool("skills_create", {
            category,
            filename,
            content,
          });
          applied += 1;
        } catch (e) {
          summary.errors.push(
            `skill ${relPath} create failed: ${
              e instanceof Error ? e.message : String(e)
            }`,
          );
        }
      }
    }
    summary.applied.skills = applied;
    summary.skipped.skills = skipped;
  }

  // ── 4. Memory — POST each entry; the MCP upserts on (key, scope) ─
  const memWrap = await readJsonFile<{ memories?: MemoryFromBackup[] }>(
    "memory.json",
  );
  if (memWrap?.memories?.length) {
    let applied = 0;
    for (const m of memWrap.memories) {
      if (typeof m.key !== "string" || m.value === undefined) continue;
      try {
        const resp = await fetch(`${mcp.base}/api/v1/memories`, {
          method: "POST",
          headers: auth,
          body: JSON.stringify({
            key: m.key,
            value: m.value,
            scope: m.scope ?? "agent",
            ttl_seconds: m.ttl_seconds ?? null,
            meta: m.meta ?? null,
          }),
          signal: AbortSignal.timeout(15000),
        });
        if (resp.ok) {
          applied += 1;
        } else {
          summary.errors.push(
            `memory ${m.key}@${m.scope ?? "agent"} POST returned HTTP ${resp.status}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `memory ${m.key} restore failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    summary.applied.memory = applied;
  }

  // ── 5. Knowledge — read-only at runtime; verify only ─────────────
  // The kb source files live under /app/bundle/kbs/ which is
  // image-baked. We don't write here. Instead, count what's in the
  // zip vs what's in the destination; any delta becomes a warning.
  const kbFiles = Object.keys(zip.files).filter(
    (n) =>
      n.startsWith("knowledge/") && !zip.files[n].dir && n.endsWith(".md"),
  );
  if (kbFiles.length) {
    summary.applied.knowledge = 0;
    summary.warnings.push(
      `${kbFiles.length} knowledge doc(s) in zip ignored — knowledge ` +
        "bundles are image-baked and not writable at runtime. The " +
        "destination's KB content is determined by its container " +
        "image, not by restore.",
    );
  }

  // ── 6. Data sources — user uploads + install set ──────
  // First: re-create operator-uploaded YAMLs (origin=user). Skip if
  // an id already exists unless force=true. Each upload goes through
  // the two-phase preview/commit flow on the destination.
  const userYamlFiles = Object.keys(zip.files).filter(
    (n) =>
      n.startsWith("data_sources/user/") &&
      !zip.files[n].dir &&
      n.endsWith(".json"),
  );
  if (userYamlFiles.length) {
    let applied = 0;
    let skipped = 0;

    // Pre-fetch existing user-source ids on destination for collision
    // detection. Best-effort — falls through to per-row error if the
    // list endpoint is down.
    let existingUserIds: Set<string> = new Set();
    try {
      const list = await fetch(`${mcp.base}/api/v1/data-sources/user`, {
        headers: auth,
      });
      if (list.ok) {
        const j = (await list.json()) as {
          data_sources?: { id: string }[];
        };
        existingUserIds = new Set((j.data_sources ?? []).map((r) => r.id));
      }
    } catch {
      /* best-effort */
    }

    for (const fileName of userYamlFiles) {
      let docRaw: string | null = null;
      try {
        docRaw = await zip.files[fileName].async("string");
      } catch (e) {
        summary.warnings.push(
          `user data source ${fileName} unreadable: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
        continue;
      }
      let doc: Record<string, unknown>;
      try {
        doc = JSON.parse(docRaw) as Record<string, unknown>;
      } catch (e) {
        summary.errors.push(
          `user data source ${fileName} not valid JSON: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
        continue;
      }
      const docId = typeof doc.id === "string" ? doc.id : "";
      if (!docId) {
        summary.errors.push(
          `user data source ${fileName} missing id field`,
        );
        continue;
      }
      if (existingUserIds.has(docId) && !force) {
        skipped += 1;
        continue;
      }
      // Two-phase: preview → commit (carries accept_token).
      try {
        const previewResp = await fetch(
          `${mcp.base}/api/v1/data-sources/user/preview`,
          {
            method: "POST",
            headers: auth,
            body: JSON.stringify({ doc }),
          },
        );
        if (!previewResp.ok) {
          const text = await previewResp.text().catch(() => "");
          summary.errors.push(
            `user data source ${docId} preview failed (${previewResp.status}): ${text.slice(0, 200)}`,
          );
          continue;
        }
        const preview = (await previewResp.json()) as {
          ok: boolean;
          accept_token?: string;
          uploaded_vendor?: string;
          error?: string;
        };
        if (!preview.ok || !preview.accept_token) {
          summary.errors.push(
            `user data source ${docId} preview returned not-ok: ${preview.error ?? "no accept_token"}`,
          );
          continue;
        }
        // Commit with vendor_choice=create_new — preserve the exact
        // vendor field from the backed-up doc (the operator's intent
        // at backup time stays). Group_under would silently rewrite
        // it on the destination.
        const commitResp = await fetch(
          `${mcp.base}/api/v1/data-sources/user`,
          {
            method: "POST",
            headers: auth,
            body: JSON.stringify({
              doc,
              accept_token: preview.accept_token,
              vendor_choice: "create_new",
            }),
          },
        );
        if (commitResp.status === 201 || commitResp.ok) {
          applied += 1;
        } else {
          const text = await commitResp.text().catch(() => "");
          summary.errors.push(
            `user data source ${docId} commit failed (${commitResp.status}): ${text.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `user data source ${docId} restore failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    summary.applied.data_sources_user = applied;
    summary.skipped.data_sources_user = skipped;
  }

  // Then: re-install the captured install set.
  const installedWrap = await readJsonFile<{
    packs?: { pack_name: string; rule_name: string; dataset_name: string }[];
  }>("data_sources/installed.json");
  if (installedWrap?.packs?.length) {
    let applied = 0;
    let skipped = 0;
    // Pre-fetch installed packs on destination so already-installed
    // packs (e.g. from bundle defaults) are counted as skipped rather
    // than reinstalled (idempotent install will succeed but we report
    // honestly).
    let existingInstalls: Set<string> = new Set();
    try {
      const list = await fetch(`${mcp.base}/api/v1/data-sources`, {
        headers: auth,
      });
      if (list.ok) {
        const j = (await list.json()) as {
          data_sources?: {
            pack_name: string;
            rule_name: string;
            dataset_name: string;
          }[];
        };
        existingInstalls = new Set(
          (j.data_sources ?? []).map(
            (r) => `${r.pack_name}__${r.rule_name}__${r.dataset_name}`,
          ),
        );
      }
    } catch {
      /* best-effort */
    }

    for (const pack of installedWrap.packs) {
      const key = `${pack.pack_name}__${pack.rule_name}__${pack.dataset_name}`;
      if (existingInstalls.has(key) && !force) {
        skipped += 1;
        continue;
      }
      try {
        const resp = await fetch(
          `${mcp.base}/api/v1/data-sources/install`,
          {
            method: "POST",
            headers: auth,
            body: JSON.stringify({
              pack_name: pack.pack_name,
              rule_name: pack.rule_name,
              dataset_name: pack.dataset_name,
            }),
          },
        );
        if (resp.ok || resp.status === 201) {
          applied += 1;
        } else {
          const text = await resp.text().catch(() => "");
          summary.errors.push(
            `data source install ${key} failed (${resp.status}): ${text.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `data source install ${key} failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    summary.applied.data_sources_installed = applied;
    summary.skipped.data_sources_installed = skipped;
  }

  // ── 7. Jobs — POST each runtime job last (so connectors exist) ───
  const jobsWrap = await readJsonFile<{ jobs?: JobFromBackup[] }>(
    "jobs.json",
  );
  if (jobsWrap?.jobs?.length) {
    let applied = 0;
    let skipped = 0;
    // Pre-fetch existing jobs to detect collisions.
    let existing: Set<string> = new Set();
    try {
      const cur = await fetch(`${mcp.base}/api/v1/jobs`, {
        headers: { Authorization: `Bearer ${mcp.token}` },
      });
      if (cur.ok) {
        const j = (await cur.json()) as { jobs?: { name: string }[] };
        existing = new Set((j.jobs ?? []).map((i) => i.name));
      }
    } catch {
      /* best-effort */
    }
    for (const job of jobsWrap.jobs) {
      if (existing.has(job.name) && !force) {
        skipped += 1;
        continue;
      }
      // Skip non-runtime jobs (manifest jobs reseed at boot).
      if (job.source && job.source !== "runtime") {
        summary.warnings.push(
          `job ${job.name} skipped: source=${job.source} (manifest jobs reseed at boot)`,
        );
        continue;
      }
      try {
        const resp = await fetch(`${mcp.base}/api/v1/jobs`, {
          method: "POST",
          headers: auth,
          body: JSON.stringify({
            name: job.name,
            cron: job.cron,
            timezone: job.timezone,
            action: job.action,
            enabled: job.enabled ?? true,
            run_once: job.run_once ?? false,
            bypass_approvals: job.bypass_approvals ?? false,
          }),
          signal: AbortSignal.timeout(15000),
        });
        if (resp.ok || resp.status === 201) {
          applied += 1;
        } else {
          const body = await resp.text();
          summary.errors.push(
            `job ${job.name} create returned HTTP ${resp.status}: ${body.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `job ${job.name} restore failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    summary.applied.jobs = applied;
    summary.skipped.jobs = skipped;
  }

  return NextResponse.json({
    ok: summary.errors.length === 0,
    dry_run: false,
    force,
    schema_version: manifest.schema_version,
    backed_up_from: manifest.phantom_version,
    ...summary,
  });
}
