#!/usr/bin/env python3
"""agent_floor_bridge.py — feed the Agent Floor scene with real agent activity.

It serves two things on one local port:

  GET  /                 the floor scene (原型/V* Agent-Floor.html)
  GET  /status           JSON snapshot the scene polls (real state)
  GET  /health           liveness + counts
  POST /event            ingest one event: {"event":"task|progress|file|state|done|log|register", "agent":"Nadia", ...}
  POST /reset            clear the floor

Real sources can also be picked up without touching their code:

  --watch NAME=DIR       any file written under DIR is reported as NAME shipping it
  --tail events.jsonl    append-only JSONL, one event object per line

Nothing is simulated here: whatever arrives is what the floor shows.
Standard library only. Binds to 127.0.0.1 unless you say otherwise.
"""
import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

MAX_FLOOR_LOG = 60
MAX_AGENT_LOG = 8
MAX_FILES = 6
STATES = ("working", "focus", "meeting", "break", "aisle", "idle", "waiting", "offline")
TASK_KINDS = ("note", "table", "check", "inventory")
MAX_QUEUE = 20
NEXT_ID = [1]

STATE = {
    "source": "agent-floor-bridge",
    "started": time.time(),
    "updated": time.time(),
    "clock": None,
    "floor": {"log": []},
    "agents": {},
}
LOCK = threading.RLock()   # re-entrant: apply_event may call assign() which locks too
ARGS = None
HTML = {"path": None, "body": None, "mtime": 0.0}


def clock_now():
    return time.strftime("%H:%M")


def key_of(name):
    return (name or "agent").strip().lower()


def log_floor(who, text):
    if not text:
        return
    STATE["floor"]["log"].insert(0, [clock_now(), who or "Floor", str(text)])
    del STATE["floor"]["log"][MAX_FLOOR_LOG:]


def log_agent(a, text):
    if not text:
        return
    a["log"].insert(0, [clock_now(), str(text)])
    del a["log"][MAX_AGENT_LOG:]


def agent_of(name, role=None, desk=None):
    k = key_of(name)
    a = STATE["agents"].get(k)
    if a is None:
        a = {"id": k, "name": (name or "agent").strip(), "role": role or "", "desk": desk,
             "state": "working", "task": "", "progress": 0.0, "files": [], "log": [], "tasks": [],
             "skills": [], "shiftFrom": "", "shiftTo": "", "updated": time.time()}
        STATE["agents"][k] = a
    for f, d in (("skills", []), ("shiftFrom", ""), ("shiftTo", "")):
        a.setdefault(f, d)
    if role:
        a["role"] = role
    if desk is not None:
        try:
            a["desk"] = int(desk)
        except (TypeError, ValueError):
            pass
    return a


def find_agent(key):
    """Resolve an agent by stable id first, then by current display name (survives renames)."""
    k = str(key or "").strip().lower()
    if not k:
        return None
    if k in STATE["agents"]:
        return STATE["agents"][k]
    for a in STATE["agents"].values():
        if a["name"].strip().lower() == k:
            return a
    return None


def hhmm(value, default):
    try:
        h, m = str(value).split(":")
        return int(h) * 60 + int(m[:2])
    except Exception:  # noqa: BLE001
        return default


def valid_shift_time(value):
    if not value:
        return True
    parts = str(value).split(":")
    if len(parts) != 2 or any(len(part) != 2 or not part.isdigit() for part in parts):
        return False
    hour, minute = (int(part) for part in parts)
    return 0 <= hour < 24 and 0 <= minute < 60


def on_shift(a):
    """Empty shift = always on. Handles windows that cross midnight."""
    f, t = a.get("shiftFrom") or "", a.get("shiftTo") or ""
    if not f or not t:
        return True
    now = time.localtime()
    n = now.tm_hour * 60 + now.tm_min
    f2, t2 = hhmm(f, 0), hhmm(t, 24 * 60)
    return (f2 <= n < t2) if f2 <= t2 else (n >= f2 or n < t2)


