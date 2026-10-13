/**
 * "Set as default" on the Models pages: write the install's default chat model.
 *
 * One call to PUT /api/agent/settings with `defaultModel` set to the canonical
 * "provider/model" ref. That proxy checks the ref against the model registry
 * (a name it rejects answers 400 with suggestions) and drops the cache the chat
 * route reads the default through, so the next turn uses it.
 *
 * The default is global: it serves new chats, jobs and benchmarks that name no
 * model, and subagents without their own. A session pinned with `/model`, a
 * job with its own model, and the chat header's pick are unaffected.
 */

import { confirmAction } from "@/lib/stores/confirm";
import { notify } from "@/lib/stores/notifications";

/** Ask, write, report. Resolves true when the default changed. */
export async function setInstallDefaultModel(ref: string, displayName: string): Promise<boolean> {
  const accepted = await confirmAction({
    title: `Make ${displayName} the default model?`,
    message:
      `New chats, jobs and benchmarks that name no model, and subagents without their own, will run on ${ref}. ` +
      "Sessions pinned with /model, jobs with their own model and the chat header's pick keep theirs.",
    confirmLabel: "Set as default",
  });
  if (!accepted) return false;
  try {
    const res = await fetch("/api/agent/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates: { defaultModel: ref }, actor: "operator" }),
    });
    const body = (await res.json().catch(() => ({}))) as { error?: string; suggestions?: string[] };
    if (!res.ok) {
      notify("error", "The default model was not changed", body.error ?? `HTTP ${res.status}`);
      return false;
    }
    notify("success", "Default model set", ref);
    return true;
  } catch (err) {
    notify("error", "The default model was not changed", err instanceof Error ? err.message : String(err));
    return false;
  }
}

/** The hover text for the default badge. */
export function defaultSourceHint(source: "default" | "derived" | null | undefined): string {
  return source === "derived"
    ? "No default model is set. This model serves because it is the recommended model of the first configured provider."
    : "The default model chosen for this install.";
}
