#!/usr/bin/env python3
"""test_contract.py — black-box HTTP contract test for the Agent Floor bridge.

It talks to an ALREADY RUNNING bridge (bridge/agent_floor_bridge.py); it starts
nothing and resets nothing. Standard library only.

Flow (one real agent, one real event sequence):

    POST /event  register -> task -> progress -> file -> done   (agent "ContractTest")

then GET /status and assert the bridge really stored the result:
  * the agent exists under its name,
  * task cleared after done,
  * progress == 1.0,
  * the file name is present in that agent's files,
  * the floor log contains the "shipped <file>" line.

One PASS/FAIL line per check, a summary line, exit code 1 if any check failed.

    python bridge/tests/test_contract.py
    FLOOR_URL=http://127.0.0.1:8787 python bridge/tests/test_contract.py   # override target
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("FLOOR_URL", "http://127.0.0.1:8787").rstrip("/")
AGENT = "ContractTest"
AGENT_KEY = AGENT.lower()
FILE_PATH = "bridge/tests/test_contract.py"
FILE_BASE = os.path.basename(FILE_PATH)

PASSED = 0
FAILED = 0


def check(name, ok, detail=""):
    """Print one PASS/FAIL line and keep the count."""
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("PASS  %s" % name)
    else:
        FAILED += 1
        print("FAIL  %s%s" % (name, ("  -- " + detail) if detail else ""))
    return ok


def request(method, path, payload=None, timeout=5.0):
    """Return (http_status_or_None, decoded_json_or_error_dict)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            code = getattr(resp, "status", None) or resp.getcode()
            return code, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"_raw": body}
    except Exception as exc:  # noqa: BLE001  (refused, timeout, dropped connection ...)
        return None, {"_error": "%s: %s" % (type(exc).__name__, exc)}


def post_event(kind, **fields):
    return request("POST", "/event", dict(fields, event=kind))


def find_agent(status):
    for a in status.get("agents", []):
        if a.get("id") == AGENT_KEY or str(a.get("name", "")).lower() == AGENT_KEY:
            return a
    return None


def main():
    print("== Agent Floor bridge contract test ==")
    print("target: %s   agent: %s   file: %s" % (BASE, AGENT, FILE_BASE))

    code, health = request("GET", "/health")
    check("bridge reachable: GET /health -> 200 ok", code == 200 and health.get("ok") is True,
          "code=%s body=%s" % (code, json.dumps(health)[:200]))

    steps = [
        ("register", {"agent": AGENT, "role": "contract-test"}),
        ("task", {"agent": AGENT, "title": "Verify the bridge contract", "role": "contract-test"}),
        ("progress", {"agent": AGENT, "value": 0.5, "note": "halfway (test)"}),
        ("file", {"agent": AGENT, "file": FILE_PATH}),
        ("done", {"agent": AGENT}),
    ]
    for kind, fields in steps:
        code, body = post_event(kind, **fields)
        check("POST /event %-8s accepted" % kind,
              code == 200 and body.get("ok") is True,
              "code=%s body=%s" % (code, json.dumps(body)[:200]))

    code, status = request("GET", "/status")
    check("GET /status -> 200 with agents[]",
          code == 200 and isinstance(status.get("agents"), list),
          "code=%s" % code)

    agent = find_agent(status) if isinstance(status, dict) else None
    check("agent stored under its name (%s)" % AGENT,
          agent is not None and agent.get("name") == AGENT,
          "agent=%s" % json.dumps(agent)[:240])

    if agent is not None:
        check("task cleared after done", agent.get("task") == "",
              "task=%r" % agent.get("task"))
        try:
            progress_ok = abs(float(agent.get("progress", -1)) - 1.0) < 1e-9
        except (TypeError, ValueError):
            progress_ok = False
        check("progress reached 1.0", progress_ok,
              "progress=%r" % agent.get("progress"))
        check("file name present in agent's files", FILE_BASE in (agent.get("files") or []),
              "files=%r" % (agent.get("files"),))
    else:
        for name in ("task cleared after done", "progress reached 1.0",
                     "file name present in agent's files"):
            check(name, False, "no agent record in /status to inspect")

    floor = status.get("floor", {}).get("log", []) if isinstance(status, dict) else []
    shipped = [e for e in floor
               if isinstance(e, (list, tuple)) and len(e) >= 3
               and e[1] == AGENT and ("shipped " + FILE_BASE) in str(e[2])]
    check("floor log contains 'shipped %s'" % FILE_BASE, len(shipped) > 0,
          "no matching floor entry; newest entries: %s" % json.dumps(floor[:3])[:240])

    print("SUMMARY: %d passed, %d failed" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
