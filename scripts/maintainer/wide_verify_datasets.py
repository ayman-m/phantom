#!/usr/bin/env python3
"""Reusable wide-window dataset re-verification for the validated data sources.

Runs INSIDE phantom_agent (reaches the xsiam connector on the docker network):

    docker exec -i phantom_agent python3 - < scripts/maintainer/wide_verify_datasets.py

For each dataset in the validated vendor list it reports landing + XDM:

  * landing  — `config timeframe = 30d | dataset = <ds> | sort desc _time | limit 1`
  * XDM      — distinct non-null `xdm.*` fields across UP TO 20 rows of
               `... | datamodel dataset = <ds> | sort desc _time | fields xdm.* | limit 20`

Two rules are baked in:

  1. **run_xql_query takes a single FLAT `query` string.** A
     `{"request": {"query": …, "tenant_timeframe": …}}` wrapper is rejected by
     the connector's Pydantic model ("Unexpected keyword argument") — the
     lookback window goes INLINE via `config timeframe = …`. Passing the wrapped
     shape silently returns no results.
  2. **Count distinct xdm.* across >=20 rows, not the single newest row.** A
     `limit 1` sample undercounts badly — one synthetic event can map 0 fields
     while the dataset's recent events map 40. The union over ~20 rows is the
     honest saturation figure.

Reads the dataset list from /app/data/agent_smoke_state.json when present;
otherwise falls back to the 22 validated datasets.
"""
import json, os, time, urllib.request
from pathlib import Path

TOKEN = os.environ["MCP_TOKEN"]
XSIAM_MCP = "http://phantom-connector-xsiam-Cortex_XSIAM:9000/mcp"
STATE = Path("/app/data/agent_smoke_state.json")
WINDOW = os.environ.get("VERIFY_WINDOW", "30d")
ROW_SAMPLE = int(os.environ.get("VERIFY_ROWS", "20"))

_FALLBACK = [
    "okta_okta_raw", "okta_sso_raw", "alibaba_action_trail_raw", "amazon_aws_raw",
    "aws_security_hub_raw", "aws_waf_raw", "atlassian_jira_raw",
    "servicenow_servicenow_raw", "cyberark_isp_raw", "msft_azure_ad_audit_raw",
    "msft_azure_ad_raw", "msft_o365_general_raw", "msft_o365_exchange_online_raw",
    "msft_o365_sharepoint_online_raw", "msft_o365_emails_raw", "msft_o365_dlp_raw",
    "qualys_qualys_raw", "proofpoint_email_security_raw", "proofpoint_tap_raw",
    "msft_azure_flowlogs_raw", "msft_azure_waf_raw", "msft_azure_aks_raw",
]


def post(url, body, sid=None):
    h = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["mcp-session-id"] = sid
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode(), r.headers


def sse_tool_json(text):
    for ln in text.split("\n"):
        if ln.startswith("data:"):
            try:
                f = json.loads(ln[5:].strip())
                if "result" in f:
                    c = f["result"].get("content", [])
                    if c:
                        t = c[0].get("text", "{}")
                        if f["result"].get("isError"):
                            return {"_err": t[:160]}
                        try:
                            return json.loads(t)
                        except json.JSONDecodeError:
                            return {"_raw": t[:160]}
                if "error" in f:
                    return {"_err": str(f["error"])[:160]}
            except Exception:
                pass
    return {}


def open_session(url):
    _, hdrs = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "wide-verify", "version": "1"}}})
    sid = hdrs.get("mcp-session-id") or hdrs.get("Mcp-Session-Id")
    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, sid)
    return sid


def xql(sid, q, rid=200):
    body, _ = post(XSIAM_MCP, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                               "params": {"name": "run_xql_query",
                                          "arguments": {"query": q}}}, sid)
    return sse_tool_json(body)


def datasets():
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
            out = []
            for slug, v in st.get("vendors", {}).items():
                out.append(v.get("dataset") or "__".join(slug.split("__")[2:]))
            if out:
                return out
        except Exception:
            pass
    return _FALLBACK


def verify(sid, ds):
    raw = xql(sid, f"config timeframe = {WINDOW} | dataset = {ds} | sort desc _time | limit 1", 200)
    rep = raw.get("reply", {}) if isinstance(raw, dict) else {}
    n_raw = rep.get("number_of_results", 0) if isinstance(rep, dict) else 0
    mr = "-"
    if n_raw:
        try:
            t = int(rep["results"]["data"][0].get("_time", 0)) // 1000
            mr = time.strftime("%m-%d %H:%M", time.gmtime(t))
        except Exception:
            pass
    xdm_n = xdm_rows = 0
    if n_raw:
        dm = xql(sid, f"config timeframe = {WINDOW} | datamodel dataset = {ds} | "
                      f"sort desc _time | fields xdm.* | limit {ROW_SAMPLE}", 201)
        dmr = dm.get("reply", {}) if isinstance(dm, dict) else {}
        if dmr.get("number_of_results", 0):
            data = dmr.get("results", {}).get("data", [])
            xdm_rows = len(data)
            fields = set()
            for row in data:
                for k, val in row.items():
                    if k.startswith("xdm.") and val not in (None, "", "null"):
                        fields.add(k)
            xdm_n = len(fields)
    return {"raw": n_raw, "xdm": xdm_n, "rows": xdm_rows, "most_recent": mr}


if __name__ == "__main__":
    sid = open_session(XSIAM_MCP)
    dss = datasets()
    print(f"sid={sid}  window={WINDOW}  row_sample={ROW_SAMPLE}\n")
    print(f"{'dataset':42s} {'raw':>4s} {'xdmDistinct':>11s} {'rows':>5s} {'recent':>12s}")
    print("-" * 80)
    land = xdmok = 0
    out = {}
    for ds in dss:
        r = verify(sid, ds)
        out[ds] = r
        if r["raw"]:
            land += 1
        if r["xdm"] > 0:
            xdmok += 1
        print(f"{ds:42s} {str(r['raw']):>4s} {str(r['xdm']):>11s} {str(r['rows']):>5s} {r['most_recent']:>12s}")
    print("-" * 80)
    xs = sorted(v["xdm"] for v in out.values() if v["xdm"] > 0)
    if xs:
        print(f"LANDED {land}/{len(dss)}  XDM>0 {xdmok}/{len(dss)}  "
              f"(xdm min={xs[0]} max={xs[-1]} mean={sum(xs)/len(xs):.1f} median={xs[len(xs)//2]})")
