/**
 * CLI wrapper — port of Spark's plugin-runner/internal/cli pattern,
 * adapted for Phantom's in-process spawn model.
 *
 * Spark runs each CLI tool (Claude Code, Codex) inside a dedicated
 * Docker container with --cap-drop=ALL for isolation. Phantom-agent
 * already ships Node.js inside its single container, so we spawn the
 * CLI as a child process directly. The tradeoff is less isolation,
 * matching Phantom's single-host single-container deployment model.
 * Container-level isolation can be layered in later if needed (the
 * per-instance-connector-container pattern provides the template).
 *
 * Usage:
 *
 *   const result = await runCli({
 *     name: "claude-code",
 *     command: "npx",
 *     args: ["@anthropic-ai/claude-code", "--print", "--output-format", "json"],
 *     envVars: { ANTHROPIC_API_KEY: "sk-ant-..." },
 *     timeoutMs: 600_000,
 *   }, "What does this codebase do?");
 *
 * For SSE-streamed endpoints, prefer runCliStreaming so stdout lines
 * arrive as they're produced instead of buffered until completion.
 */

import { spawn } from "child_process";

export interface CliWrapperConfig {
  /** Plugin identifier (audit trail, error messages). */
  name: string;
  /** Executable to invoke (e.g. "npx", "claude", "codex"). */
  command: string;
  /** Args appended BEFORE the task prompt. */
  args: string[];
  /** Environment variables — merged onto the inherited env. Secret
   *  values flow here (e.g. ANTHROPIC_API_KEY). Use sparingly: every
   *  key listed here is visible to the child process. */
  envVars: Record<string, string>;
  /** Environment variables to DELETE from the inherited env before
   *  spawning. Applied AFTER `envVars` are overlaid — so if you both
   *  add and clear the same key, the clear wins. Mirrors the
   *  known-working `clearEnv` pattern: Claude Code prefers
   *  ANTHROPIC_API_KEY over CLAUDE_CODE_OAUTH_TOKEN when both are set,
   *  which breaks the device-token / Max-subscription OAuth flow. To
   *  force the OAuth path you MUST delete ANTHROPIC_API_KEY from env. */
  clearEnv?: string[];
  /** Hard timeout in milliseconds. Past this, the child is sent
   *  SIGTERM, then SIGKILL after a 5-second grace period. */
  timeoutMs: number;
  /** Working directory for the child. Defaults to /tmp. */
  workDir?: string;
}

export interface CliResult {
  /** Process exit code. -1 if the process was killed (timeout or SIGKILL).
   *  Non-zero exit codes are usually CLI-tool-specific errors. */
  exitCode: number;
  /** Combined stdout (captured in full; can be large). */
  stdout: string;
  /** Combined stderr (captured in full). Most CLI tools write diagnostic
   *  output here, not actual results. */
  stderr: string;
  /** Wall-clock duration from spawn to exit. */
  durationMs: number;
  /** True if the process was killed because timeoutMs elapsed. */
  timedOut: boolean;
}

const SIGTERM_GRACE_MS = 5_000;

/**
 * Run a CLI tool with a task prompt. Captures stdout + stderr in full,
 * enforces a timeout, returns the result once the process exits.
 *
 * The task prompt is appended as the final positional argument. Most
 * CLI tools accept the prompt this way (Claude Code, Codex). If a
 * specific tool wants the prompt on stdin instead, that's a future
 * extension — pass it as the last argv element for now.
 */
export async function runCli(
  config: CliWrapperConfig,
  task: string,
): Promise<CliResult> {
  return runCliInternal(config, task, () => {});
}

/**
 * Same as runCli but invokes `onStdoutLine(line)` for each newline-
 * delimited chunk of stdout as it arrives. Lines that don't end with
 * a newline at process exit are flushed via a final onStdoutLine call.
 *
 * Use this for SSE endpoints — emit an SSE event per stdout line and
 * the operator sees output stream in real-time rather than waiting
 * for the whole CLI run to complete.
 */
export async function runCliStreaming(
  config: CliWrapperConfig,
  task: string,
  onStdoutLine: (line: string) => void,
): Promise<CliResult> {
  return runCliInternal(config, task, onStdoutLine);
}

async function runCliInternal(
  config: CliWrapperConfig,
  task: string,
  onStdoutLine: (line: string) => void,
): Promise<CliResult> {
  const startedAt = Date.now();
  const argv = [...config.args, task];

  // Merge env vars: inherit current env, then overlay caller's vars.
  // Caller wins on conflict — that's the credential-injection pattern.
  // Then DELETE any keys listed in clearEnv — clear wins over overlay.
  const env: NodeJS.ProcessEnv = { ...process.env, ...config.envVars };
  for (const key of config.clearEnv ?? []) {
    delete env[key];
  }

  const child = spawn(config.command, argv, {
    env,
    cwd: config.workDir ?? "/tmp",
    stdio: ["ignore", "pipe", "pipe"],
  });

  let stdout = "";
  let stderr = "";
  let stdoutBuffer = "";
  let timedOut = false;

  // Stream stdout line-by-line through the callback.
  child.stdout.setEncoding("utf-8");
  child.stdout.on("data", (chunk: string) => {
    stdout += chunk;
    stdoutBuffer += chunk;
    let newlineIdx: number;
    while ((newlineIdx = stdoutBuffer.indexOf("\n")) !== -1) {
      const line = stdoutBuffer.slice(0, newlineIdx);
      stdoutBuffer = stdoutBuffer.slice(newlineIdx + 1);
      if (line.length > 0) {
        try {
          onStdoutLine(line);
        } catch {
          // Callback errors don't abort the CLI run.
        }
      }
    }
  });

  child.stderr.setEncoding("utf-8");
  child.stderr.on("data", (chunk: string) => {
    stderr += chunk;
  });

  // Hard timeout: SIGTERM then SIGKILL after a grace period.
  const timeoutHandle = setTimeout(() => {
    timedOut = true;
    if (child.pid && !child.killed) {
      child.kill("SIGTERM");
      setTimeout(() => {
        if (!child.killed) child.kill("SIGKILL");
      }, SIGTERM_GRACE_MS).unref();
    }
  }, config.timeoutMs);
  timeoutHandle.unref();

  // Wait for exit.
  const exitCode: number = await new Promise((resolve) => {
    child.on("close", (code, signal) => {
      // close fires after all stdio streams close. exit fires earlier
      // and may leave buffered output unread — close is the correct
      // synchronization point.
      clearTimeout(timeoutHandle);
      resolve(typeof code === "number" ? code : signal ? -1 : 0);
    });
    child.on("error", () => {
      // Spawn failure (command not found, etc.) — resolve with -1.
      clearTimeout(timeoutHandle);
      resolve(-1);
    });
  });

  // Flush any final partial stdout line that didn't end with \n.
  if (stdoutBuffer.length > 0) {
    try {
      onStdoutLine(stdoutBuffer);
    } catch {
      // Same swallow rule as the streaming path.
    }
  }

  return {
    exitCode,
    stdout,
    stderr,
    durationMs: Date.now() - startedAt,
    timedOut,
  };
}