def update_agent(name, ev):
    for field in ("shiftFrom", "shiftTo"):
        value = str(ev.get(field) or "").strip()
        if field in ev and not valid_shift_time(value):
            return {"ok": False, "error": "%s must be empty or a valid HH:MM time" % field}
    with LOCK:
        a = find_agent(name) or agent_of(name)
        old = a["name"]
        if ev.get("name"):
            a["name"] = str(ev["name"]).strip()[:40] or a["name"]
        if "skills" in ev:
            sk = ev["skills"]
            if isinstance(sk, str):
                sk = sk.split(",")
            a["skills"] = [str(s).strip()[:24] for s in sk if str(s).strip()][:8]
        for f in ("shiftFrom", "shiftTo"):
            if f in ev:
                a[f] = str(ev[f] or "").strip()
        if a["name"] != old:
            log_floor(a["name"], "renamed from " + old)
        if "skills" in ev:
            log_floor(a["name"], "skills: " + (", ".join(a["skills"]) or "none"))
        if "shiftFrom" in ev or "shiftTo" in ev:
            log_floor(a["name"], "shift " + (a["shiftFrom"] or "any") + "–" + (a["shiftTo"] or "any"))
        STATE["updated"] = time.time()
        return {"ok": True, "id": a["id"], "agent": a["name"], "skills": a["skills"],
                "shiftFrom": a["shiftFrom"], "shiftTo": a["shiftTo"], "onShift": on_shift(a)}


def add_file(a, path):
    base = os.path.basename(str(path).replace("\\", "/").rstrip("/")) or "file"
    if base not in a["files"]:
        a["files"].insert(0, base)
        del a["files"][MAX_FILES:]
    log_agent(a, "Wrote " + base)
    log_floor(a["name"], "shipped " + base)
    return base


