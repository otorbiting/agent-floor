# Bridge contract notes — Agent Floor bridge (Rina, 2026-10-12)

Target: the **live** bridge at `http://127.0.0.1:8787` (already running; I did not start, stop, restart or
reconfigure it). My client: `bridge/tests/test_contract.py` (standard library only, black-box — it starts
nothing and resets nothing).

## What I tested

The real HTTP contract of the four endpoints the scene depends on, for one real agent (`ContractTest`):

`POST /event` register -> task -> progress -> file -> done, then `GET /status` read-back asserting the
bridge really stored it: agent present under its name, task cleared after `done`, `progress == 1.0`, the
file name present in that agent's `files`, and a `shipped <file>` line in the floor log.

## Exact commands and observed results

### 1. The contract test itself (from the workspace root)

```
python "bridge\tests\test_contract.py"
```

Observed: **12 checks, 12 PASS, 0 FAIL, exit code 0**:

```
PASS  bridge reachable: GET /health -> 200 ok
PASS  POST /event register accepted
PASS  POST /event task     accepted
PASS  POST /event progress accepted
PASS  POST /event file     accepted
PASS  POST /event done     accepted
PASS  GET /status -> 200 with agents[]
PASS  agent stored under its name (ContractTest)
PASS  task cleared after done
PASS  progress reached 1.0
PASS  file name present in agent's files
PASS  floor log contains 'shipped test_contract.py'
SUMMARY: 12 passed, 0 failed
```

The stored record read back from `/status` (03/13:16, bridge-local clock) — matches what was asserted:

```json
{"id": "contracttest", "name": "ContractTest", "role": "contract-test", "desk": null,
 "state": "idle", "task": "", "progress": 1.0, "files": ["test_contract.py"], ...}
```

Floor log lines for that agent: `finished Verify the bridge contract`, `shipped test_contract.py`,
`picked up Verify the bridge contract`, `joined the floor`.

So the happy-path contract holds: every event kind is accepted with `{"ok": true}`, basename of the file
path lands in `files`, `done` forces `progress` to 1.0 and clears `task`.

### 2. Weakness probe — `task` event with a non-numeric `progress`

```
python -c "import json,urllib.request;req=urllib.request.Request('http://127.0.0.1:8787/event',data=json.dumps({'event':'task','agent':'ContractTest','title':'probe','progress':'abc'}).encode(),headers={'Content-Type':'application/json'},method='POST');print(urllib.request.urlopen(req,timeout=4).read())"
```

Observed (exit 1, client side):

```
http.client.RemoteDisconnected: Remote end closed connection without response
```

No HTTP status, no JSON error was ever returned.

### 3. What the crashed request left behind (state read immediately after probe 2)

```
python -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:8787/status',timeout=4));print([(a['name'],repr(a['task']),a['progress'],a['state']) for a in d['agents'] if a['id']=='contracttest'])"
```

Observed: `[('ContractTest', "'probe'", 0.0, 'working')]` — the event was **partially applied**
(agent row created, `task` set) before the crash; no floor-log line was written.

### 4. Contrast probe — malformed JSON body

```
python -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8787/event',data=b'{bad',headers={'Content-Type':'application/json'},method='POST'),timeout=4).read())"
```

Observed: `urllib.error.HTTPError: HTTP Error 400: Bad Request` — a clean JSON 400 **is** returned for an
unparsable body, so the drop-the-connection behaviour in probe 2 is specific to a valid-JSON event that
raises inside `apply_event`.

## The one real weakness worth fixing (verified by probes 2 and 3)

**A valid `task` event whose `progress` is a non-numeric truthy value kills the request and half-applies it.**

Root cause, `bridge/agent_floor_bridge.py`: the `task` branch converts `progress` without a guard —

- `:123` `elif kind in ("task", "start", "claim"):`
- `:125` `a["progress"] = float(ev.get("progress") or 0.0)`  <- `ValueError` escapes here

while the `progress` branch guards the same conversion (`:130`-`:134`, `try/except (TypeError, ValueError)`),
and `do_POST` only guards body read/parse (`:247`-`:254`, the `bad json` 400 path).

Consequences observed: the caller gets **no HTTP response at all** (no 4xx, so a producer cannot tell a
poisoned report from a lost network), the agent record is left half-mutated (`task` set, stale progress,
no log line), and the traceback goes to the bridge's stderr only. A one-line producer typo
(`--value` sent as a string on the wrong event kind) is therefore enough to silently corrupt one agent's
card. Fix: reuse the progress branch's clamp/guard in the task branch (fall back to 0.0 or keep the old
value, and answer 400 `{"ok": false, "error": ...}` instead of dropping the connection).

## Minor observations (code reading only, not probed at runtime)

- `register` stores any `state` string as-is (`:118`) while the `state` event whitelists values (`:140`) —
  an unvalidated state lands on the next `GET /status` snapshot.
- A batch `POST /event` with a JSON array reports `{"ok": true, "applied": n}` even when individual events
  in it fail (`:261`-`:263`, per-event results ignored).
- Files are reduced to basename, deduped per agent and capped at 6 (`:87`-`:89`), so two same-named files
  from different directories collapse into one entry.

## Scope note

`bridge/agent_floor_bridge.py`, `bridge/floor_producer.py` and everything under `原型\` were left untouched;
only `bridge/tests/test_contract.py` and this note were created.
