export interface MCPTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface MCPToolResult {
  content: Array<{ type?: string; text: string }>;
  structuredContent?: unknown;
  isError?: boolean;
}

export class PhantomMCPClient {
  private readonly mcpUrl: string;
  private readonly mcpToken?: string;
  /**
   * Per-instance headers attached to every MCP request. Used today
   * for `X-Phantom-Trigger` so a scheduled chat's downstream tool
   * calls inherit the trigger tag for audit attribution. Reserved
   * names (Content-Type, Accept, Authorization, mcp-session-id,
   * mcp-protocol-version) take precedence over extras to avoid the
   * caller accidentally breaking transport semantics.
   */
  private readonly extraHeaders: Record<string, string>;
  private sessionId?: string;
  private protocolVersion?: string;
  private initPromise?: Promise<void>;

  constructor(
    mcpUrl: string,
    mcpToken?: string,
    extraHeaders?: Record<string, string>,
  ) {
    this.mcpUrl = mcpUrl;
    this.mcpToken = mcpToken;
    this.extraHeaders = extraHeaders ?? {};
  }

  private headers(): Record<string, string> {
    // Start with extras so reserved names below cleanly override them.
    const headers: Record<string, string> = { ...this.extraHeaders };
    headers["Content-Type"] = "application/json";
    headers["Accept"] = "text/event-stream, application/json";

    if (this.mcpToken) headers.Authorization = this.mcpToken;
    if (this.sessionId) headers["mcp-session-id"] = this.sessionId;
    if (this.protocolVersion) headers["mcp-protocol-version"] = this.protocolVersion;

    return headers;
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    const contentType = response.headers.get("content-type") || "";
    const sessionId = response.headers.get("mcp-session-id");
    if (sessionId) this.sessionId = sessionId;

    if (contentType.includes("text/event-stream")) {
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Empty MCP SSE response body");
      const decoder = new TextDecoder();
      let buffer = "";
      let lastEvent: T | null = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload || payload === "[DONE]") continue;
          try {
            lastEvent = JSON.parse(payload) as T;
          } catch {
            continue;
          }
        }
      }

      if (!lastEvent) throw new Error("No MCP SSE event payload received");
      return lastEvent;
    }

    return (await response.json()) as T;
  }

  private async initializeIfNeeded(): Promise<void> {
    if (this.sessionId && this.protocolVersion) return;
    if (this.initPromise) return this.initPromise;

    this.initPromise = (async () => {
      const response = await fetch(this.mcpUrl, {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: Date.now(),
          method: "initialize",
          params: {
            protocolVersion: "2025-06-18",
            capabilities: {},
            clientInfo: { name: "phantom-agent", version: "1.0.0" },
          },
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to initialize MCP session: ${response.status} ${response.statusText}`);
      }

      const payload = await this.parseResponse<{ result?: { protocolVersion?: string } }>(response);
      if (payload?.result?.protocolVersion) this.protocolVersion = payload.result.protocolVersion;

      await fetch(this.mcpUrl, {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "notifications/initialized",
          params: null,
        }),
      });
    })();

    return this.initPromise;
  }

  async listTools(): Promise<MCPTool[]> {
    await this.initializeIfNeeded();
    const response = await fetch(this.mcpUrl, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: Date.now(),
        method: "tools/list",
        params: null,
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to list MCP tools: ${response.status} ${response.statusText}`);
    }

    const payload = await this.parseResponse<{ result?: { tools?: MCPTool[] } }>(response);
    return payload.result?.tools || [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<MCPToolResult> {
    await this.initializeIfNeeded();
    const response = await fetch(this.mcpUrl, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: Date.now(),
        method: "tools/call",
        params: { name, arguments: args },
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to call MCP tool ${name}: ${response.status} ${response.statusText}`);
    }

    const payload = await this.parseResponse<{ result: MCPToolResult }>(response);
    return payload.result;
  }
}