def num_or_none(value):
    """Coerce to float, or return None when the value cannot be a number."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_event(ev):
    kind = str(ev.get("event") or "").strip().lower()
    # validate numeric fields before touching any agent, so a bad producer
    # report is rejected instead of half-applying an event
    if "progress" in ev and ev["progress"] is not None and num_or_none(ev["progress"]) is None:
        return {"ok": False, "error": "progress must be a number"}
    if kind == "progress" and num_or_none(ev.get("value", ev.get("progress"))) is None:
        return {"ok": False, "error": "progress needs a numeric 'value'"}
    with LOCK:
        if kind == "reset":
            STATE["agents"].clear()
            STATE["floor"]["log"].clear()
            log_floor("Bridge", "floor reset")
            STATE["updated"] = time.time()
            return {"ok": True, "reset": True}

        if kind == "floor":
            log_floor(ev.get("who") or ev.get("agent") or "Floor", ev.get("text") or ev.get("log"))
            STATE["updated"] = time.time()
            return {"ok": True}

        name = ev.get("agent") or ev.get("name")
        if not name:
            return {"ok": False, "error": "missing 'agent'"}

        a = find_agent(name) or agent_of(name, ev.get("role"), ev.get("desk"))
        a["updated"] = time.time()

        if kind in ("register", "join"):
            st = str(ev.get("state") or "working").lower()
            a["state"] = st if st in STATES else "working"
            if ev.get("task"):
                a["task"] = str(ev["task"])
            log_floor(a["name"], ev.get("log") or "joined the floor")

        elif kind in ("task", "start", "claim"):
            a["task"] = str(ev.get("title") or ev.get("task") or a["task"] or "task")
            a["progress"] = max(0.0, min(1.0, num_or_none(ev.get("progress")) or 0.0))
            a["state"] = "working"
            log_agent(a, "Started " + a["task"])
            log_floor(a["name"], "picked up " + a["task"])

        elif kind == "progress":
            v = num_or_none(ev.get("value", ev.get("progress")))
            if v is not None:
                a["progress"] = max(0.0, min(1.0, v))
            if ev.get("note"):
                log_agent(a, str(ev["note"]))

        elif kind == "state":
            st = str(ev.get("value") or ev.get("state") or "working").lower()
            if st not in STATES:
                st = "working"
            a["state"] = st
            log_floor(a["name"], {"meeting": "went into a meeting", "break": "stepped out for a break",
                                  "aisle": "is on the move", "idle": "is idle", "focus": "is heads-down",
                                  "waiting": "is waiting", "offline": "went offline"}.get(st, st))

        elif kind in ("file", "artifact"):
            add_file(a, ev.get("file") or ev.get("path") or "file")

        elif kind in ("done", "finish", "complete"):
            a["progress"] = 1.0
            if ev.get("file") or ev.get("path"):
                add_file(a, ev.get("file") or ev.get("path"))
            a["state"] = str(ev.get("state") or "idle").lower()
            log_agent(a, "Finished " + (a["task"] or "the task"))
            log_floor(a["name"], "finished " + (a["task"] or "the task"))
            if not ev.get("keep_task"):
                a["task"] = ""

        elif kind in ("assign", "delegate"):
            titles = ev.get("tasks") or ev.get("lines") or ev.get("titles") or ([ev["title"]] if ev.get("title") else [])
            out = assign(name, titles, ev.get("kind", "note"), ev.get("role", ""), ev.get("by", "producer"))
            return out

        elif kind == "log":
            log_agent(a, ev.get("text") or ev.get("log"))
            log_floor(a["name"], ev.get("text") or ev.get("log"))

        else:
            return {"ok": False, "error": "unknown event '%s'" % kind}

        if ev.get("progress") is not None and kind != "progress":
            v = num_or_none(ev["progress"])
            if v is not None:
                a["progress"] = max(0.0, min(1.0, v))
        if ev.get("role"):
            a["role"] = str(ev["role"])
        STATE["updated"] = time.time()
        return {"ok": True, "agent": a["name"]}


def snapshot():
    with LOCK:
        agents = sorted(STATE["agents"].values(), key=lambda a: (a["desk"] if a["desk"] else 99, a["name"]))
        return {
            "source": STATE["source"],
            "updated": STATE["updated"],
            "clock": clock_now(),
            "floor": {"log": list(STATE["floor"]["log"])},
            "agents": [dict(a, queue=queue_info(a), onShift=on_shift(a)) for a in agents],
        }


# ---------- work queue: the manager assigns, agents take one at a time ----------
def queue_info(a):
    q = a.get("tasks", [])
    return {"waiting": sum(1 for t in q if t["state"] == "waiting"),
            "active": sum(1 for t in q if t["state"] == "active"),
            "done": sum(1 for t in q if t["state"] == "done") + sum(1 for t in q if t["state"] == "failed"),
            "next": next((t["title"] for t in q if t["state"] == "waiting"), "")}


def new_task(title, kind="note", by="manager"):
    kind = kind if kind in TASK_KINDS else "note"
    t = {"id": "t%d" % NEXT_ID[0], "title": str(title).strip()[:160], "kind": kind, "by": by,
         "state": "waiting", "created": time.time(), "started": None, "ended": None, "note": "", "file": ""}
    NEXT_ID[0] += 1
    return t


def active_task(a):
    return next((t for t in a.get("tasks", []) if t["state"] == "active"), None)


def next_waiting(a):
    return next((t for t in a.get("tasks", []) if t["state"] == "waiting"), None)


def assign(agent_name, titles, kind="note", role="", by="manager"):
    with LOCK:
        a = find_agent(agent_name) or agent_of(agent_name, role)
        q = a.setdefault("tasks", [])
        if isinstance(titles, str):
            titles = titles.splitlines()
        added, skipped = [], 0
        for entry in titles:
            k = kind
            if isinstance(entry, dict):
                k = entry.get("kind", kind)
                entry = entry.get("title", "")
            title = str(entry).strip()
            if not title:
                continue
            if len(q) >= MAX_QUEUE:
                skipped += 1
                continue
            t = new_task(title, k, by)
            q.append(t)
            added.append(t["id"])
        if added:
            log_floor(a["name"], "was assigned %d task%s" % (len(added), "" if len(added) == 1 else "s"))
            STATE["updated"] = time.time()
        return {"ok": bool(added), "agent": a["name"], "ids": added, "skipped": skipped, "queue": queue_info(a)}


def claim(agent_name):
    with LOCK:
        a = find_agent(agent_name) or agent_of(agent_name)
        act = active_task(a)
        if act:
            return {"ok": False, "error": "busy: one task at a time", "active": act, "agent": a["name"]}
        t = next_waiting(a)
        if not t:
            return {"ok": False, "error": "no waiting task", "agent": a["name"]}
        if not on_shift(a):
            return {"ok": False, "error": "off shift", "agent": a["name"],
                    "shift": [a.get("shiftFrom") or "", a.get("shiftTo") or ""]}
        t["state"] = "active"
        t["started"] = time.time()
        a["state"] = "working"
        a["task"] = t["title"]
        a["progress"] = 0.0
        log_agent(a, "Started " + t["title"])
        log_floor(a["name"], "started " + t["title"])
        STATE["updated"] = time.time()
        return {"ok": True, "agent": a["name"], "task": t}


def complete_task(agent_name, tid=None, state="done", note="", file=""):
    with LOCK:
        a = find_agent(agent_name) or agent_of(agent_name)
        t = next((x for x in a.get("tasks", []) if (x["id"] == tid) or (not tid and x["state"] == "active")), None)
        if t is None:
            return {"ok": False, "error": "no matching task"}
        t["state"] = state if state in ("done", "failed") else "done"
        t["ended"] = time.time()
        t["note"] = note or t.get("note", "")
        if file:
            t["file"] = add_file(a, file)
        a["progress"] = 1.0
        a["state"] = "idle"
        a["task"] = ""
        log_agent(a, ("Finished " if t["state"] == "done" else "Failed ") + t["title"])
        log_floor(a["name"], ("finished " if t["state"] == "done" else "failed ") + t["title"])
        STATE["updated"] = time.time()
        return {"ok": True, "agent": a["name"], "task": t, "queue": queue_info(a)}


def remove_task(agent_name, tid):
    with LOCK:
        a = find_agent(agent_name) or agent_of(agent_name)
        q = a.setdefault("tasks", [])
        t = next((x for x in q if x["id"] == tid), None)
        if t is None:
            return {"ok": False, "error": "unknown task id"}
        if t["state"] == "active":
            return {"ok": False, "error": "task is running"}
        q.remove(t)
        STATE["updated"] = time.time()
        return {"ok": True, "agent": a["name"], "removed": tid, "queue": queue_info(a)}


def clear_tasks(agent_name=None):
    with LOCK:
        targets = [agent_of(agent_name)] if agent_name else list(STATE["agents"].values())
        n = 0
        for a in targets:
            q = a.setdefault("tasks", [])
            keep = [t for t in q if t["state"] in ("waiting", "active")]
            n += len(q) - len(keep)
            a["tasks"] = keep
        STATE["updated"] = time.time()
        return {"ok": True, "cleared": n}


def read_html():
    path = os.path.abspath(ARGS.html)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None, None
    if HTML["body"] is None or mt != HTML["mtime"] or HTML["path"] != path:
        with open(path, "rb") as fh:
            HTML["body"] = fh.read()
        HTML["mtime"] = mt
        HTML["path"] = path
    return HTML["body"], path


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentFloorBridge/1.0"

    def log_message(self, fmt, *args):
        if ARGS and ARGS.verbose:
            print("[http] " + (fmt % args), flush=True)

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/floor", "/floor.html", "/index.html"):
            body, p = read_html()
            if body is None:
                self._send(404, "scene html not found — pass --html <path>", "text/plain; charset=utf-8")
            else:
                self._send(200, body, "text/html; charset=utf-8")
        elif path == "/status":
            self._json(200, snapshot())
        elif path == "/health":
            s = snapshot()
            self._json(200, {"ok": True, "agents": len(s["agents"]), "events_logged": len(s["floor"]["log"]),
                             "age": round(time.time() - s["updated"], 1)})
        elif path == "/tasks":
            s = snapshot()
            self._json(200, {"ok": True, "agents": [{"agent": a["name"], "queue": a["queue"],
                                                      "tasks": a.get("tasks", [])[-8:]} for a in s["agents"]]})
        elif path == "/next":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            with LOCK:
                a = STATE["agents"].get(key_of((qs.get("agent") or [""])[0]))
                t = next_waiting(a) if a else None
            self._json(200, {"ok": bool(t), "task": t, "active": (active_task(a) if a else None)})
        else:
            self._json(404, {"ok": False, "error": "unknown path"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            ev = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": "bad json: %s" % exc})
            return
        if path == "/reset":
            ev = {"event": "reset"}
        elif path == "/assign":
            titles = ev.get("tasks") or ev.get("lines") or ev.get("titles") or ([ev["title"]] if ev.get("title") else [])
            out = assign(ev.get("agent") or "Manager", titles, ev.get("kind", "note"), ev.get("role", ""), ev.get("by", "manager"))
            self._json(200 if out.get("ok") else 400, out)
            return
        elif path == "/claim":
            out = claim(ev.get("agent") or "")
            self._json(200 if out.get("ok") else 409, out)
            return
        elif path in ("/task/done", "/task/finish"):
            out = complete_task(ev.get("agent") or "", ev.get("id") or ev.get("task_id"),
                                ev.get("state") or "done", ev.get("note") or "", ev.get("file") or "")
            self._json(200 if out.get("ok") else 400, out)
            return
        elif path == "/task/remove":
            out = remove_task(ev.get("agent") or "", ev.get("id") or ev.get("task_id"))
            self._json(200 if out.get("ok") else 400, out)
            return
        elif path == "/tasks/clear":
            self._json(200, clear_tasks(ev.get("agent")))
            return
        elif path in ("/agent/update", "/agent"):
            if not (ev.get("agent") or ev.get("name")):
                self._json(400, {"ok": False, "error": "missing agent"})
                return
            out = update_agent(ev.get("agent") or ev.get("name"), ev)
            self._json(200 if out.get("ok") else 400, out)
            return
        elif path != "/event":
            self._json(404, {"ok": False, "error": "unknown path"})
            return
        if isinstance(ev, list):
            results = [apply_event(e) for e in ev]
            bad = [r for r in results if not r.get("ok")]
            self._json(200 if not bad else 400, {"ok": not bad, "applied": len(results) - len(bad),
                                                "failed": len(bad), "results": results[:10]})
            return
        try:
            out = apply_event(ev)
        except Exception as exc:  # noqa: BLE001 — never drop the connection on a producer typo
            self._json(400, {"ok": False, "error": "event raised: %s" % exc})
            return
        self._json(200 if out.get("ok") else 400, out)


def watch_loop(specs, interval, initial, since=None):
    seen = {}
    start = since if since is not None else time.time()
    while True:
        for name, folder in specs:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.startswith(".") or f.endswith((".tmp", ".part", "~")):
                        continue
                    fp = os.path.join(root, f)
                    try:
                        mt = os.path.getmtime(fp)
                    except OSError:
                        continue
                    prev = seen.get(fp)
                    if prev is None:
                        seen[fp] = mt
                        # first sight: report files that appeared after we started watching
                        if initial or mt >= start - 0.5:
                            apply_event({"event": "file", "agent": name, "file": fp})
                    elif mt > prev + 0.01:
                        seen[fp] = mt
                        apply_event({"event": "file", "agent": name, "file": fp})
        time.sleep(interval)


def tail_loop(path, interval):
    pos = 0
    buf = ""
    while True:
        try:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size < pos:
                    pos, buf = 0, ""
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    pos = fh.tell()
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        apply_event(json.loads(line))
                    except Exception as exc:  # noqa: BLE001
                        print("[tail] skipped bad line: %s" % exc, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[tail] %s" % exc, flush=True)
        time.sleep(interval)


def main():
    global ARGS
    ap = argparse.ArgumentParser(description="Bridge real agent activity onto the Agent Floor scene.")

    def positive_float(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("must be a number greater than zero")
        if not math.isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("must be greater than zero")
        return number

    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1, local only)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--html", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "原型", "V7 Agent-Floor.html"),
                    help="floor scene html to serve at /")
    ap.add_argument("--watch", action="append", default=[], metavar="NAME=DIR",
                    help="report any file written under DIR as shipped by NAME (repeatable)")
    ap.add_argument("--watch-interval", type=positive_float, default=1.5)
    ap.add_argument("--watch-initial", action="store_true", help="also report files already present at start")
    ap.add_argument("--tail", metavar="FILE.jsonl", help="append-only jsonl of events")
    ap.add_argument("--demo", action="store_true", help="(smoke test) post one event of each kind, then keep serving")
    ap.add_argument("--worker", dest="worker", action="store_true", default=True,
                    help="do assigned work in-process, so agents start as soon as you assign (default)")
    ap.add_argument("--no-worker", dest="worker", action="store_false", help="serve only; run floor_worker.py yourself")
    ap.add_argument("--worker-interval", type=positive_float, default=1.5)
    ap.add_argument("--verbose", action="store_true")
    ARGS = ap.parse_args()

    specs = []
    for raw in ARGS.watch:
        if "=" not in raw:
            print("[watch] ignoring '%s' (expected NAME=DIR)" % raw, flush=True)
            continue
        name, folder = raw.split("=", 1)
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            print("[watch] %s is not a directory — skipping" % folder, flush=True)
            continue
        specs.append((name.strip(), folder))

    if specs:
        t = threading.Thread(target=watch_loop, args=(specs, ARGS.watch_interval, ARGS.watch_initial, STATE["started"]), daemon=True)
        t.start()
        print("[watch] " + ", ".join("%s <- %s" % (n, d) for n, d in specs), flush=True)
    if ARGS.tail:
        t = threading.Thread(target=tail_loop, args=(os.path.abspath(ARGS.tail), 1.0), daemon=True)
        t.start()
        print("[tail] %s" % os.path.abspath(ARGS.tail), flush=True)

    if ARGS.demo:
        for ev in ({"event": "register", "agent": "Bridge", "role": "link check", "log": "bridge online"},
                   {"event": "task", "agent": "Bridge", "title": "self test", "progress": 0.0},
                   {"event": "progress", "agent": "Bridge", "value": 0.5, "note": "half way"},
                   {"event": "file", "agent": "Bridge", "file": "bridge/self-test.txt"},
                   {"event": "done", "agent": "Bridge", "state": "idle"}):
            apply_event(ev)

    body, path = read_html()
    print("[scene] %s" % (path if body else "(not found — pass --html)"), flush=True)
    if ARGS.worker:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import floor_worker
            url = "http://%s:%d" % ("127.0.0.1" if ARGS.host in ("0.0.0.0", "") else ARGS.host, ARGS.port)
            threading.Thread(target=floor_worker.serve,
                             args=(url, (), ARGS.worker_interval, 0, True, False), daemon=True).start()
            print("[worker] assigned work runs in-process (disable with --no-worker)", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[worker] could not start: %s" % exc, flush=True)
    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), Handler)
    print("[ready] http://%s:%d/  ·  /status  ·  POST /event  ·  POST /reset" % (ARGS.host, ARGS.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[stop] bridge closed", flush=True)


if __name__ == "__main__":
    main()
