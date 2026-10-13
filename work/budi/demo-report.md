# Budi demo pipeline report

- agent: Budi (Engineer)
- generated: 2026-10-12 15:05:32
- dataset: work/budi/raw.csv (60 rows, 2026-08-01 .. 2026-09-29, seed 20261012)

## Step ledger (real elapsed time)

| step | what actually happened | output | elapsed (s) |
| --- | --- | --- | --- |
| 1 | generated the deterministic dataset with random.Random(20261012) | raw.csv | 0.0013 |
| 2 | re-read raw.csv with the csv module and aggregated it | summary.json | 0.0017 |
| 3 | rendered this report from summary.json | demo-report.md | this step (whole table in the verification section) |
| 4 | re-read raw.csv + summary.json and verified consistency | verify.json | in the section below |

## Computed values (read back from work/budi/summary.json)

| metric | value |
| --- | --- |
| rows | 60 |
| date range | 2026-08-01 .. 2026-09-29 |
| mean temp (C) | 18.77 |
| min temp (C) | 4.7 on 2026-09-10 |
| max temp (C) | 29.7 on 2026-08-31 |
| total rainfall (mm) | 181.8 |
| mean rainfall (mm) | 3.03 |
| wet days (>= 1.0 mm) | 40 |

| station | rows | mean temp (C) |
| --- | --- | --- |
| East | 20 | 17.66 |
| North | 20 | 19.04 |
| South | 20 | 19.59 |

## Inputs and outputs on disk

- work/budi/raw.csv (input to step 2)
- work/budi/raw.csv
- work/budi/demo-report.md
- work/budi/verify.json

## Floor reporting

Steps are reported live through bridge/floor_producer.py to http://127.0.0.1:8787
(register, task, progress per step, one file event per artifact, done at the end).
Reporting failures are logged and never stop the job.

## Step timings (real elapsed seconds, measured with time.perf_counter)

| step | elapsed (s) |
| --- | --- |
| 1 | 0.0013 |
| 2 | 0.0017 |
| 3 | 0.0010 |
| 4 | 0.0009 |

Total job time: 0.0049 s

(Step 4 elapsed covers the verification checks themselves; the verify.json write
that follows is measured separately in the console log and is under a millisecond.)

## Verification (step 4, elapsed 0.0009 s) - PASS

| check | result | detail |
| --- | --- | --- |
| raw.csv row count == 60 | PASS | raw.csv has 60 data rows |
| summary rows == raw.csv rows | PASS | summary says 60, raw.csv has 60 |
| mean temp reproduced from raw.csv | PASS | recomputed 18.77 vs summary 18.77 |
| total rainfall reproduced from raw.csv | PASS | recomputed 181.80 vs summary 181.8 |
| per-station rows sum to total | PASS | per_station total 60 |
| station East mean temp reproduced | PASS | recomputed 17.66 vs summary 17.66 |
| station North mean temp reproduced | PASS | recomputed 19.04 vs summary 19.04 |
| station South mean temp reproduced | PASS | recomputed 19.59 vs summary 19.59 |
| report quotes the real mean temp | PASS | looking for 18.77 in demo-report.md |
| report quotes the real total rainfall | PASS | looking for 181.8 in demo-report.md |

Step 4 elapsed: 0.0009 s. 10 of 10 checks passed (PASS).
