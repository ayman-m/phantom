"""Validate the codebase-search MCP server with a real stdio handshake.

Spawns the server exactly as `.mcp.json` would, completes the MCP handshake,
lists tools, and actually calls all three — proving the server does real
AST-based structured search end to end, not just that the file imports.

Phantom-specific: the call-time assertions reference real symbols that live
in `bundles/spark/mcp/src/api/data_sources.py` so any breakage in the
codebase-search index gets caught.

Run via:  python3 tooling/validate/check_mcp.py
Exit:     0 if handshake + tool calls return real AST results, 1 otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class McpClient:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            ["python3", "tooling/mcp/codebase_search.py"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, message: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def recv(self, want_id: int) -> dict:
        assert self.proc.stdout
        for _ in range(100):
            line = self.proc.stdout.readline()
            if not line:
                # Surface the child's stderr. Without this a plain
                # ImportError reads as "closed the stream" and the real
                # one-line cause never reaches the CI log.
                err = ""
                if self.proc.stderr:
                    try:
                        err = self.proc.stderr.read() or ""
                    except Exception:
                        pass
                raise RuntimeError(
                    "MCP server closed the stream"
                    + (f" — stderr: {err.strip()}" if err.strip() else "")
                )
            message = json.loads(line)
            if message.get("id") == want_id:
                return message
        raise RuntimeError(f"no response with id {want_id}")

    def call(self, call_id: int, tool: str, arguments: dict) -> str:
        self.send(
            {
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        return self.recv(call_id)["result"]["content"][0]["text"]

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    client = McpClient()
    try:
        client.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "phantom-validate", "version": "1.0"},
                },
            }
        )
        init = client.recv(1)
        server_name = init.get("result", {}).get("serverInfo", {}).get("name", "?")
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = [t["name"] for t in client.recv(2)["result"]["tools"]]
        expected = {"where_is", "find_references", "outline"}
        if not expected.issubset(tools):
            print(f"FAIL: expected structured tools {sorted(expected)} — got {tools}")
            return 1

        # where_is — must structurally locate compose_data_source_id, a real
        # function in bundles/spark/mcp/src/api/data_sources.py.
        where_text = client.call(3, "where_is", {"name": "compose_data_source_id"})
        if "data_sources" not in where_text or "[function]" not in where_text:
            print(
                f"FAIL: where_is did not structurally locate "
                f"compose_data_source_id — {where_text!r}"
            )
            return 1

        # find_references — the same function is called from multiple places
        # in the data_sources REST surface; at least one [call] reference
        # must surface.
        refs_text = client.call(
            4, "find_references", {"name": "compose_data_source_id"}
        )
        if "[call]" not in refs_text:
            print(
                f"FAIL: find_references did not find a call site for "
                f"compose_data_source_id — {refs_text!r}"
            )
            return 1

        # outline — module-level API for data_sources.py must list a few
        # known top-level functions. compose_data_source_id is IMPORTED into
        # this file (defined in usecase/data_sources_store.py) so outline
        # won't list it; assert on the functions that ARE defined here.
        outline_text = client.call(5, "outline", {"module": "data_sources"})
        if (
            "data_sources_list" not in outline_text
            or "data_sources_install" not in outline_text
        ):
            print(
                f"FAIL: outline did not return the data_sources module API "
                f"— {outline_text!r}"
            )
            return 1

        print(
            f"PASS: MCP server '{server_name}' — handshake ok, tools {tools}; "
            f"where_is + find_references + outline returned real AST results"
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
