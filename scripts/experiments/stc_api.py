"""Helper: call stc-engine agent tool API through the local IAP tunnel."""
import os, json, ssl, urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASE = "https://localhost:3001"


def _key():
    return os.environ["PHANTOM_KEY"]


def call_tool(tool, arguments, timeout=60):
    payload = {"name": tool, "arguments": arguments}
    req = urllib.request.Request(
        BASE + "/api/agent/tool/call",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
    return json.load(r)


def tenant_xql(query, relative_ms=86400000, poll_s=3, max_polls=40):
    """Run XQL against the STC tenant directly (no tunnel needed)."""
    base = os.environ["STC_XSIAM_STANDARD_API_URL"].rstrip("/")
    hdrs = {
        "Authorization": os.environ["STC_XSIAM_STANDARD_API_KEY"],
        "x-xdr-auth-id": os.environ["STC_XSIAM_STANDARD_API_ID"],
        "Content-Type": "application/json",
    }

    def post(path, payload, timeout=30):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                     headers=hdrs, method="POST")
        return json.load(urllib.request.urlopen(req, timeout=timeout))

    r = post("/public_api/v1/xql/start_xql_query/",
             {"request_data": {"query": query, "timeframe": {"relativeTime": relative_ms}}})
    qid = r["reply"]
    import time
    for _ in range(max_polls):
        res = post("/public_api/v1/xql/get_query_results/",
                   {"request_data": {"query_id": qid, "pending_flag": True,
                                     "limit": 1000, "format": "json"}})
        st = res.get("reply", {}).get("status")
        if st == "SUCCESS":
            return res["reply"]["results"]["data"]
        if st == "FAIL":
            raise RuntimeError("XQL FAIL: " + json.dumps(res)[:500])
        time.sleep(poll_s)
    raise TimeoutError("XQL timed out: " + query[:80])
