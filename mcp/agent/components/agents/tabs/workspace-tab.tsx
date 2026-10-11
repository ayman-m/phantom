"use client";

import * as React from "react";
import { apiRequest, listRequest } from "@/lib/api/client";

const glassStyle = {
  background: "var(--glass-bg-strong)",
  backdropFilter: "blur(12px)",
  border: "0.5px solid var(--glass-border)",
} as const;

interface WorkspaceFile {
  name: string;
  path: string;
  size: number;
  modified: string;
  type: string;
}

interface WorkspaceTabProps {
  agentId: string;
}

function getFileIcon(name: string): { icon: string; color: string } {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  switch (ext) {
    case "pdf":
      return { icon: "picture_as_pdf", color: "text-error" };
    case "csv":
      return { icon: "table_chart", color: "text-[#7bdc7b]" };
    case "json":
      return { icon: "data_object", color: "text-tertiary" };
    case "txt":
    case "md":
      return { icon: "description", color: "text-on-surface-variant" };
    case "py":
    case "js":
    case "ts":
    case "go":
      return { icon: "code", color: "text-primary" };
    case "png":
    case "jpg":
    case "jpeg":
    case "gif":
    case "svg":
      return { icon: "image", color: "text-secondary" };
    default:
      return { icon: "insert_drive_file", color: "text-on-surface-variant" };
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export function WorkspaceTab({ agentId }: WorkspaceTabProps) {
  const [files, setFiles] = React.useState<WorkspaceFile[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const fetchFiles = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await listRequest<WorkspaceFile>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/workspace`,
    );
    setLoading(false);
    if (result.ok) {
      setFiles(result.data);
    } else {
      // Treat 404 as empty workspace
      if (result.error.code === "HTTP_404") {
        setFiles([]);
      } else {
        setError(result.error.message);
      }
    }
  }, [agentId]);

  React.useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  async function handleUpload(file: File) {
    const formData = new FormData();
    formData.append("file", file);

    // For workspace upload, use a raw fetch since apiRequest serializes JSON
    try {
      const path = `/api/v1/agents/${encodeURIComponent(agentId)}/workspace/${encodeURIComponent(file.name)}`;
      const isClient = typeof window !== "undefined";
      const url = isClient
        ? `/api/proxy/v1/agents/${encodeURIComponent(agentId)}/workspace/${encodeURIComponent(file.name)}`
        : path;

      await fetch(url, {
        method: "PUT",
        body: formData,
      });
      fetchFiles();
    } catch {
      // Silently handle upload errors for now
    }
  }

  async function handleDelete(filePath: string) {
    const result = await apiRequest<void>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/workspace/${encodeURIComponent(filePath)}`,
      { method: "DELETE" },
    );
    if (result.ok) {
      setFiles((prev) => prev.filter((f) => f.path !== filePath));
    }
  }

  const totalSize = files.reduce((sum, f) => sum + f.size, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h3 className="text-xs font-label uppercase tracking-widest text-on-surface-variant">
            Agent Workspace
          </h3>
          <div className="flex items-center gap-4 text-[10px] font-mono text-on-surface-variant/50">
            <span>{files.length} files</span>
            <span>{formatFileSize(totalSize)} used</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg font-label font-bold text-xs uppercase tracking-widest text-on-primary-container transition-all hover:scale-[1.02] active:scale-95"
          style={{
            background: "linear-gradient(135deg, #1963b3 0%, #2d8df0 100%)",
          }}
        >
          <span className="material-symbols-outlined text-base">
            upload_file
          </span>
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleUpload(file);
            e.target.value = "";
          }}
        />
      </div>

      {/* File Table */}
      <div className="rounded-xl overflow-hidden" style={glassStyle}>
        {loading ? (
          <div className="p-8 text-center">
            <p className="text-sm text-on-surface-variant">
              Loading workspace files...
            </p>
          </div>
        ) : error ? (
          <div className="p-8 text-center">
            <p className="text-sm text-error">{error}</p>
            <button
              type="button"
              onClick={fetchFiles}
              className="mt-2 text-xs text-primary hover:underline"
            >
              Retry
            </button>
          </div>
        ) : files.length === 0 ? (
          <div className="p-8 text-center space-y-2">
            <span className="material-symbols-outlined text-3xl text-on-surface-variant/30">
              folder_off
            </span>
            <p className="text-sm text-on-surface-variant">
              No files in workspace
            </p>
            <p className="text-xs text-on-surface-variant/60">
              Upload files to make them available during agent task runs.
            </p>
          </div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant border-b border-white/[0.06]">
                <th className="px-5 py-3 font-semibold w-10" />
                <th className="px-5 py-3 font-semibold">Name</th>
                <th className="px-5 py-3 font-semibold">Size</th>
                <th className="px-5 py-3 font-semibold">Modified</th>
                <th className="px-5 py-3 font-semibold w-20" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {files.map((file) => {
                const fi = getFileIcon(file.name);
                return (
                  <tr
                    key={file.path}
                    className="group hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="px-5 py-3">
                      <span
                        className={`material-symbols-outlined text-base ${fi.color}`}
                      >
                        {fi.icon}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-sm font-mono text-on-surface">
                        {file.name}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-sm text-on-surface-variant">
                      {formatFileSize(file.size)}
                    </td>
                    <td className="px-5 py-3 text-sm text-on-surface-variant">
                      {formatDate(file.modified)}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={() => handleDelete(file.path)}
                          className="p-1 rounded text-on-surface-variant hover:text-error transition-colors"
                          aria-label={`Delete ${file.name}`}
                        >
                          <span className="material-symbols-outlined text-base">
                            delete
                          </span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Info Banner */}
      <div
        className="flex items-start gap-3 rounded-xl px-5 py-4"
        style={glassStyle}
      >
        <span className="material-symbols-outlined text-base text-primary mt-0.5">
          info
        </span>
        <p className="text-xs text-on-surface-variant leading-relaxed">
          Workspace files are accessible by the agent during task runs. Files are
          automatically mounted in the agent sandbox and can be read or written
          by sandbox tools (file_read, file_write).
        </p>
      </div>

      {/* Context Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          {
            icon: "lock",
            title: "Encryption",
            desc: "All workspace files are encrypted at rest using AES-256.",
          },
          {
            icon: "sync",
            title: "Sync Status",
            desc: "Files are synced to the agent sandbox before each run.",
          },
          {
            icon: "history",
            title: "History",
            desc: "File versions are retained for 30 days after deletion.",
          },
        ].map((card) => (
          <div
            key={card.title}
            className="rounded-xl p-4 space-y-2"
            style={glassStyle}
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-base text-on-surface-variant">
                {card.icon}
              </span>
              <h4 className="text-xs font-label font-bold uppercase tracking-widest text-on-surface-variant">
                {card.title}
              </h4>
            </div>
            <p className="text-xs text-on-surface-variant/60">{card.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
