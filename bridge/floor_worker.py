#!/usr/bin/env python3
"""floor_worker.py — the hands of the Agent Floor.

It takes jobs that were assigned in the scene's manage panel (or via POST /assign) and does them,
one task at a time per agent, in assignment order. While it works it reports progress and the file it
produced, so the floor moves because real work is happening.

  python bridge/floor_worker.py                  # serve every agent that has a queue
  python bridge/floor_worker.py --agent Nadia    # serve only Nadia (repeatable)
  python bridge/floor_worker.py --once           # one pass, then exit (good for tests)
  python bridge/floor_worker.py --interval 1.5

Task kinds (all real, deterministic, standard library only — no shell, no arbitrary commands):

  note       writes work/<agent>/note-<id>.md   — the task, who asked, timings, and a real checksum
  table      writes work/<agent>/table-<id>.csv — generated rows + real aggregates, seeded by task id
  check      writes work/<agent>/check-<id>.md  — real integrity check (sizes + sha256) of that agent's files
  inventory  writes work/<agent>/inventory-<id>.csv — real listing of work/ with sizes and mtimes

Nobody executes shell commands from a task title: a title is text, the work is the kind.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("FLOOR_URL", "http://127.0.0.1:8787")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")


def call(url, path, payload=None, method=None, timeout=6.0):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "http %s" % exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def say(quiet, msg):
    if not quiet:
        print(msg, flush=True)


def agent_dir(name):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip().lower())
    d = os.path.join(WORK, safe or "agent")
    os.makedirs(d, exist_ok=True)
    return d


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def real_work(seed):
    """A small honest computation so a task is not an empty promise: deterministic, timed."""
    rnd = random.Random(seed)
    total, n = 0.0, 200000
    for _ in range(n):
        total += rnd.random()
    return n, total / n


def do_note(url, agent, task, quiet):
    t0 = time.perf_counter()
    n, mean = real_work(task["id"])
    d = agent_dir(agent)
    path = os.path.join(d, "note-%s.md" % task["id"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# %s\n\n" % task["title"])
        fh.write("- agent: %s\n- requested by: %s\n- task id: %s (%s)\n" % (agent, task.get("by", "manager"), task["id"], task["kind"]))
        fh.write("- created: %s\n- finished: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(task["created"] or time.time())),
                                                      time.strftime("%Y-%m-%d %H:%M:%S")))
        fh.write("- real work done: %d iterations, mean %.6f, %.2f ms\n" % (n, mean, (time.perf_counter() - t0) * 1000))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("- file sha256: %s\n" % digest(path)[:32])
    return path, "note written"


def do_table(url, agent, task, quiet):
    rnd = random.Random("table-" + task["id"])
    rows = 400
    d = agent_dir(agent)
    path = os.path.join(d, "table-%s.csv" % task["id"])
    vals = []
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "sensor", "reading", "flag"])
        for i in range(rows):
            v = round(rnd.uniform(6.0, 31.5), 2)
            vals.append(v)
            w.writerow([i + 1, "s%02d" % (i % 7 + 1), v, "high" if v > 28 else ""])
    stats = {"rows": rows, "mean": round(sum(vals) / rows, 3), "min": min(vals), "max": max(vals),
             "high": sum(1 for v in vals if v > 28)}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("# stats %s\n" % json.dumps(stats, sort_keys=True))
    return path, "table of %d rows (mean %.2f, %d flagged)" % (rows, stats["mean"], stats["high"])


def do_check(url, agent, task, quiet):
    d = agent_dir(agent)
    files = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    rows, ok = [], 0
    for f in files:
        fp = os.path.join(d, f)
        size = os.path.getsize(fp)
        rows.append((f, size, digest(fp)[:16]))
        ok += 1 if digest(fp) else 0
    path = os.path.join(d, "check-%s.md" % task["id"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Integrity check — %s\n\n" % agent)
        fh.write("Checked %d file(s) in %s at %s.\n\n| file | bytes | sha256 |\n|---|---|---|\n" % (len(rows), d, time.strftime("%H:%M:%S")))
        for f, size, h in rows:
            fh.write("| %s | %d | %s |\n" % (f, size, h))
        fh.write("\nAll %d files readable and hashed.\n" % ok)
    return path, "checked %d files" % len(rows)


def do_inventory(url, agent, task, quiet):
    path = os.path.join(agent_dir(agent), "inventory-%s.csv" % task["id"])
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "bytes", "modified"])
        for root, dirs, files in os.walk(WORK):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for f in sorted(files):
                fp = os.path.join(root, f)
                try:
                    w.writerow([os.path.relpath(fp, ROOT), os.path.getsize(fp),
                                time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))])
                    n += 1
                except OSError:
                    pass
    return path, "inventoried %d files" % n


KINDS = {"note": do_note, "table": do_table, "check": do_check, "inventory": do_inventory}


def run_task(url, agent, task, quiet):
    kind = task.get("kind") or "note"
    fn = KINDS.get(kind, do_note)
    say(quiet, "  [%s] %s -> %s" % (agent, kind, task["title"]))
    call(url, "/event", {"event": "progress", "agent": agent, "value": 0.15,
                         "note": "started %s (%s)" % (task["title"], kind)})
    time.sleep(0.4)
    path, summary = fn(url, agent, task, quiet)
    call(url, "/event", {"event": "progress", "agent": agent, "value": 0.8, "note": summary})
    out = call(url, "/task/done", {"agent": agent, "id": task["id"], "state": "done",
                                   "note": summary, "file": path})
    say(quiet, "  [%s] done: %s (%s)" % (agent, summary, os.path.basename(path)))
    return out


def targets(url, only, quiet):
    if only:
        return only
    with_queue = call(url, "/tasks")
    names = [a["agent"] for a in (with_queue.get("agents") or [])
             if (a.get("queue") or {}).get("waiting", 0) > 0]
    if not names and not quiet:
        seen = call(url, "/status")
        names = [a["name"] for a in (seen.get("agents") or [])]
    return names


def serve(url, only=(), interval=1.5, max_tasks=0, quiet=False, once=False):
    """One task at a time per agent, in queue order, forever (or once / until max_tasks)."""
    done = 0
    while True:
        moved = False
        for agent in targets(url, list(only), quiet):
            if max_tasks and done >= max_tasks:
                return done
            got = call(url, "/claim", {"agent": agent})
            if not got.get("ok"):
                continue
            run_task(url, agent, got["task"], quiet)
            done += 1
            moved = True
        if once or (max_tasks and done >= max_tasks):
            return done
        time.sleep(0.4 if moved else interval)


def main():
    ap = argparse.ArgumentParser(description="Do the work assigned on the Agent Floor.")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--agent", action="append", default=[], help="serve only this agent (repeatable)")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--max", type=int, default=0, help="stop after N tasks (0 = unlimited)")
    ap.add_argument("--quiet", action="store_true")
    p = ap.parse_args()

    say(p.quiet, "worker on %s -> %s" % (p.url, WORK))
    done = serve(p.url, p.agent, p.interval, p.max, p.quiet, p.once)
    say(p.quiet, "worker finished: %d task(s)" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
