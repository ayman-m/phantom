"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { deleteAgent, updateAgent } from "@/lib/api/agents";
import type { Agent } from "@/lib/api/types";

interface PresenceInfo {
  status: "online" | "busy" | "idle" | "offline";
  last_seen_at?: string;
}

interface AgentPageHeaderProps {
  agent: Agent;
  presence: PresenceInfo | null;
  onAgentUpdated: (agent: Agent) => void;
}

const presenceConfig: Record<
  PresenceInfo["status"],
  { label: string; dotClass: string; glowClass: string }
> = {
  online: {
    label: "Online",
    dotClass: "bg-[#7bdc7b]",
    glowClass: "shadow-[0_0_8px_#7bdc7b]",
  },
  busy: {
    label: "Busy",
    dotClass: "bg-amber-400",
    glowClass: "shadow-[0_0_8px_rgba(251,191,36,0.5)]",
  },
  idle: {
    label: "Idle",
    dotClass: "bg-tertiary",
    glowClass: "shadow-[0_0_8px_rgba(160,140,255,0.3)]",
  },
  offline: {
    label: "Offline",
    dotClass: "bg-outline-variant",
    glowClass: "",
  },
};

export function AgentPageHeader({
  agent,
  presence,
  onAgentUpdated,
}: AgentPageHeaderProps) {
  const router = useRouter();
  const [editingName, setEditingName] = React.useState(false);
  const [name, setName] = React.useState(agent.name);
  const [copied, setCopied] = React.useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    setName(agent.name);
  }, [agent.name]);

  React.useEffect(() => {
    if (editingName && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingName]);

  const status = presence?.status ?? "offline";
  const pCfg = presenceConfig[status];

  async function handleNameSave() {
    setEditingName(false);
    if (name.trim() && name !== agent.name) {
      const result = await updateAgent(agent.agent_id, { name: name.trim() });
      if (result.ok) {
        onAgentUpdated(result.data);
      } else {
        setName(agent.name);
      }
    } else {
      setName(agent.name);
    }
  }

  function handleCopyId() {
    navigator.clipboard.writeText(agent.agent_id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleDelete() {
    setDeleting(true);
    const result = await deleteAgent(agent.agent_id);
    setDeleting(false);
    if (result.ok) {
      router.push("/agents");
    }
  }

  return (
    <>
      <section className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="flex items-center gap-5">
          {/* Avatar */}
          <div className="relative">
            <div
              className="w-16 h-16 rounded-xl flex items-center justify-center border overflow-hidden"
              style={{
                background: "var(--glass-bg-strong)",
                backdropFilter: "blur(12px)",
                borderColor: "var(--glass-border)",
              }}
            >
              <span
                className="material-symbols-outlined text-primary text-3xl"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                smart_toy
              </span>
            </div>
            <div
              className={`absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full border-[3px] border-background ${pCfg.dotClass} ${pCfg.glowClass}`}
            />
          </div>

          {/* Name + presence + ID */}
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              {editingName ? (
                <input
                  ref={inputRef}
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onBlur={handleNameSave}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleNameSave();
                    if (e.key === "Escape") {
                      setName(agent.name);
                      setEditingName(false);
                    }
                  }}
                  className="text-2xl font-headline font-bold tracking-tight text-on-surface bg-transparent border-b border-primary outline-none"
                />
              ) : (
                <h1
                  className="text-2xl font-headline font-bold tracking-tight text-on-surface cursor-pointer hover:text-primary transition-colors"
                  onClick={() => setEditingName(true)}
                  title="Click to edit name"
                >
                  {agent.name}
                </h1>
              )}
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/[0.04]">
                <span
                  className={`w-2 h-2 rounded-full ${pCfg.dotClass} ${pCfg.glowClass}`}
                />
                <span className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant">
                  {pCfg.label}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2 text-on-surface-variant">
              <span className="text-xs font-mono opacity-60">{agent.agent_id}</span>
              <button
                type="button"
                onClick={handleCopyId}
                className="text-on-surface-variant hover:text-primary transition-colors"
                aria-label="Copy agent ID"
              >
                <span className="material-symbols-outlined text-sm">
                  {copied ? "check" : "content_copy"}
                </span>
              </button>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push("/chat")}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-on-primary-container transition-all hover:scale-[1.02] active:scale-95"
            style={{
              background:
                "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
            }}
          >
            <span className="material-symbols-outlined text-base">chat</span>
            Start Chat
          </button>
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-error border border-error/30 hover:bg-error/10 transition-colors"
          >
            <span className="material-symbols-outlined text-base">delete</span>
            Delete
          </button>
        </div>
      </section>

      {/* Delete Confirmation Dialog */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div
            className="max-w-md w-full mx-4 p-6 rounded-xl space-y-4"
            style={{
              background: "var(--glass-bg-elev)",
              backdropFilter: "blur(12px)",
              border: "0.5px solid var(--glass-border)",
            }}
          >
            <h3 className="text-lg font-headline font-bold text-on-surface">
              Delete Agent
            </h3>
            <p className="text-sm text-on-surface-variant">
              Are you sure you want to delete{" "}
              <span className="font-bold text-on-surface">{agent.name}</span>?
              This action cannot be undone. All sessions and data associated with
              this agent will be permanently removed.
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 rounded-lg text-sm font-label text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="px-4 py-2 rounded-lg text-sm font-label font-bold text-on-surface bg-error hover:bg-error/80 disabled:opacity-50 transition-colors"
              >
                {deleting ? "Deleting..." : "Delete Agent"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
