import { listRequest } from "./client";
import type { ApiRequestOptions } from "./client";
import type { ToolDescriptor } from "./types";

/** List registered tools from GET /api/v1/tools. */
export function listTools(options?: ApiRequestOptions) {
  return listRequest<ToolDescriptor>("/api/v1/tools", options);
}
