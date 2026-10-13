/**
 * Restore endpoint — accepts a zip produced by GET /api/agent/backup
 * and applies each section to the destination's stores in dependency
 * order: personality → instances+secrets → skills → memory → knowledge
 * (no-op) → data sources → operator state → hooks → jobs.
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
 * Existing-entry lookup: a section that skips collisions first lists what
 * the destination holds. If that listing fails, the destination is NOT
 * treated as empty: without force the section is skipped with a warning
 * (see lib/restore-existing.ts); with force it is written anyway.
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
 *   5b. Operator state (tested-journey marks, metric bookmarks) is
 *      independent key-value data, written key by key.
 *   5c. Hooks (Settings -> Hooks) are operator configuration; a hook
 *      with the same id on the destination is kept unless force. Secret
 *      values are not in the zip (lib/hooks-backup.ts), so a hook that
 *      lost any is written disabled, with a warning naming the fields.
 *      They come before jobs so a policy hook is in place before a
 *      restored job can fire tool calls.
 *   6. Jobs last because runtime jobs may reference connector tools
 *      (e.g. phantom_create_data_worker) which need their instance
 *      enabled before the first cron tick.
 */

import { NextResponse } from "next/server";

import JSZip from "jszip";

import { getBuiltinHook } from "@/lib/hook-builtins";
import { HOOKS_FILE, planHooksRestore } from "@/lib/hooks-backup";
import { validateHook } from "@/lib/hooks";
import { PhantomMCPClient } from "@/lib/mcp-client";
import {
  OPERATOR_STATE_FILE,
  planOperatorStateRestore,
} from "@/lib/operator-state-backup";
import {
  guardSection,
  keysFromList,
  lookupExistingKeys,
} from "@/lib/restore-existing";
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

/** How many entries operator_state.json holds (for the skipped count). */
function operatorStateEntryCount(file: unknown): number {
  const entries =
    file !== null && typeof file === "object"
      ? (file as { entries?: unknown }).entries
      : undefined;
  return Array.isArray(entries) ? entries.length : 0;
}

