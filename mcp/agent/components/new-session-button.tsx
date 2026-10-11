"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createAgentRun } from "@/lib/api/runs";

export interface NewSessionButtonProps {
  agentId: string;
  className?: string;
  label?: string;
}

export function NewSessionButton({
  agentId,
  className,
  label = "New Session",
}: NewSessionButtonProps) {
  const router = useRouter();
  const [isCreating, setIsCreating] = useState(false);

  async function handleClick() {
    setIsCreating(true);
    const result = await createAgentRun(agentId, "");
    if (result.ok) {
      router.push(`/agents/${agentId}/sessions/${result.data.sessionId}`);
    }
    setIsCreating(false);
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isCreating}
      className={className}
      aria-label="New Session"
    >
      {isCreating ? "Creating…" : label}
    </button>
  );
}
