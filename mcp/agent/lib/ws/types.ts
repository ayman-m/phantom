/** Server hello message sent upon initial connection. */
export interface HelloMessage {
  type: "hello";
  version: string;
  connection_id: string;
}

/** Client subscribe message to join channels. */
export interface SubscribeMessage {
  type: "subscribe";
  channels: string[];
}

/** Client unsubscribe message to leave channels. */
export interface UnsubscribeMessage {
  type: "unsubscribe";
  channels: string[];
}

/** Client ping message for keepalive. */
export interface PingMessage {
  type: "ping";
  timestamp: number;
}

/** Server pong response to a ping. */
export interface PongMessage {
  type: "pong";
  timestamp: number;
}

/** Server event message dispatched on a channel. */
export interface EventMessage {
  type: "event";
  channel: string;
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

/** Union of all inbound (server-to-client) WebSocket messages. */
export type InboundMessage = HelloMessage | PongMessage | EventMessage;

/** Union of all outbound (client-to-server) WebSocket messages. */
export type OutboundMessage =
  | SubscribeMessage
  | UnsubscribeMessage
  | PingMessage;

/** Run event types dispatched on run:{runId} channels. */
export enum RunEventType {
  PARTIAL_TEXT = "PARTIAL_TEXT",
  REASONING_CHUNK = "REASONING_CHUNK",
  TOOL_CALL_STARTED = "TOOL_CALL_STARTED",
  TOOL_CALL_COMPLETED = "TOOL_CALL_COMPLETED",
  STATE_CHANGED = "STATE_CHANGED",
  COMPLETED = "COMPLETED",
  FAILED = "FAILED",
  CANCELLED = "CANCELLED",
}

/** Payload for PARTIAL_TEXT events. */
export interface PartialTextPayload {
  chunk: string;
}

/** Payload for REASONING_CHUNK events. */
export interface ReasoningChunkPayload {
  chunk: string;
}

/** Payload for TOOL_CALL_STARTED events. */
export interface ToolCallStartedPayload {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/** Payload for TOOL_CALL_COMPLETED events. */
export interface ToolCallCompletedPayload {
  id: string;
  result?: string;
  error?: string;
}

/** Payload for STATE_CHANGED events. */
export interface StateChangedPayload {
  state: string;
  approval_id?: string;
  tool?: string;
  description?: string;
}

/** Payload for COMPLETED events. */
export interface CompletedPayload {
  output?: string;
  usage?: { input_tokens?: number; output_tokens?: number };
}

/** Payload for FAILED events. */
export interface FailedPayload {
  error: string;
  code?: string;
}
