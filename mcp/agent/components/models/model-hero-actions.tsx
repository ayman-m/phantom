"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api/client";
import { setConfigPath } from "@/lib/api/config";

interface ModelHeroActionsProps {
  provider: string;
  modelId: string;
  displayName: string;
  isDefault: boolean;
}

type TestStatus = "idle" | "testing" | "success" | "error";
type DefaultStatus = "idle" | "saving" | "saved" | "error";

/** Normalize CLI provider IDs back to the base provider for API calls. */
function resolveBaseProvider(provider: string): string {
  if (provider === "anthropic-cli") return "anthropic";
  if (provider === "openai-codex") return "openai";
  return provider;
}

export function ModelHeroActions({
  provider,
  modelId,
  displayName,
  isDefault,
}: ModelHeroActionsProps) {
  const router = useRouter();
  const [testStatus, setTestStatus] = React.useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = React.useState("");
  const [defaultStatus, setDefaultStatus] = React.useState<DefaultStatus>("idle");

  async function handleSetDefault() {
    setDefaultStatus("saving");

    try {
      const result = await setConfigPath(
        "workspace",
        { defaultModel: modelId, defaultProvider: provider },
        "", // hash — not validated yet
      );

      if (result.ok) {
        setDefaultStatus("saved");
        // Revalidate the page to refresh badges across the app.
        router.refresh();
      } else {
        setDefaultStatus("error");
      }
    } catch {
      setDefaultStatus("error");
    }
  }

  async function handleTestConnection() {
    setTestStatus("testing");
    setTestMessage("");

    const baseProvider = resolveBaseProvider(provider);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    try {
      const result = await apiRequest<{ status: string; message: string }>(
        `/api/v1/providers/${encodeURIComponent(baseProvider)}/test`,
        {
          method: "POST",
          body: {},
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);

      if (result.ok && result.data.status === "success") {
        setTestStatus("success");
        setTestMessage(result.data.message || "Connected");
      } else {
        const msg = result.ok ? result.data.message : result.error.message;
        setTestStatus("error");
        setTestMessage(msg);
      }
    } catch {
      clearTimeout(timeoutId);
      setTestStatus("error");
      setTestMessage("Connection timed out");
    }
  }

  const statusColors: Record<TestStatus, string> = {
    idle: "",
    testing: "text-on-surface-variant",
    success: "text-secondary",
    error: "text-error",
  };

  return (
    <div className="flex items-center gap-3 shrink-0 flex-wrap">
      {/* Set as Default */}
      <button
        type="button"
        onClick={handleSetDefault}
        disabled={isDefault || defaultStatus === "saving"}
        className="text-white px-6 py-3 rounded-xl font-label text-xs uppercase tracking-wider font-bold shadow-lg transition-all hover:brightness-110 hover:shadow-primary/30 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          background: isDefault
            ? "linear-gradient(135deg, #424751 0%, #555 100%)"
            : "linear-gradient(135deg, #1963B3 0%, #2D8DF0 100%)",
        }}
        aria-label={`Set ${displayName} as default model`}
      >
        {isDefault
          ? "✓ Current Default"
          : defaultStatus === "saving"
            ? "Saving…"
            : defaultStatus === "saved"
              ? "✓ Saved"
              : "Set as Default"}
      </button>

      {/* Test Connection */}
      <button
        type="button"
        onClick={handleTestConnection}
        disabled={testStatus === "testing"}
        className="px-6 py-3 rounded-xl font-label text-xs uppercase tracking-wider font-bold text-on-surface hover:brightness-110 transition-all active:scale-95 disabled:opacity-60 shadow-lg"
        style={{ background: "linear-gradient(135deg, #037321 0%, #56B55A 100%)" }}
        aria-label={`Test connection to ${displayName}`}
      >
        {testStatus === "testing" ? "Testing…" : "Test Connection"}
      </button>

      {/* Status badge */}
      {testStatus !== "idle" && testStatus !== "testing" && (
        <span
          className={`text-xs font-bold ${statusColors[testStatus]} flex items-center gap-1.5`}
          role="status"
        >
          {testStatus === "success" && (
            <span className="w-2 h-2 rounded-full bg-secondary shadow-[0_0_8px_#7bdc7b]" />
          )}
          {testStatus === "error" && (
            <span className="material-symbols-outlined text-sm">error</span>
          )}
          {testMessage}
        </span>
      )}
    </div>
  );
}
