import { create } from "zustand";
import { abortRun } from "../api/runs";

/** Role of a chat message sender. */
export type MessageRole = "user" | "assistant";

/** A tool call embedded within an assistant message. */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "pending" | "success" | "error";
  result?: string;
  error?: string;
}

/** An approval request embedded within an assistant message.
 *
 * Self-modification approval: every gated MCP tool call (anything in
 * manifest.approvals.humanRequired[]) creates a row of this shape.
 * Approval cards in the chat thread render against it; the chat
 * stream's `approval_pending` SSE event populates it.
 */
export interface ApprovalRequest {
  id: string;
  tool: string;
  description: string;
  arguments?: Record<string, unknown>;
  status: "pending" | "approved" | "denied";
  resolvedBy?: string;
  /** Self-modification risk tier — drives card color, banner text, and the
   * "type CONFIRM" challenge for credential ops.
   *   soft         — Tier 2: green Approve button (default).
   *   destructive  — Tier 3: red banner; "this is irrecoverable" line.
   *   credential   — Tier 4: type CONFIRM input gates the button. */
  riskTier?: "soft" | "destructive" | "credential";
  /** ISO-8601 timestamp from the bus row's created_at. */
  createdAt?: string;
  /** The tool_call_id from the SSE stream — lets the renderer
   * correlate the card to the originating tool_call event. */
  toolCallId?: string;
}

/** A single chat message in the session transcript. */
export interface ChatMessage {
  id: string;
  /** MCP-side message id when this row was loaded from
   *  persistence. Used by per-message Fork-from-here. Undefined for
   *  rows that came in via the live SSE stream and haven't been
   *  re-fetched yet. */
  mcpId?: string;
  role: MessageRole;
  text: string;
  reasoning?: string;
  toolCalls: ToolCall[];
  approvals: ApprovalRequest[];
  timestamp: string;
}

export interface ChatState {
  messages: ChatMessage[];
  activeRunId: string | null;
  isStreaming: boolean;
  streamingText: string;
  pendingToolCalls: ToolCall[];
  pendingApprovals: ApprovalRequest[];
  error: string | null;
}

export interface ChatActions {
  addUserMessage: (sessionId: string, text: string) => void;
  startRun: (sessionId: string, runId: string) => void;
  appendText: (chunk: string) => void;
  appendReasoning: (chunk: string) => void;
  addToolCall: (toolCall: ToolCall) => void;
  completeToolCall: (toolCallId: string, result: string) => void;
  failToolCall: (toolCallId: string, error: string) => void;
  addApproval: (approval: ApprovalRequest) => void;
  resolveApproval: (approvalId: string, resolution: "approved" | "denied") => void;
  completeRun: () => void;
  failRun: (error: string) => void;
  cancelRun: () => void;
  abortRun: (runId: string) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

export type ChatStore = ChatState & ChatActions;

const initialState: ChatState = {
  messages: [],
  activeRunId: null,
  isStreaming: false,
  streamingText: "",
  pendingToolCalls: [],
  pendingApprovals: [],
  error: null,
};

let nextMessageId = 0;

function generateMessageId(): string {
  nextMessageId++;
  return `msg-${nextMessageId}`;
}

/** Reset the message ID counter (for testing). */
export function resetMessageIdCounter(): void {
  nextMessageId = 0;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  ...initialState,

  addUserMessage: (_sessionId: string, text: string) => {
    const message: ChatMessage = {
      id: generateMessageId(),
      role: "user",
      text,
      toolCalls: [],
      approvals: [],
      timestamp: new Date().toISOString(),
    };
    set((state) => ({
      messages: [...state.messages, message],
      error: null,
    }));
  },

  startRun: (_sessionId: string, runId: string) => {
    const assistantMessage: ChatMessage = {
      id: generateMessageId(),
      role: "assistant",
      text: "",
      toolCalls: [],
      approvals: [],
      timestamp: new Date().toISOString(),
    };
    set((state) => ({
      messages: [...state.messages, assistantMessage],
      activeRunId: runId,
      isStreaming: true,
      streamingText: "",
      pendingToolCalls: [],
      pendingApprovals: [],
      error: null,
    }));
  },

  appendText: (chunk: string) => {
    set((state) => {
      const newStreamingText = state.streamingText + chunk;
      const messages = [...state.messages];
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "assistant") {
        messages[messages.length - 1] = {
          ...lastMessage,
          text: newStreamingText,
        };
      }
      return { messages, streamingText: newStreamingText };
    });
  },

