/** API error envelope returned by the api-gateway. */
export interface ApiError {
  code: string;
  message: string;
  retryable: boolean;
}

/** Overall platform health response from GET /health. */
export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  uptime: number;
}

/** Individual service status within the platform. */
export interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "unhealthy";
  responseTime: number;
  lastChecked: string;
}

/** Agent configuration for model selection. */
export interface AgentModelConfig {
  defaultModel?: string | null;
  fallbackModels?: string[];
  thinkLevel?: "none" | "low" | "medium" | "high";
}

/** Agent configuration for tool access control. */
export interface AgentToolsConfig {
  allowedTools?: string[];
  deniedTools?: string[];
}

/** Agent configuration for skills. */
export interface AgentSkillsConfig {
  enabledSkills?: string[];
}

/** Agent definition. */
/**
 * Agent definition.
 * Supports both proto-JSON wire format (snake_case: agent_id, created_at)
 * and the legacy camelCase format used by older UI code.
 */
export interface Agent {
  // Proto-JSON fields (snake_case) — populated by the API
  agent_id: string;
  name: string;
  description: string;
  default_model?: { provider?: string; model?: string } | null;
  fallback_models?: { provider?: string; model?: string }[];
  think_level?: string;
  tool_allow?: string[];
  tool_deny?: string[];
  system_prompt_template?: string;
  standing_orders?: string;
  metadata?: Record<string, unknown> | null;
  version?: number;
  created_at?: string;
  updated_at?: string;

  // Legacy camelCase fields — still used by some UI components and tests
  id?: string;
  status?: "active" | "inactive" | "error";
  model?: string | null;
  systemPrompt?: string | null;
  modelConfig?: AgentModelConfig | null;
  toolsConfig?: AgentToolsConfig | null;
  skillsConfig?: AgentSkillsConfig | null;
  sessionCount?: number;
  lastActiveAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

/** Request body for updating an agent. */
export interface UpdateAgentRequest {
  name?: string;
  description?: string;
  standing_orders?: string;
  systemPrompt?: string | null;
  model?: string | null;
  modelConfig?: AgentModelConfig | null;
  toolsConfig?: AgentToolsConfig | null;
  skillsConfig?: AgentSkillsConfig | null;
}

/** Session tied to an agent. */
export interface Session {
  session_id: string;
  session_key: string;
  agent_id: string;
  run_count: string;
  total_input_tokens: string;
  total_output_tokens: string;
  last_model: string;
  metadata: Record<string, unknown> | null;
  version: string;
  created_at: string;
  updated_at: string;
  last_active_at: string;
}

/** A single execution run within a session. */
export interface Run {
  id: string;
  sessionId: string;
  agentId: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  input: string;
  output: string | null;
  startedAt: string;
  completedAt: string | null;
  error: string | null;
}

/** Event emitted during a run (streamed via WebSocket). */
export interface RunEvent {
  id: string;
  runId: string;
  type: "tool_call" | "tool_result" | "message" | "error" | "status_change";
  data: Record<string, unknown>;
  timestamp: string;
}

/** External connector (e.g. Slack, GitHub). */
export interface Connector {
  id: string;
  name: string;
  type: string;
  status: "connected" | "disconnected" | "error";
  config: Record<string, unknown>;
  createdAt: string;
}

/** Configuration section value with optimistic concurrency hash. */
export interface ConfigValue {
  path: string;
  value: unknown;
  hash: string;
}

/** Tool metadata returned by the tools catalog. */
export interface ToolDescriptor {
  name: string;
  description: string;
  inputSchema: unknown;
  group: string;
}

/** Skill metadata with runtime eligibility details. */
export interface SkillDescriptor {
  name: string;
  displayName: string;
  description: string;
  source: "bundled" | "managed" | "workspace";
  precedence: number;
  eligibility: {
    eligible: boolean;
    requiredEnv: string[];
    requiredBins: string[];
    requiredOs: string[];
    reason?: string;
  };
}

/** Interaction pattern supported by a model. */
export type InteractionPattern =
  | "streaming_api"
  | "cli_tool"
  | "async_job"
  | "interactive_session";

/** Model kind — used to split /models into tabs (Chat, Embedding, Image, Voice). */
export type ModelKind = "chat" | "embedding" | "image" | "voice";

/** Available model capabilities for a provider. */
export interface ModelInfo {
  provider: string;
  model: string;
  displayName?: string;
  contextWindow: number;
  supportsThinking: boolean;
  supportsTools: boolean;
  /** Classification from the gateway's classifyModel() — defaults to "chat" for unknowns. */
  kind?: ModelKind;
  /** Vertex-only: "GA", "PUBLIC_PREVIEW", etc. Gives the UI a signal for preview-tier badging. */
  launchStage?: string;
  createdAt?: string;
  interactionPatterns?: InteractionPattern[];
  /**
   * When true, the model is listed in the catalog but not
   * yet wired through the chat-route. The chat header's model dropdown
   * filters these out; the /services Models page surfaces them with a
   * greyed-out "Coming soon" treatment so operators see the roadmap
   * without being able to pick a model that would fail at send time.
   */
  wip?: boolean;
}

/** Structured platform log entry. */
export interface LogEntry {
  timestamp: string;
  level: string;
  source: string;
  runId?: string;
  message: string;
}

/** Approval request for a tool execution. */
export interface Approval {
  id: string;
  runId: string;
  agentId: string;
  toolName: string;
  description: string;
  status: "pending" | "approved" | "denied" | "expired";
  createdAt: string;
  resolvedAt?: string;
  /** Surface that initiated the request. Drives where the
   *  resolver UI lights up — chat-origin gets an inline approval card
   *  in that chat session; everything else surfaces in /approvals.
   *  Format:
   *    "chat:<session_id>"   → chat-origin (resolve inline; /approvals
   *                            still shows the row for audit)
   *    "job:<job_name>"      → scheduled job
   *    "api"                 → REST/MCP direct call
   *    "operator"            → UI-initiated mutation
   *    "unknown"             → legacy rows with no origin
   */
  origin?: string;
}

/** Agent activity statistics returned by GET /api/v1/agents/:id/stats. */
export interface AgentStats {
  agent_id: string;
  window: string;
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  success_rate: number;
  active_sessions: number;
  recent_runs: RecentRun[];
}

/** Minimal run info included in agent stats recent_runs. */
export interface RecentRun {
  run_id: string;
  session_id: string;
  agent_id: string;
  state: number;
  input_text?: string;
  created_at?: string;
  completed_at?: string;
  token_usage?: {
    input_tokens: number;
    output_tokens: number;
  };
}

/** Model usage statistics returned by GET /api/v1/models/:model/stats. */
export interface ModelStats {
  provider: string;
  model: string;
  window: string;
  total_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  avg_duration_ms: number;
  last_used_at: string | null;
}

/** Request body for creating an agent. */
export interface CreateAgentRequest {
  name: string;
  description: string;
  model?: string;
  systemPrompt?: string;
}

/** Options for creating a run. */
export interface CreateRunOptions {
  model?: string;
  thinkLevel?: "none" | "low" | "medium" | "high";
}

/** Resolution payload for resolving an approval. */
export interface ApprovalResolution {
  resolution: "approved" | "denied";
  resolvedBy?: string;
}
