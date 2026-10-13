# Budi demo pipeline - run log

Actual console output of `python "bridge\demo_run.py"` run from the workspace root,
captured live by the script itself (stdout of that run, below, unedited).
The final `file run-log.md` and `done` events are sent to the bridge right after this
transcript ends, so they are not part of it.

```text
Agent Floor demo pipeline - agent Budi (Engineer)
workspace: C:\Users\lenovo\AppData\Roaming\AutoClaw-oversea-official\accounts\b898840b2bc1108655397f3cb94d546dcf3afdd436899db60517aac76841dc35\projects\Default
bridge:    http://127.0.0.1:8787   producer: bridge/floor_producer.py
bridge /health: {"ok": true, "agents": 2, "events_logged": 8, "age": 0.2}

[step 0] registering on the floor
  [floor] register -> sent via floor_producer.py
  [floor] task -> sent via floor_producer.py
[step 1] generating 60 deterministic rows (seed 20261012)
  wrote work/budi/raw.csv (1806 bytes, 60 data rows) in 0.0013 s
  [floor] progress step 1/4: generated 60 rows -> raw.csv -> sent via floor_producer.py
  [floor] file raw.csv -> sent via floor_producer.py
[step 2] aggregating the real file with the csv module
  wrote work/budi/summary.json in 0.0017 s
  rows=60 mean_temp=18.77 total_rain=181.8 wet_days=40
  [floor] progress step 2/4: aggregated raw.csv -> summary.json (mean 18.77 C, 181.8 mm total) -> sent via floor_producer.py
  [floor] file summary.json -> sent via floor_producer.py
[step 3] rendering the report from the computed summary
  wrote work/budi/demo-report.md (1578 bytes) in 0.0010 s
  [floor] progress step 3/4: rendered demo-report.md with the real numbers -> sent via floor_producer.py
  [floor] file demo-report.md -> sent via floor_producer.py
[step 4] verifying its own outputs
  PASS  raw.csv row count == 60 (raw.csv has 60 data rows)
  PASS  summary rows == raw.csv rows (summary says 60, raw.csv has 60)
  PASS  mean temp reproduced from raw.csv (recomputed 18.77 vs summary 18.77)
  PASS  total rainfall reproduced from raw.csv (recomputed 181.80 vs summary 181.8)
  PASS  per-station rows sum to total (per_station total 60)
  PASS  station East mean temp reproduced (recomputed 17.66 vs summary 17.66)
  PASS  station North mean temp reproduced (recomputed 19.04 vs summary 19.04)
  PASS  station South mean temp reproduced (recomputed 19.59 vs summary 19.59)
  PASS  report quotes the real mean temp (looking for 18.77 in demo-report.md)
  PASS  report quotes the real total rainfall (looking for 181.8 in demo-report.md)
  verification checks took 0.0009 s; wrote work/budi/verify.json
  verification result: PASS (10/10 checks passed)
  [floor] progress step 4/4: verification PASS (10 checks) -> sent via floor_producer.py
  [floor] file verify.json -> sent via floor_producer.py

elapsed per step (s): step1=0.0013, step2=0.0017, step3=0.0010, step4=0.0009
total job time: 0.0049 s
floor events sent: 10, reporting failures: 0
RESULT: PASS
```
