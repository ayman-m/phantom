import { apiRequest, listRequest, type ApiResult } from "./client";

export interface WorkspaceFile {
  name: string;
  size: number;
  last_modified: string;
}

/** List all files in an agent's workspace. */
export async function listWorkspaceFiles(
  agentId: string,
  options?: { token?: string },
): Promise<ApiResult<WorkspaceFile[]>> {
  return listRequest<WorkspaceFile>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/workspace`,
    { token: options?.token },
  );
}

/** Get a download URL for a workspace file. */
export function getWorkspaceFileUrl(agentId: string, path: string): string {
  return `/api/v1/agents/${encodeURIComponent(agentId)}/workspace/${path}`;
}

/** Download a workspace file as a blob. */
export async function downloadWorkspaceFile(
  agentId: string,
  path: string,
  options?: { token?: string },
): Promise<ApiResult<Blob>> {
  const url = getWorkspaceFileUrl(agentId, path);

  try {
    const headers: Record<string, string> = {};
    if (options?.token) {
      headers["Authorization"] = `Bearer ${options.token}`;
    }

    const response = await fetch(url, { headers });
    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: `HTTP_${response.status}`,
          message: response.statusText || "Download failed",
          retryable: response.status >= 500,
        },
      };
    }

    const blob = await response.blob();
    return { ok: true, data: blob };
  } catch (error: unknown) {
    return {
      ok: false,
      error: {
        code: "NETWORK_ERROR",
        message: error instanceof Error ? error.message : "Network error",
        retryable: true,
      },
    };
  }
}

/** Upload a file to an agent's workspace. */
export async function uploadWorkspaceFile(
  agentId: string,
  path: string,
  file: File,
  options?: { token?: string },
): Promise<ApiResult<{ status: string; path: string }>> {
  const url = `/api/v1/agents/${encodeURIComponent(agentId)}/workspace/${path}`;

  try {
    const headers: Record<string, string> = {
      "Content-Type": file.type || "application/octet-stream",
    };
    if (options?.token) {
      headers["Authorization"] = `Bearer ${options.token}`;
    }

    const response = await fetch(url, {
      method: "PUT",
      headers,
      body: file,
    });

    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: `HTTP_${response.status}`,
          message: response.statusText || "Upload failed",
          retryable: response.status >= 500,
        },
      };
    }

    const data = (await response.json()) as { status: string; path: string };
    return { ok: true, data };
  } catch (error: unknown) {
    return {
      ok: false,
      error: {
        code: "NETWORK_ERROR",
        message: error instanceof Error ? error.message : "Network error",
        retryable: true,
      },
    };
  }
}

/** Delete a file from an agent's workspace. */
export async function deleteWorkspaceFile(
  agentId: string,
  path: string,
  options?: { token?: string },
): Promise<ApiResult<void>> {
  return apiRequest<void>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/workspace/${path}`,
    { method: "DELETE", token: options?.token },
  );
}
