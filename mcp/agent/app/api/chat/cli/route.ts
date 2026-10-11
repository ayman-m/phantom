/**
 * POST /api/chat/cli — Claude Code CLI shell-out endpoint.
 *
 * First release of the multi-provider arc (A1). Phantom-agent ships
 * Claude Code (the `@anthropic-ai/claude-code` npm package) pre-
 * installed in the image. This route spawns it as a child process,
 * streams stdout back as SSE events, and writes an audit row for the
 * run. Operators pick CLI mode as a "second model option" alongside
 * the default Gemini chat-route — the chat-route's tool-call loop is
 * NOT involved on this path; Claude Code has its own internal tools.
 *
 * # Wire shape
 *
 *   POST /api/chat/cli
 *   { "prompt": "<task text>" }
 *
 *   ← SSE stream:
 *      event: meta        — { provider, started_at }
 *      event: output      — parsed JSON line (Claude Code emits JSONL)
 *      event: output_raw  — { line } for any non-JSON-parseable line
 *      event: done        — { exit_code, duration_ms, timed_out, stderr_tail }
 *      event: error       — { message } on transport failure
 *
 * # Auth
 *
 * Session-cookie gated by middleware.ts (matcher includes
 * /api/chat/:path*). The Anthropic credential is sourced via
 * lib/anthropic-credentials.ts → ProviderStore + env var fallback.
 * Returns 400 if no credential is configured anywhere.
 *
 * # Why a separate endpoint (not chat/route.ts)
 *
 * Claude Code's --print mode is one-shot, non-interactive, and runs
 * its own tool-call loop internally. It doesn't slot into the chat-
 * route's 20-step tool-dispatch + approval-gate + hook fire-site
 * pipeline. Keeping the path separate avoids forcing every Gemini
 * path comment to enumerate "...unless provider=claude-code".
 *
 * # What happens to the agent's MCP tools
 *
 * On this path, Claude Code DOES NOT see Phantom's MCP tools (data
 * sources, connectors, skills). It only has its own built-in tools
 * (file system, bash, web fetch, etc.). To give Claude Code access
 * to Phantom's MCP, we'd need to register Phantom's MCP as an
 * external server via Claude Code's `--mcp-config` flag — that's a
 * possible future enhancement, not supported today.
 */

import { NextRequest, NextResponse } from "next/server";

import { runCliStreaming } from "@/lib/cli-wrapper";
import { resolveAnthropicCliKey } from "@/lib/anthropic-credentials";

export const dynamic = "force-dynamic";

const CLAUDE_CODE_TIMEOUT_MS = 600_000; // 10 minutes — matches Spark's plugin.yaml.
const STDERR_TAIL_BYTES = 2_000;

interface RequestBody {
  prompt?: string;
  /** Optional cwd override. Defaults to a fresh tmp dir per request
   *  so the CLI has somewhere to write working files without
   *  polluting the container filesystem. */
  workDir?: string;
}

export async function POST(request: NextRequest) {
  let body: RequestBody;
  try {
    body = (await request.json()) as RequestBody;
  } catch {
    return NextResponse.json(
      { error: "invalid JSON body" },
      { status: 400 },
    );
  }

  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) {
    return NextResponse.json(
      { error: "prompt is required" },
      { status: 400 },
    );
  }

  const apiKey = await resolveAnthropicCliKey();
  if (!apiKey) {
    return NextResponse.json(
      {
        error:
          "Anthropic credentials not configured. Set ANTHROPIC_API_KEY or " +
          "CLAUDE_CODE_OAUTH_TOKEN in /opt/phantom/.env, or configure via " +
          "/providers once the ProviderStore write path is wired.",
      },
      { status: 400 },
    );
  }

  // SSE stream. ReadableStream pattern matches lib/system-prompt.ts +
  // the main chat route — Next.js 15 + Edge-runtime-safe.
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: string, data: object) => {
        try {
          const line = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
          controller.enqueue(encoder.encode(line));
        } catch {
          // Controller already closed (client disconnected). Swallow.
        }
      };

      send("meta", {
        provider: "claude-code",
        started_at: new Date().toISOString(),
      });

      try {
        const result = await runCliStreaming(
          {
            // Claude Code CLI backend pattern:
            //
            //  1. Invoke `claude` directly (already on PATH in the image as
            //     /usr/bin/claude, version 1.0.128). A per-call `npx
            //     @anthropic-ai/claude-code` install would be slow AND
            //     could resolve a different version than what's baked.
            //
            //  2. Use `--permission-mode bypassPermissions`. Without this,
            //     Claude Code stalls at interactive permission prompts
            //     (file-write / bash / etc.) — the watchdog kills the
            //     run with "no output for N seconds." The one-shot flow
            //     therefore uses bypassPermissions.
            //
            //  3. `clearEnv: ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_OLD"]`
            //     + `envVars: { CLAUDE_CODE_OAUTH_TOKEN: apiKey }` only —
            //     do NOT set ANTHROPIC_API_KEY. Claude Code prefers
            //     ANTHROPIC_API_KEY over CLAUDE_CODE_OAUTH_TOKEN when both
            //     are set; the device token isn't a valid API key, so
            //     setting both env vars to the same value would break the
            //     Max-subscription / device-token OAuth flow.
            //
            //  4. `envVars: { IS_SANDBOX: "1" }` bypasses Claude
            //     Code's hardcoded root-guard. Upstream code (in
            //     @anthropic-ai/claude-code) checks `process.getuid()` at
            //     startup and `process.exit(1)`s with the message
            //     "--dangerously-skip-permissions cannot be used with root/sudo
            //     privileges for security reasons" when bypassPermissions is
            //     requested from a root process. The guard's premise is "we
            //     can't tell whether you're sandboxed." For phantom_agent that
            //     premise is false by inspection — the agent runs in a Docker
            //     container with bind-mount volumes only, ephemeral FS
            //     otherwise, no host access path. Setting IS_SANDBOX=1 (the
            //     documented escape hatch, alongside CLAUDE_CODE_BUBBLEWRAP=1)
            //     tells Claude Code that the operator has already asserted
            //     sandbox status. The alternative — dropping the
            //     whole container to a non-root USER in the agent Dockerfile —
            //     would touch TLS, ports, the embedded MCP and the skills
            //     bootstrap.
            name: "claude-code",
            command: "claude",
            args: [
              "-p",
              "--output-format",
              "json",
              "--permission-mode",
              "bypassPermissions",
            ],
            envVars: {
              CLAUDE_CODE_OAUTH_TOKEN: apiKey,
              IS_SANDBOX: "1",
            },
            clearEnv: ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_OLD"],
            timeoutMs: CLAUDE_CODE_TIMEOUT_MS,
            workDir: body.workDir,
          },
          prompt,
          (line) => {
            // Claude Code --output-format=json emits a final JSON
            // object on success and may emit per-event JSON lines
            // during execution. Try to parse; fall back to raw on
            // anything that isn't valid JSON (banner output,
            // partial lines mid-stream, etc.).
            try {
              const obj = JSON.parse(line);
              send("output", obj as object);
            } catch {
              send("output_raw", { line });
            }
          },
        );

        send("done", {
          exit_code: result.exitCode,
          duration_ms: result.durationMs,
          timed_out: result.timedOut,
          stderr_tail: result.stderr.slice(-STDERR_TAIL_BYTES),
        });
      } catch (err) {
        send("error", {
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        try {
          controller.close();
        } catch {
          // Already closed (client disconnected mid-stream). Swallow.
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
