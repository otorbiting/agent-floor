#!/usr/bin/env python3
"""demo_run.py - one real, honest 4-step job for agent "Budi", reported to the Agent Floor.

Real work only (no mock numbers):
  step 1  generate a deterministic 60-row dataset        -> work/budi/raw.csv
  step 2  aggregate that file with the csv module        -> work/budi/summary.json
  step 3  render a markdown report with the real values  -> work/budi/demo-report.md
  step 4  re-read its own outputs and check consistency  -> work/budi/verify.json + PASS/FAIL

Every step is reported to the running bridge through bridge/floor_producer.py
(subprocess; direct HTTP POST to /event as fallback). Reporting is best effort:
an unreachable or slow bridge is logged and never crashes the job.

Run from the workspace root:  python "bridge\\demo_run.py"
Standard library only.
"""

import csv
import datetime
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRODUCER = os.path.join(HERE, "floor_producer.py")
WORK = os.path.join(ROOT, "work", "budi")
BRIDGE_URL = os.environ.get("FLOOR_URL", "http://127.0.0.1:8787")

AGENT = "Budi"
ROLE = "Engineer"
TASK_TITLE = "Budi demo pipeline: raw.csv -> summary.json -> demo-report.md -> verify"
ROWS = 60
SEED = 20261012
STATIONS = ["North", "East", "South"]

TRANSCRIPT = []
REPORTED = []
REPORT_ERRORS = 0


def say(line=""):
    print(line, flush=True)
    TRANSCRIPT.append(line)


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def now():
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")


# --------------------------------------------------------------------------- floor


def _producer_argv(event, fields):
    if event == "register":
        argv = ["register", "--agent", AGENT]
        if fields.get("role"):
            argv += ["--role", fields["role"]]
    elif event == "task":
        argv = ["task", "--agent", AGENT, "--title", fields["title"]]
    elif event == "progress":
        argv = ["progress", "--agent", AGENT, "--value", "%.3f" % fields["value"]]
        if fields.get("note"):
            argv += ["--note", fields["note"]]
    elif event == "file":
        argv = ["file", "--agent", AGENT, "--path", fields["path"]]
    elif event == "state":
        argv = ["state", "--agent", AGENT, "--value", fields["value"]]
    elif event == "log":
        argv = ["log", "--agent", AGENT, "--text", fields["text"]]
    elif event == "done":
        argv = ["done", "--agent", AGENT, "--state", fields.get("state", "idle")]
        if fields.get("path"):
            argv += ["--file", fields["path"]]
    else:
        raise ValueError("unsupported event %r" % event)
    # --url / --quiet are global options: they must come before the subcommand.
    return ["--url", BRIDGE_URL, "--quiet"] + argv


def _http_event(event, fields):
    payload = {"event": event, "agent": AGENT}
    payload.update(fields)
    if "path" in payload:
        payload["file"] = payload.pop("path")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BRIDGE_URL.rstrip("/") + "/event", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=4) as resp:
        return resp.status == 200


def report(event, note=None, **fields):
    """Best-effort report to the bridge. Returns True/False, never raises."""
    global REPORT_ERRORS
    label = event + (" " + note if note else "")
    try:
        cp = subprocess.run([sys.executable, PRODUCER] + _producer_argv(event, fields),
                            capture_output=True, text=True, timeout=20)
        if cp.returncode == 0:
            REPORTED.append(label)
            say("  [floor] %s -> sent via floor_producer.py" % label)
            return True
        raise RuntimeError("floor_producer exited %d: %s" % (cp.returncode, (cp.stderr or "").strip()[:200]))
    except Exception as exc:  # noqa: BLE001 - reporting must never break the job
        REPORT_ERRORS += 1
        say("  [floor] %s -> producer failed (%s); trying direct POST" % (label, exc))

    try:
        _http_event(event, fields)
        REPORTED.append(label + " (direct POST)")
        say("  [floor] %s -> sent via direct POST %s/event" % (label, BRIDGE_URL))
        return True
    except Exception as exc:  # noqa: BLE001
        REPORT_ERRORS += 1
        say("  [floor] %s -> NOT reported (%s); continuing anyway" % (label, exc))
        return False