  appendReasoning: (chunk: string) => {
    set((state) => {
      const messages = [...state.messages];
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "assistant") {
        messages[messages.length - 1] = {
          ...lastMessage,
          reasoning: (lastMessage.reasoning ?? "") + chunk,
        };
      }
      return { messages };
    });
  },

  addToolCall: (toolCall: ToolCall) => {
    set((state) => {
      const messages = [...state.messages];
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "assistant") {
        messages[messages.length - 1] = {
          ...lastMessage,
          toolCalls: [...lastMessage.toolCalls, toolCall],
        };
      }
      return {
        messages,
        pendingToolCalls: [...state.pendingToolCalls, toolCall],
      };
    });
  },

  completeToolCall: (toolCallId: string, result: string) => {
    set((state) => {
      const messages = state.messages.map((msg) => {
        if (msg.role !== "assistant") return msg;
        const idx = msg.toolCalls.findIndex((tc) => tc.id === toolCallId);
        if (idx === -1) return msg;
        const updatedToolCalls = [...msg.toolCalls];
        updatedToolCalls[idx] = {
          ...updatedToolCalls[idx],
          status: "success",
          result,
        };
        return { ...msg, toolCalls: updatedToolCalls };
      });
      return {
        messages,
        pendingToolCalls: state.pendingToolCalls.filter(
          (tc) => tc.id !== toolCallId,
        ),
      };
    });
  },

  failToolCall: (toolCallId: string, error: string) => {
    set((state) => {
      const messages = state.messages.map((msg) => {
        if (msg.role !== "assistant") return msg;
        const idx = msg.toolCalls.findIndex((tc) => tc.id === toolCallId);
        if (idx === -1) return msg;
        const updatedToolCalls = [...msg.toolCalls];
        updatedToolCalls[idx] = {
          ...updatedToolCalls[idx],
          status: "error",
          error,
        };
        return { ...msg, toolCalls: updatedToolCalls };
      });
      return {
        messages,
        pendingToolCalls: state.pendingToolCalls.filter(
          (tc) => tc.id !== toolCallId,
        ),
      };
    });
  },

  addApproval: (approval: ApprovalRequest) => {
    set((state) => {
      const messages = [...state.messages];
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "assistant") {
        messages[messages.length - 1] = {
          ...lastMessage,
          approvals: [...lastMessage.approvals, approval],
        };
      }
      return {
        messages,
        pendingApprovals: [...state.pendingApprovals, approval],
      };
    });
  },

  resolveApproval: (
    approvalId: string,
    resolution: "approved" | "denied",
  ) => {
    set((state) => {
      const messages = state.messages.map((msg) => {
        if (msg.role !== "assistant") return msg;
        const idx = msg.approvals.findIndex((a) => a.id === approvalId);
        if (idx === -1) return msg;
        const updatedApprovals = [...msg.approvals];
        updatedApprovals[idx] = {
          ...updatedApprovals[idx],
          status: resolution,
        };
        return { ...msg, approvals: updatedApprovals };
      });
      return {
        messages,
        pendingApprovals: state.pendingApprovals.filter(
          (a) => a.id !== approvalId,
        ),
      };
    });
  },

  completeRun: () => {
    set({
      activeRunId: null,
      isStreaming: false,
      streamingText: "",
      pendingToolCalls: [],
      pendingApprovals: [],
    });
  },

  failRun: (error: string) => {
    set({
      activeRunId: null,
      isStreaming: false,
      streamingText: "",
      pendingToolCalls: [],
      pendingApprovals: [],
      error,
    });
  },

  cancelRun: () => {
    set({
      activeRunId: null,
      isStreaming: false,
      streamingText: "",
      pendingToolCalls: [],
      pendingApprovals: [],
    });
  },

  abortRun: async (runId: string) => {
    const state = get();
    if (state.activeRunId !== runId) return;
    await abortRun(runId, "User aborted");
    set({
      activeRunId: null,
      isStreaming: false,
      streamingText: "",
      pendingToolCalls: [],
      pendingApprovals: [],
    });
  },

  clearError: () => {
    set({ error: null });
  },

  reset: () => {
    set(initialState);
  },
}));
