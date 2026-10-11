import { create } from "zustand";
import {
  WebSocketManager,
  ConnectionState,
  type EventCallback,
  type StateCallback,
} from "../ws/manager";
import {
  RunEventType,
  type EventMessage,
  type PartialTextPayload,
  type ReasoningChunkPayload,
  type ToolCallStartedPayload,
  type ToolCallCompletedPayload,
  type StateChangedPayload,
  type FailedPayload,
} from "../ws/types";
import { useChatStore } from "./chat";

/**
 * @deprecated The generalized `/stream` WebSocket channel model has been
 * removed (known-gaps item 8).  The chat page streams via SSE through
 * `POST /api/v1/chat` and per-run streaming uses gateway endpoints
 * `GET /api/v1/runs/{run_id}/stream` (WebSocket) and
 * `GET /api/v1/runs/{run_id}/events` (SSE).
 *
 * This store is kept for backward compatibility with dashboard-client,
 * approvals, and session chat-view pages that still reference it.  New
 * code should use the per-run SSE/WebSocket endpoints directly.
 */
export interface WebSocketState {
  connectionStatus: ConnectionState;
  subscribedChannels: string[];
  subscribedRuns: string[];
}

export interface WebSocketActions {
  connect: (token: string) => void;
  disconnect: () => void;
  subscribe: (channel: string) => void;
  unsubscribe: (channel: string) => void;
  subscribeToRun: (runId: string) => void;
  unsubscribeFromRun: (runId: string) => void;
  on: (eventType: string, callback: EventCallback) => void;
  off: (eventType: string, callback: EventCallback) => void;
}

export type WebSocketStore = WebSocketState & WebSocketActions;

/**
 * @deprecated See WebSocketState deprecation note.  The old `/stream`
 * endpoint no longer exists; this now falls back to the per-run
 * WebSocket base path (`/api/v1/runs`).  Callers should migrate to
 * per-run streaming endpoints directly.
 */
function resolveWebSocketBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_WS_URL?.trim();

  if (configuredUrl) {
    return configuredUrl;
  }

  if (typeof window === "undefined") {
    throw new Error(
      "NEXT_PUBLIC_WS_URL is not configured and window.location is unavailable",
    );
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/runs`;
}

let manager: WebSocketManager | null = null;

const stateCallback: StateCallback = (state) => {
  useWebSocketStore.setState({
    connectionStatus: state,
    subscribedChannels: Array.from(getManager().subscribedChannels),
  });
};

/** Get the shared WebSocketManager instance (creates one if needed). */
export function getManager(): WebSocketManager {
  if (!manager) {
    manager = new WebSocketManager();
    manager.onStateChange(stateCallback);
  }
  return manager;
}

/** Replace the shared manager (useful for testing). */
export function setManager(m: WebSocketManager): void {
  if (manager) {
    manager.offStateChange(stateCallback);
  }
  manager = m;
  manager.onStateChange(stateCallback);
}

/** Map of runId → event handler for cleanup on unsubscribe. */
const runEventHandlers = new Map<string, EventCallback>();

/** Route a run channel event to the chat store. */
export function handleRunEvent(
  runId: string,
  msg: EventMessage,
): void {
  const chat = useChatStore.getState();
  const eventType = msg.event as RunEventType;

  switch (eventType) {
    case RunEventType.PARTIAL_TEXT: {
      const payload = msg.data as unknown as PartialTextPayload;
      chat.appendText(payload.chunk);
      break;
    }
    case RunEventType.REASONING_CHUNK: {
      const payload = msg.data as unknown as ReasoningChunkPayload;
      chat.appendReasoning(payload.chunk);
      break;
    }
    case RunEventType.TOOL_CALL_STARTED: {
      const payload = msg.data as unknown as ToolCallStartedPayload;
      chat.addToolCall({
        id: payload.id,
        name: payload.name,
        arguments: payload.arguments,
        status: "pending",
      });
      break;
    }
    case RunEventType.TOOL_CALL_COMPLETED: {
      const payload = msg.data as unknown as ToolCallCompletedPayload;
      if (payload.error) {
        chat.failToolCall(payload.id, payload.error);
      } else {
        chat.completeToolCall(payload.id, payload.result ?? "");
      }
      break;
    }
    case RunEventType.STATE_CHANGED: {
      const payload = msg.data as unknown as StateChangedPayload;
      if (payload.state === "awaiting_approval" && payload.approval_id) {
        chat.addApproval({
          id: payload.approval_id,
          tool: payload.tool ?? "unknown",
          description: payload.description ?? "",
          status: "pending",
        });
      }
      break;
    }
    case RunEventType.COMPLETED: {
      chat.completeRun();
      useWebSocketStore.getState().unsubscribeFromRun(runId);
      break;
    }
    case RunEventType.FAILED: {
      const payload = msg.data as unknown as FailedPayload;
      chat.failRun(payload.error);
      useWebSocketStore.getState().unsubscribeFromRun(runId);
      break;
    }
    case RunEventType.CANCELLED: {
      chat.cancelRun();
      useWebSocketStore.getState().unsubscribeFromRun(runId);
      break;
    }
  }
}

export const useWebSocketStore = create<WebSocketStore>(() => ({
  connectionStatus: ConnectionState.DISCONNECTED,
  subscribedChannels: [],
  subscribedRuns: [],

  connect: (token: string) => {
    const url = `${resolveWebSocketBaseUrl()}?token=${encodeURIComponent(token)}`;
    getManager().connect(url);
  },

  disconnect: () => {
    getManager().disconnect();
  },

  subscribe: (channel: string) => {
    getManager().subscribe([channel]);
    useWebSocketStore.setState({
      subscribedChannels: Array.from(getManager().subscribedChannels),
    });
  },

  unsubscribe: (channel: string) => {
    getManager().unsubscribe([channel]);
    useWebSocketStore.setState({
      subscribedChannels: Array.from(getManager().subscribedChannels),
    });
  },

  subscribeToRun: (runId: string) => {
    const channel = `run:${runId}`;
    const mgr = getManager();

    const handler: EventCallback = (msg: EventMessage) => {
      if (msg.channel === channel) {
        handleRunEvent(runId, msg);
      }
    };

    runEventHandlers.set(runId, handler);
    mgr.subscribe([channel]);

    // Listen for each run event type on the manager
    for (const eventType of Object.values(RunEventType)) {
      mgr.on(eventType, handler);
    }

    useWebSocketStore.setState((state) => ({
      subscribedChannels: Array.from(mgr.subscribedChannels),
      subscribedRuns: [...state.subscribedRuns, runId],
    }));
  },

  unsubscribeFromRun: (runId: string) => {
    const channel = `run:${runId}`;
    const mgr = getManager();
    const handler = runEventHandlers.get(runId);

    if (handler) {
      for (const eventType of Object.values(RunEventType)) {
        mgr.off(eventType, handler);
      }
      runEventHandlers.delete(runId);
    }

    mgr.unsubscribe([channel]);

    useWebSocketStore.setState((state) => ({
      subscribedChannels: Array.from(mgr.subscribedChannels),
      subscribedRuns: state.subscribedRuns.filter((id) => id !== runId),
    }));
  },

  on: (eventType: string, callback: EventCallback) => {
    getManager().on(eventType, callback);
  },

  off: (eventType: string, callback: EventCallback) => {
    getManager().off(eventType, callback);
  },
}));