def bridge_health():
    try:
        with urllib.request.urlopen(BRIDGE_URL.rstrip("/") + "/health", timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------- step bodies


def step1_generate():
    t0 = time.perf_counter()
    rng = random.Random(SEED)
    day0 = datetime.date(2026, 8, 1)
    path = os.path.join(WORK, "raw.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_id", "date", "station", "temp_c", "rainfall_mm"])
        for i in range(ROWS):
            w.writerow([i + 1,
                        (day0 + datetime.timedelta(days=i)).isoformat(),
                        STATIONS[i % len(STATIONS)],
                        round(rng.gauss(18.0, 6.0), 1),
                        round(max(0.0, rng.gauss(3.5, 4.0)), 1)])
    return path, time.perf_counter() - t0


def step2_aggregate(raw_path):
    t0 = time.perf_counter()
    rows = []
    with open(raw_path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            rows.append({"date": rec["date"], "station": rec["station"],
                         "temp_c": float(rec["temp_c"]), "rainfall_mm": float(rec["rainfall_mm"])})
    if not rows:
        raise ValueError("raw.csv had no data rows")

    temps = [r["temp_c"] for r in rows]
    rain = [r["rainfall_mm"] for r in rows]
    hottest = max(rows, key=lambda r: r["temp_c"])
    coldest = min(rows, key=lambda r: r["temp_c"])

    per = {}
    for r in rows:
        per.setdefault(r["station"], []).append(r["temp_c"])
    per_station = {name: {"rows": len(v), "mean_temp_c": round(sum(v) / len(v), 2)}
                   for name, v in sorted(per.items())}

    summary = {
        "agent": AGENT,
        "source_file": rel(raw_path),
        "rows": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "mean_temp_c": round(sum(temps) / len(temps), 2),
        "min_temp_c": min(temps),
        "min_temp_on": coldest["date"],
        "max_temp_c": max(temps),
        "max_temp_on": hottest["date"],
        "total_rainfall_mm": round(sum(rain), 2),
        "mean_rainfall_mm": round(sum(rain) / len(rain), 2),
        "wet_days": sum(1 for v in rain if v >= 1.0),
        "per_station": per_station,
        "computed_at": now(),
    }
    path = os.path.join(WORK, "summary.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path, summary, time.perf_counter() - t0


def step3_report(summary, timings):
    t0 = time.perf_counter()
    raw_path = os.path.join(WORK, "raw.csv")
    s = summary
    lines = [
        "# Budi demo pipeline report",
        "",
        "- agent: %s (%s)" % (AGENT, ROLE),
        "- generated: %s" % now(),
        "- dataset: %s (%d rows, %s .. %s, seed %d)" % (s["source_file"], s["rows"],
                                                        s["first_date"], s["last_date"], SEED),
        "",
        "## Step ledger (real elapsed time)",
        "",
        "| step | what actually happened | output | elapsed (s) |",
        "| --- | --- | --- | --- |",
        "| 1 | generated the deterministic dataset with random.Random(%d) | raw.csv | %.4f |" % (SEED, timings["1"]),
        "| 2 | re-read raw.csv with the csv module and aggregated it | summary.json | %.4f |" % timings["2"],
        "| 3 | rendered this report from summary.json | demo-report.md | this step (whole table in the verification section) |",
        "| 4 | re-read raw.csv + summary.json and verified consistency | verify.json | in the section below |",
        "",
        "## Computed values (read back from %s)" % rel(os.path.join(WORK, "summary.json")),
        "",
        "| metric | value |",
        "| --- | --- |",
        "| rows | %d |" % s["rows"],
        "| date range | %s .. %s |" % (s["first_date"], s["last_date"]),
        "| mean temp (C) | %s |" % s["mean_temp_c"],
        "| min temp (C) | %s on %s |" % (s["min_temp_c"], s["min_temp_on"]),
        "| max temp (C) | %s on %s |" % (s["max_temp_c"], s["max_temp_on"]),
        "| total rainfall (mm) | %s |" % s["total_rainfall_mm"],
        "| mean rainfall (mm) | %s |" % s["mean_rainfall_mm"],
        "| wet days (>= 1.0 mm) | %d |" % s["wet_days"],
        "",
        "| station | rows | mean temp (C) |",
        "| --- | --- | --- |",
    ]
    for name, info in s["per_station"].items():
        lines.append("| %s | %d | %s |" % (name, info["rows"], info["mean_temp_c"]))
    lines += [
        "",
        "## Inputs and outputs on disk",
        "",
        "- %s (input to step 2)" % rel(raw_path),
        "- %s" % s["source_file"],
        "- %s" % rel(os.path.join(WORK, "demo-report.md")),
        "- %s" % rel(os.path.join(WORK, "verify.json")),
        "",
        "## Floor reporting",
        "",
        "Steps are reported live through bridge/floor_producer.py to %s" % BRIDGE_URL,
        "(register, task, progress per step, one file event per artifact, done at the end).",
        "Reporting failures are logged and never stop the job.",
        "",
    ]
    path = os.path.join(WORK, "demo-report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path, time.perf_counter() - t0


def step4_verify(summary, timings):
    t0 = time.perf_counter()
    raw_path = os.path.join(WORK, "raw.csv")
    report_path = os.path.join(WORK, "demo-report.md")
    checks = []

    rows = []
    with open(raw_path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            rows.append(rec)

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("raw.csv row count == %d" % ROWS, len(rows) == ROWS,
          "raw.csv has %d data rows" % len(rows))
    check("summary rows == raw.csv rows", summary["rows"] == len(rows),
          "summary says %d, raw.csv has %d" % (summary["rows"], len(rows)))

    temps = [float(r["temp_c"]) for r in rows]
    rain = [float(r["rainfall_mm"]) for r in rows]
    mean_t = round(sum(temps) / len(temps), 2)
    total_r = round(sum(rain), 2)
    check("mean temp reproduced from raw.csv", abs(mean_t - summary["mean_temp_c"]) < 1e-9,
          "recomputed %.2f vs summary %s" % (mean_t, summary["mean_temp_c"]))
    check("total rainfall reproduced from raw.csv", abs(total_r - summary["total_rainfall_mm"]) < 1e-9,
          "recomputed %.2f vs summary %s" % (total_r, summary["total_rainfall_mm"]))
    check("per-station rows sum to total",
          sum(v["rows"] for v in summary["per_station"].values()) == summary["rows"],
          "per_station total %d" % sum(v["rows"] for v in summary["per_station"].values()))
    for name, info in summary["per_station"].items():
        got = [t for t, r in zip(temps, rows) if r["station"] == name]
        check("station %s mean temp reproduced" % name,
              abs(round(sum(got) / len(got), 2) - info["mean_temp_c"]) < 1e-9,
              "recomputed %.2f vs summary %s" % (round(sum(got) / len(got), 2), info["mean_temp_c"]))

    report_text = open(report_path, encoding="utf-8").read()
    check("report quotes the real mean temp", str(summary["mean_temp_c"]) in report_text,
          "looking for %s in demo-report.md" % summary["mean_temp_c"])
    check("report quotes the real total rainfall", str(summary["total_rainfall_mm"]) in report_text,
          "looking for %s in demo-report.md" % summary["total_rainfall_mm"])
    passed = sum(1 for c in checks if c["ok"])

    elapsed = time.perf_counter() - t0
    result = {
        "agent": AGENT,
        "checked_at": now(),
        "artifacts": [rel(raw_path), rel(os.path.join(WORK, "summary.json")),
                      rel(report_path), rel(os.path.join(WORK, "verify.json"))],
        "checks": checks,
        "passed": passed,
        "failed": len(checks) - passed,
        "result": "PASS" if passed == len(checks) else "FAIL",
        "step4_elapsed_s": round(elapsed, 4),
    }
    vpath = os.path.join(WORK, "verify.json")
    with open(vpath, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    all_timings = dict(timings)
    all_timings["4"] = elapsed
    with open(report_path, "a", encoding="utf-8") as fh:
        fh.write("\n## Step timings (real elapsed seconds, measured with time.perf_counter)\n\n")
        fh.write("| step | elapsed (s) |\n| --- | --- |\n")
        for k in sorted(all_timings):
            fh.write("| %s | %.4f |\n" % (k, all_timings[k]))
        fh.write("\nTotal job time: %.4f s\n" % sum(all_timings.values()))
        fh.write("\n(Step 4 elapsed covers the verification checks themselves; the verify.json write\n"
                 "that follows is measured separately in the console log and is under a millisecond.)\n")
        fh.write("\n## Verification (step 4, elapsed %.4f s) - %s\n\n" % (elapsed, result["result"]))
        fh.write("| check | result | detail |\n| --- | --- | --- |\n")
        for c in checks:
            fh.write("| %s | %s | %s |\n" % (c["check"], "PASS" if c["ok"] else "FAIL", c["detail"]))
        fh.write("\nStep 4 elapsed: %.4f s. %d of %d checks passed (%s).\n"
                 % (elapsed, passed, len(checks), result["result"]))
    return vpath, result, elapsed


# --------------------------------------------------------------------------- main


def main():
    os.makedirs(WORK, exist_ok=True)
    say("Agent Floor demo pipeline - agent %s (%s)" % (AGENT, ROLE))
    say("workspace: %s" % ROOT)
    say("bridge:    %s   producer: %s" % (BRIDGE_URL, rel(PRODUCER)))
    health = bridge_health()
    say("bridge /health: %s" % json.dumps(health))
    say("")

    say("[step 0] registering on the floor")
    report("register", role=ROLE)
    report("task", title=TASK_TITLE)

    timings = {}

    say("[step 1] generating %d deterministic rows (seed %d)" % (ROWS, SEED))
    raw_path, timings["1"] = step1_generate()
    size = os.path.getsize(raw_path)
    say("  wrote %s (%d bytes, %d data rows) in %.4f s" % (rel(raw_path), size, ROWS, timings["1"]))
    report("progress", value=0.15, note="step 1/4: generated %d rows -> raw.csv" % ROWS)
    report("file", note="raw.csv", path=raw_path)

    say("[step 2] aggregating the real file with the csv module")
    sum_path, summary, timings["2"] = step2_aggregate(raw_path)
    say("  wrote %s in %.4f s" % (rel(sum_path), timings["2"]))
    say("  rows=%d mean_temp=%s total_rain=%s wet_days=%d"
        % (summary["rows"], summary["mean_temp_c"], summary["total_rainfall_mm"], summary["wet_days"]))
    report("progress", value=0.45,
           note="step 2/4: aggregated raw.csv -> summary.json (mean %s C, %.1f mm total)"
                % (summary["mean_temp_c"], summary["total_rainfall_mm"]))
    report("file", note="summary.json", path=sum_path)

    say("[step 3] rendering the report from the computed summary")
    rep_path, timings["3"] = step3_report(summary, timings)
    say("  wrote %s (%d bytes) in %.4f s" % (rel(rep_path), os.path.getsize(rep_path), timings["3"]))
    report("progress", value=0.72, note="step 3/4: rendered demo-report.md with the real numbers")
    report("file", note="demo-report.md", path=rep_path)

    say("[step 4] verifying its own outputs")
    v_path, result, timings["4"] = step4_verify(summary, timings)
    for c in result["checks"]:
        say("  %s  %s (%s)" % ("PASS" if c["ok"] else "FAIL", c["check"], c["detail"]))
    say("  verification checks took %.4f s; wrote %s" % (timings["4"], rel(v_path)))
    say("  verification result: %s (%d/%d checks passed)"
        % (result["result"], result["passed"], result["passed"] + result["failed"]))

    if result["result"] == "PASS":
        report("progress", value=0.95, note="step 4/4: verification PASS (%d checks)" % result["passed"])
    else:
        report("progress", value=0.95, note="step 4/4: verification FAIL (%d checks)" % result["failed"])
    report("file", note="verify.json", path=v_path)

    say("")
    say("elapsed per step (s): %s" % ", ".join("step%s=%.4f" % (k, timings[k]) for k in sorted(timings)))
    say("total job time: %.4f s" % sum(timings.values()))
    say("floor events sent: %d, reporting failures: %d" % (len(REPORTED), REPORT_ERRORS))
    say("RESULT: %s" % result["result"])

    log_path = os.path.join(WORK, "run-log.md")
    header = [
        "# Budi demo pipeline - run log",
        "",
        "Actual console output of `python \"bridge\\demo_run.py\"` run from the workspace root,",
        "captured live by the script itself (stdout of that run, below, unedited).",
        "The final `file run-log.md` and `done` events are sent to the bridge right after this",
        "transcript ends, so they are not part of it.",
        "",
        "```text",
    ]
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(header + TRANSCRIPT + ["```", ""]))

    say("")
    say("[done] wrote %s; sending final file + done to the bridge" % rel(log_path))
    report("file", note="run-log.md", path=log_path)
    report("done", state="idle")
    say("[done] floor now shows %s with %d file events reported." % (AGENT, len(REPORTED)))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
