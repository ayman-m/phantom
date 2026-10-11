import { NextRequest, NextResponse } from "next/server";

import { PhantomMCPClient } from "@/lib/mcp-client";
import { proxyToMcp } from "@/lib/mcp-proxy";
import { getEffectiveRuntimeConfig } from "@/lib/runtime-config";

export const dynamic = "force-dynamic";

type SkillListItem = {
  name: string;
  category: string;
  file_path: string;
  size_bytes?: number;
  modified_at?: string;
};

const parseToolResult = <T,>(result: { content: Array<{ text: string }> }): T => {
  const raw = result.content?.[0]?.text || "{}";
  return JSON.parse(raw) as T;
};

export async function GET(request: NextRequest) {
  try {
    const runtimeConfig = await getEffectiveRuntimeConfig();
    const mcpClient = new PhantomMCPClient(runtimeConfig.MCP_URL, runtimeConfig.MCP_TOKEN);
    const { searchParams } = new URL(request.url);
    const filePath = searchParams.get("file_path");

    if (filePath) {
      const result = await mcpClient.callTool("skills_read", { file_path: filePath });
      const parsed = parseToolResult<{ success: boolean; content?: string; error?: string }>(result);
      return NextResponse.json(parsed);
    }

    const result = await mcpClient.callTool("skills_list_all", {});
    const skills = parseToolResult<SkillListItem[]>(result);
    return NextResponse.json({ success: true, skills });
  } catch (error) {
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { category, filename, content } = body || {};

    if (!category || !filename || !content) {
      return NextResponse.json(
        { success: false, error: "category, filename, and content are required." },
        { status: 400 }
      );
    }

    const runtimeConfig = await getEffectiveRuntimeConfig();
    const mcpClient = new PhantomMCPClient(runtimeConfig.MCP_URL, runtimeConfig.MCP_TOKEN);
    const result = await mcpClient.callTool("skills_create", {
      category,
      filename,
      content,
    });
    const parsed = parseToolResult<{ success: boolean; message?: string; error?: string }>(result);
    return NextResponse.json(parsed);
  } catch (error) {
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}

export async function PUT(request: NextRequest) {
  try {
    const body = await request.json();
    const { file_path, content } = body || {};

    if (!file_path || !content) {
      return NextResponse.json(
        { success: false, error: "file_path and content are required." },
        { status: 400 }
      );
    }

    const runtimeConfig = await getEffectiveRuntimeConfig();
    const mcpClient = new PhantomMCPClient(runtimeConfig.MCP_URL, runtimeConfig.MCP_TOKEN);
    const result = await mcpClient.callTool("skills_update", {
      file_path,
      content,
    });
    const parsed = parseToolResult<{ success: boolean; message?: string; error?: string }>(result);
    return NextResponse.json(parsed);
  } catch (error) {
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  // Operator-direct soft-delete. Proxies to the MCP REST endpoint
  // (`bundles/spark/mcp/src/api/skills.py:delete_skill`) which calls
  // the underlying ungated `skills_crud.skills_delete` directly,
  // bypassing the `skills_delete` gated tool wrapper that
  // exists for the chat-agent's self-mod path. Same architectural
  // pattern jobs/instances/providers already use — operator-direct
  // UI clicks ARE the approval, no separate /approvals queue
  // acknowledgement needed. See api/skills.py docstring for the
  // architectural background.
  //
  // This goes through the REST endpoint rather than the MCP tool
  // `skills_delete`, which would hit the approval gate. The
  // file_path arrives as a query string per the legacy contract;
  // the REST endpoint takes it as a path-suffix parameter.
  const { searchParams } = new URL(request.url);
  const filePath = searchParams.get("file_path");
  if (!filePath) {
    return NextResponse.json(
      { success: false, error: "file_path is required." },
      { status: 400 },
    );
  }
  // Path-encode each segment but keep the slashes (the REST endpoint
  // declares the param as `{file_path:path}` so slashes are part of
  // the value, not the route boundary).
  const encoded = filePath
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
  return proxyToMcp(request, `/api/v1/skills/${encoded}`);
}
