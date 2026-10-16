#!/usr/bin/env python3
"""floor_producer.py — report real agent activity to the Agent Floor bridge.

Any agent, script or pipeline can call this. One line per real thing that happened.

  python floor_producer.py register  --agent Nadia --role Research
  python floor_producer.py task      --agent Nadia --title "Vendor comparison brief"
  python floor_producer.py progress  --agent Nadia --value 0.4 --note "3 of 7 vendors scored"
  python floor_producer.py file      --agent Nadia --path work/nadia/vendors-brief.md
  python floor_producer.py state     --agent Nadia --value meeting
  python floor_producer.py done      --agent Nadia
  python floor_producer.py log       --agent Nadia --text "asked Yusuf for the pipeline log"
  python floor_producer.py watch     --agent Nadia --dir work/nadia      # any new/changed file counts as shipped
  python floor_producer.py reset

Address: --url, else $FLOOR_URL, else http://127.0.0.1:8787
Standard library only; exits non-zero if the bridge is unreachable (safe to ignore in a pipeline).
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("FLOOR_URL", "http://127.0.0.1:8787")


def positive_float(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number greater than zero")
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def post(url, payload, quiet=False, timeout=4.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/event", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if not quiet:
            print("floor bridge rejected the event at %s (HTTP %s): %s"
                  % (url, exc.code, detail), file=sys.stderr)
        return False
    except urllib.error.URLError as exc:
        if not quiet:
            print("floor bridge unreachable at %s (%s)" % (url, exc), file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            print("floor report failed: %s" % exc, file=sys.stderr)
        return False

    try:
        result = json.loads(body)
    except ValueError:
        result = None
    if not isinstance(result, dict) or result.get("ok") is not True:
        if not quiet:
            print("floor bridge did not confirm the event: %s" % (body or "empty response"),
                  file=sys.stderr)
        return False
    if not quiet:
        print(body)
    return True


def agent_args(p):
    ev = {"agent": p.agent}
    if getattr(p, "role", None):
        ev["role"] = p.role
    if getattr(p, "desk", None):
        ev["desk"] = p.desk
    return ev


def watch(p):
    if not math.isfinite(p.interval) or p.interval <= 0:
        raise ValueError("watch interval must be greater than zero")
    if not os.path.isdir(p.dir):
        raise OSError("watch directory does not exist: %s" % p.dir)
    seen = {}
    start = time.time()
    print("watching %s -> %s" % (os.path.abspath(p.dir), p.agent), flush=True)
    while True:
        for root, dirs, files in os.walk(p.dir):
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
                    if p.initial or mt >= start - 0.5:
                        post(p.url, {"event": "file", "agent": p.agent, "file": fp}, p.quiet)
                elif mt > prev + 0.01:
                    seen[fp] = mt
                    post(p.url, {"event": "file", "agent": p.agent, "file": fp}, p.quiet)
        time.sleep(p.interval)


def main():
    ap = argparse.ArgumentParser(description="Report real work to the Agent Floor bridge.")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--quiet", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_text, fields):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--agent", "-a", required=True)
        for f, kw in fields:
            s.add_argument(f, **kw)
        return s

    add("register", "an agent joins the floor", [("--role", {}), ("--desk", {"type": int})])
    add("task", "an agent picks up a task", [("--title", {"required": True}), ("--role", {}), ("--desk", {"type": int})])
    add("progress", "task progress 0..1", [("--value", {"type": float, "required": True}), ("--note", {})])
    add("file", "a real file was produced", [("--path", {"required": True})])
    add("state", "meeting / break / focus / idle / working / aisle", [("--value", {"required": True})])
    add("log", "one line of activity", [("--text", {"required": True})])
    add("done", "task finished", [("--file", {}), ("--state", {"default": "idle"})])
    sub.add_parser("reset", help="clear the floor")
    w = sub.add_parser("watch", help="watch a folder: new/changed files count as shipped")
    w.add_argument("--agent", "-a", required=True)
    w.add_argument("--dir", required=True)
    w.add_argument("--interval", type=positive_float, default=1.5)
    w.add_argument("--initial", action="store_true", help="also report files already there")

    p = ap.parse_args()

    if p.cmd == "reset":
        req = urllib.request.Request(p.url.rstrip("/") + "/reset", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                print(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            print("floor bridge unreachable at %s (%s)" % (p.url, exc), file=sys.stderr)
            return 1
        return 0

    if p.cmd == "watch":
        try:
            watch(p)
        except KeyboardInterrupt:
            return 0
        except (OSError, ValueError) as exc:
            print("floor watch failed: %s" % exc, file=sys.stderr)
            return 2
        return 0

    ev = agent_args(p)
    if p.cmd == "task":
        ev.update(event="task", title=p.title)
    elif p.cmd == "progress":
        ev.update(event="progress", value=p.value)
        if p.note:
            ev["note"] = p.note
    elif p.cmd == "file":
        ev.update(event="file", file=p.path)
    elif p.cmd == "state":
        ev.update(event="state", value=p.value)
    elif p.cmd == "log":
        ev.update(event="log", text=p.text)
    elif p.cmd == "done":
        ev.update(event="done", state=p.state)
        if p.file:
            ev["file"] = p.file
    else:
        ev.update(event="register")

    return 0 if post(p.url, ev, p.quiet) else 1


if __name__ == "__main__":
    sys.exit(main())