/** How many hooks hooks.json holds (for the skipped count). */
function hooksEntryCount(file: unknown): number {
  const hooks =
    file !== null && typeof file === "object"
      ? (file as { hooks?: unknown }).hooks
      : undefined;
  return Array.isArray(hooks) ? hooks.length : 0;
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
        operator_state: !!zip.file(OPERATOR_STATE_FILE),
        hooks: !!zip.file(HOOKS_FILE),
      },
      restore_order: [
        "personality",
        "instances",
        "skills",
        "memory",
        "knowledge",
        "data_sources",
        "operator_state",
        "hooks",
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

  /** GET a JSON list from the MCP; throws on a non-OK answer. */
  async function getJson(path: string): Promise<unknown> {
    const resp = await fetch(`${mcp.base}${path}`, {
      headers: { Authorization: `Bearer ${mcp.token}` },
      // Generous: a timeout here skips the section, so a slow but healthy
      // listing should not be mistaken for a failed one.
      signal: AbortSignal.timeout(30000),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  /**
   * The keys the destination already holds for a section, or null when they
   * could not be listed and the section must be skipped (a warning and the
   * skipped count are recorded here). See lib/restore-existing.ts.
   */
  async function existingOrSkip(
    label: string,
    summaryKey: string,
    incoming: number,
    fetchBody: () => Promise<unknown>,
    keysOf: (body: unknown) => string[] | null,
  ): Promise<Set<string> | null> {
    const guard = guardSection(
      await lookupExistingKeys(fetchBody, keysOf),
      force,
      label,
      incoming,
    );
    if (!guard.proceed) {
      if (guard.warning) summary.warnings.push(guard.warning);
      summary.applied[summaryKey] = 0;
      summary.skipped[summaryKey] = incoming;
      return null;
    }
    return guard.existing;
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
  // Pre-fetch existing instances to detect collisions.
  const existingInstances = instWrap?.instances?.length
    ? await existingOrSkip(
        "instances",
        "instances",
        instWrap.instances.length,
        () => getJson("/api/v1/instances"),
        (b) =>
          keysFromList(b, "instances", (i) =>
            typeof i.connector_id === "string" && typeof i.name === "string"
              ? `${i.connector_id}/${i.name}`
              : null,
          ),
      )
    : null;
  if (instWrap?.instances?.length && existingInstances) {
    const existing = existingInstances;
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
  // Get existing skills set so we know which to update vs create.
  const existingSkills = skillFiles.length
    ? await existingOrSkip(
        "skills",
        "skills",
        skillFiles.length,
        async () => {
          const listResult = await mcpClient.callTool("skills_list_all", {});
          const text = listResult.content?.[0]?.text;
          if (typeof text !== "string") throw new Error("empty tool result");
          return JSON.parse(text) as unknown;
        },
        (b) =>
          keysFromList(b, null, (s) =>
            typeof s.file_path === "string" ? s.file_path : null,
          ),
      )
    : null;
  if (skillFiles.length && existingSkills) {
    const existing = existingSkills;
    let applied = 0;
    let skipped = 0;
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
  // Pre-fetch existing user-source ids on destination for collision
  // detection. If the list is unavailable the section is skipped (see
  // existingOrSkip), not written over what may be there.
  const existingUserIds = userYamlFiles.length
    ? await existingOrSkip(
        "user data sources",
        "data_sources_user",
        userYamlFiles.length,
        () => getJson("/api/v1/data-sources/user"),
        (b) =>
          keysFromList(b, "data_sources", (r) =>
            typeof r.id === "string" ? r.id : null,
          ),
      )
    : null;
  if (userYamlFiles.length && existingUserIds) {
    let applied = 0;
    let skipped = 0;

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
  // Pre-fetch installed packs on destination so already-installed
  // packs (e.g. from bundle defaults) are counted as skipped rather
  // than reinstalled (idempotent install will succeed but we report
  // honestly).
  const existingInstalls = installedWrap?.packs?.length
    ? await existingOrSkip(
        "installed data sources",
        "data_sources_installed",
        installedWrap.packs.length,
        () => getJson("/api/v1/data-sources"),
        (b) =>
          keysFromList(b, "data_sources", (r) =>
            typeof r.pack_name === "string" &&
            typeof r.rule_name === "string" &&
            typeof r.dataset_name === "string"
              ? `${r.pack_name}__${r.rule_name}__${r.dataset_name}`
              : null,
          ),
      )
    : null;
  if (installedWrap?.packs?.length && existingInstalls) {
    let applied = 0;
    let skipped = 0;

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

  // ── 6b. Operator state — PUT each key; keep the destination's own
  //        unless force (same rule as the other sections) ───────────
  const stateFile = await readJsonFile<unknown>(OPERATOR_STATE_FILE);
  // Skipped as a whole when the destination's keys cannot be listed.
  const existingStateKeys =
    stateFile !== undefined
      ? await existingOrSkip(
          "operator state",
          "operator_state",
          operatorStateEntryCount(stateFile),
          () => getJson("/api/v1/operator-state"),
          (b) =>
            keysFromList(b, "entries", (e) =>
              typeof e.key === "string" ? e.key : null,
            ),
        )
      : null;
  if (stateFile !== undefined && existingStateKeys) {
    const plan = planOperatorStateRestore(
      stateFile,
      existingStateKeys,
      force,
    );
    let applied = 0;
    for (const { key, value } of plan.puts) {
      try {
        const resp = await fetch(
          `${mcp.base}/api/v1/operator-state/${encodeURIComponent(key)}`,
          {
            method: "PUT",
            headers: auth,
            body: JSON.stringify({ value }),
            signal: AbortSignal.timeout(15000),
          },
        );
        if (resp.ok) {
          applied += 1;
        } else {
          const body = await resp.text().catch(() => "");
          summary.errors.push(
            `operator state ${key} PUT returned HTTP ${resp.status}: ${body.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `operator state ${key} restore failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    if (plan.invalid) {
      summary.warnings.push(
        `operator state: ${plan.invalid} unusable entr${plan.invalid === 1 ? "y" : "ies"} ignored`,
      );
    }
    summary.applied.operator_state = applied;
    summary.skipped.operator_state = plan.skipped;
  }

  // ── 6c. Hooks — POST each hook (the store upserts on the id); keep
  //        the destination's own unless force; hooks that lost secret
  //        values come back disabled (lib/hooks-backup.ts) ───────────
  const hooksFile = await readJsonFile<unknown>(HOOKS_FILE);
  // Skipped as a whole when the destination's hooks cannot be listed.
  const existingHookIds =
    hooksFile !== undefined
      ? await existingOrSkip(
          "hooks",
          "hooks",
          hooksEntryCount(hooksFile),
          () => getJson("/api/v1/hooks"),
          (b) =>
            keysFromList(b, "hooks", (h) =>
              typeof h.id === "string" ? h.id : null,
            ),
        )
      : null;
  if (hooksFile !== undefined && existingHookIds) {
    const plan = planHooksRestore(hooksFile, existingHookIds, force);
    const lostSecrets = new Set(plan.disabledForSecrets);
    summary.warnings.push(...plan.warnings);
    let applied = 0;
    let skipped = plan.skipped;
    for (const hook of plan.posts) {
      // The MCP only checks the shape. The agent-side validator also checks
      // that a builtin still exists in this image and that its config is
      // valid, so a hook this install could not run is reported, not stored.
      // A hook that lost secret values is expected to fail the config check
      // (a required value is gone), so only its builtin name is checked.
      const transport = hook.transport as { type?: string; name?: string };
      const usable = lostSecrets.has(hook.id)
        ? transport.type !== "builtin" ||
          (typeof transport.name === "string" &&
            getBuiltinHook(transport.name) !== undefined)
        : validateHook(hook) !== null;
      if (!usable) {
        skipped += 1;
        summary.warnings.push(
          `hooks: ${String(hook.name ?? hook.id)} (${hook.id}) not restored: ` +
            "this install cannot run it (unknown builtin or invalid definition).",
        );
        continue;
      }
      try {
        const resp = await fetch(`${mcp.base}/api/v1/hooks`, {
          method: "POST",
          headers: auth,
          body: JSON.stringify(hook),
          signal: AbortSignal.timeout(15000),
        });
        if (resp.ok || resp.status === 201) {
          applied += 1;
        } else {
          const body = await resp.text().catch(() => "");
          summary.errors.push(
            `hook ${hook.id} POST returned HTTP ${resp.status}: ${body.slice(0, 200)}`,
          );
        }
      } catch (e) {
        summary.errors.push(
          `hook ${hook.id} restore failed: ${
            e instanceof Error ? e.message : String(e)
          }`,
        );
      }
    }
    if (plan.invalid) {
      summary.warnings.push(
        `hooks: ${plan.invalid} unusable entr${plan.invalid === 1 ? "y" : "ies"} ignored`,
      );
    }
    summary.applied.hooks = applied;
    summary.skipped.hooks = skipped;
  }

  // ── 7. Jobs — POST each runtime job last (so connectors exist) ───
  const jobsWrap = await readJsonFile<{ jobs?: JobFromBackup[] }>(
    "jobs.json",
  );
  // Pre-fetch existing jobs to detect collisions.
  const existingJobs = jobsWrap?.jobs?.length
    ? await existingOrSkip(
        "jobs",
        "jobs",
        jobsWrap.jobs.length,
        () => getJson("/api/v1/jobs"),
        (b) =>
          keysFromList(b, "jobs", (j) =>
            typeof j.name === "string" ? j.name : null,
          ),
      )
    : null;
  if (jobsWrap?.jobs?.length && existingJobs) {
    const existing = existingJobs;
    let applied = 0;
    let skipped = 0;
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
