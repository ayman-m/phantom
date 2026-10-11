"use client";

import { useEffect } from "react";
import { useAuthStore } from "@/lib/stores/auth";
import { ToastContainer } from "@/components/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  const checkAuth = useAuthStore((s) => s.checkAuth);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // NOTE: The generalized /stream WebSocket auto-connect was removed
  // (known-gaps item 8).  The chat page streams via SSE through
  // POST /api/v1/chat.  Per-run streaming uses the gateway's
  // GET /api/v1/runs/{run_id}/stream (WebSocket) and
  // GET /api/v1/runs/{run_id}/events (SSE), connected on-demand by
  // individual pages (e.g., session chat-view, dashboard).

  return (
    <>
      {children}
      <ToastContainer />
    </>
  );
}
