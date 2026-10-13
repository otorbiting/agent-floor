# Agent Floor bridge — real agent activity on the floor

The scene (`原型/V* Agent-Floor.html`) can run two ways:

| how you open it | what you see |
|---|---|
| `http://127.0.0.1:8787/` (served by the bridge) | **live feed** — desks show whatever your real agents report |
| `原型/V7 Agent-Floor.html` (opened as a file) | **simulation** — the built-in demo activity |

The badge next to the title always says which one you are looking at (`live feed · N real agents · updated Xs ago` / `simulation`), and the wall board in the scene reads `FLOOR BOARD · LIVE FEED` or `· SIMULATION`. Nothing is invented in feed mode: what the bridge has is what the floor shows.

## 1. Start it

```powershell
python bridge\agent_floor_bridge.py --port 8787 --html "原型\V7 Agent-Floor.html"
```

Then open <http://127.0.0.1:8787/>. The bridge binds to `127.0.0.1` only and has no authentication — do not expose it with `--host 0.0.0.0` on an untrusted network.

Useful flags:

```
--worker             do assigned work in-process so agents start as soon as you assign (default on)
--no-worker          serve only; run floor_worker.py yourself
--watch NAME=DIR     any file written under DIR is reported as shipped by NAME (repeatable)
--watch-initial      also report files that already existed when the watcher started
--tail FILE.jsonl    append one event object per line to a file; the bridge tails it
--demo               post one event of each kind (smoke test), then keep serving
--verbose            log every HTTP request
```

**Assigning work starts it.** With `--worker` (the default) the bridge itself takes each queued task in order and does it, so nothing else needs to be running: you type a task, press Assign, and the agent starts within a second or two and reports the file it produced.

## 2. Report real work

One line per real thing that happened. `floor_producer.py` is a thin CLI over `POST /event`; `$FLOOR_URL` or `--url` chooses the bridge (default `http://127.0.0.1:8787`).

```powershell
python bridge\floor_producer.py register --agent Nadia --role Research
python bridge\floor_producer.py task     --agent Nadia --title "Vendor comparison brief"
python bridge\floor_producer.py progress --agent Nadia --value 0.4 --note "3 of 7 vendors scored"
python bridge\floor_producer.py file     --agent Nadia --path work\nadia\vendors-brief.md
python bridge\floor_producer.py state    --agent Nadia --value meeting    # or break / focus / idle / working / aisle
python bridge\floor_producer.py log      --agent Nadia --text "asked Yusuf for the pipeline log"
python bridge\floor_producer.py done     --agent Nadia --file work\nadia\vendors-brief.md
python bridge\floor_producer.py reset
```

Exit code is non-zero if the bridge is unreachable, so a pipeline can ignore it safely.

### Or let the bridge watch a folder

If your agents (or any tool) simply write files, no reporting code is needed — the writer becomes the agent:

```powershell
python bridge\agent_floor_bridge.py --watch "Nadia=C:\work\nadia" --watch "Yusuf=C:\work\yusuf"
# or, from inside a running pipeline:
python bridge\floor_producer.py watch --agent Nadia --dir C:\work\nadia
```

### Or append to a JSONL

```jsonl
{"event":"task","agent":"Yusuf","role":"Engineer","title":"Fix the nightly pipeline"}
{"event":"progress","agent":"Yusuf","value":0.5}
{"event":"file","agent":"Yusuf","file":"build/fix-4172.patch"}
{"event":"done","agent":"Yusuf","state":"idle"}
```

```powershell
python bridge\agent_floor_bridge.py --tail events.jsonl
```

## 3. Assign work from the scene (manage panel)

The scene has an **Assign work** panel (desktop: left side; mobile: the `Work` button). Pick an agent, type one task per line, press Assign. Lines can pick their own work type:

```
Summarise the vendor shortlist
table: Table the survey results
check: Check the evidence folder
inventory: Inventarise the build outputs
```

Agents work **one task at a time, in order**: the bridge refuses a second claim while a task is running (`409 busy`), and the next waiting task only starts after the current one is finished. The panel shows `running` / `queued` per row and can cancel a queued task (`×`).

### Editing an agent

The same panel edits the selected agent and the change is live on the floor:

| field | meaning | behaviour |
|---|---|---|
| **name** | display name (rename) | keeps id, desk, queue and files; the floor relabels immediately |
| **from / to** | work time as a shift window, `HH:MM` (empty = always on) | outside the window the agent shows **Off shift**, is not assigned/claimed work, and keeps queued tasks for later (windows may cross midnight) |
| **skills** | comma-separated tags | kept on the record, shown on the agent's card, and readable by any external dispatcher |

```powershell
curl -X POST http://127.0.0.1:8787/agent/update -d '{"agent":"Rina","name":"Rina Putri","skills":"research, sql","shiftFrom":"09:00","shiftTo":"18:00"}'
```

Renames are safe: everything is keyed by the stable `id` returned in `GET /status`, so addressing the agent by either its id or its current name reaches the same record.

### Doing the work

```powershell
python bridge\floor_worker.py                 # serve every agent with a queue, forever
python bridge\floor_worker.py --agent Rina    # only Rina
python bridge\floor_worker.py --once          # one pass, then exit
python bridge\floor_worker.py --max 3         # stop after 3 tasks
```

`floor_worker.py` is the reference worker: it claims by HTTP, does a real deterministic job for the task's kind, and reports the produced file. **It never executes shell commands from a task title** — a title is text, the work is the kind:

| kind | writes | what is real |
|---|---|---|
| `note` | `work/<agent>/note-<id>.md` | the task, who asked, timings, a 200k-iteration computation, file sha256 |
| `table` | `work/<agent>/table-<id>.csv` | 400 generated rows + real min/mean/max/flag counts |
| `check` | `work/<agent>/check-<id>.md` | real sizes + sha256 of every file in that agent's folder |
| `inventory` | `work/<agent>/inventory-<id>.csv` | real listing of `work/` with sizes and mtimes |

Any other agent, script or model can take the same jobs instead — the queue is just HTTP:

```powershell
curl http://127.0.0.1:8787/next?agent=Rina                       # peek at the next task
curl -X POST http://127.0.0.1:8787/claim -d '{"agent":"Rina"}'  # take it (409 if busy)
curl -X POST http://127.0.0.1:8787/task/done -d '{"agent":"Rina","id":"t7","note":"done","file":"out/report.md"}'
```

## 4. The contract

`GET /status` — what the scene polls every 2 s:

```json
{
  "source": "agent-floor-bridge", "updated": 1760271212.4, "clock": "13:14",
  "floor": { "log": [["13:14", "Nadia", "shipped vendors-brief.md"]] },
  "agents": [{
    "id": "nadia", "name": "Nadia", "role": "Research", "desk": 1,
    "state": "working", "task": "Vendor comparison brief", "progress": 0.4,
    "files": ["vendors-brief.md"], "log": [["13:12", "Started Vendor comparison brief"]],
    "updated": 1760271200.1
  }]
}
```

`POST /event` — same fields, one event at a time (or a list of events):

| `event` | required | effect |
|---|---|---|
| `register` | `agent` | the agent appears on the floor (`role`, `desk` optional) |
| `task` / `start` | `agent`, `title` | sets the current task, progress 0, state working |
| `progress` | `agent`, `value` (0..1) | moves the progress bar; `note` is written to the agent's log |
| `file` / `artifact` | `agent`, `file` | adds the file to the agent, logs "shipped …" |
| `state` | `agent`, `value` | `working` `focus` `meeting` `break` `aisle` `idle` `waiting` `offline` |
| `done` / `finish` | `agent` | progress 1.0, optional `file`, state → `idle`, clears the task |
| `log` | `agent`, `text` | one activity line |
| `assign` | `agent`, `tasks` or `lines` | queue work (each entry may be `{title, kind}`) |
| `floor` | `text` | a line on the floor log itself (`who` optional) |

Work-queue endpoints: `POST /assign` (`{agent, tasks:[{title,kind}]}` or `{agent, lines:[...]}`), `POST /claim` (`409` while one is running), `POST /task/done` (`{agent, id, state, note, file}`), `POST /task/remove` (`{agent, id}`, only queued), `POST /tasks/clear` (`{agent}` optional), `GET /tasks` (all queues), `GET /next?agent=` (peek).

`POST /reset` clears everything. Desk numbers are 1-based; if you omit `desk`, the scene assigns the first free desk and keeps that agent on it.

## 5. What is real, and what the scene adds

- **Real**: identity, role, current task, progress, produced file names, state changes, activity lines, timestamps, and the order they happened in. Also who is in a meeting / on a break — because you said so.
- **Added by the scene** (and only that): how the agent *walks* to the coffee counter when you report `break`, where they sit, and the pixel-level animation. Those are animations over your data, not claims about what an agent did.
- The scene pauses the built-in simulation for every desk it takes over; desks your agents don't use are shown as `unassigned` rather than filled with made-up activity.
- If the bridge stops answering for ~6 s the scene says `feed offline · showing built-in simulation` and falls back to the simulation instead of freezing on stale data.
- Ten desks exist in the room. Register more agents and the extras are simply not shown (the badge counts real agents; `N/10` in the Agents panel shows how many got desks).

## 6. Verified behaviour

```
$ python bridge\agent_floor_bridge.py --port 8787 --html "原型\V7 Agent-Floor.html" --watch "Rina=work\rina"
[watch] Rina <- ...\work\rina
[ready] http://127.0.0.1:8787/  ·  /status  ·  POST /event  ·  POST /reset

$ python bridge\floor_producer.py file --agent AutoClaw --path "原型\V7 Agent-Floor.html"
{"ok": true, "agent": "AutoClaw"}

$ curl http://127.0.0.1:8787/status
AutoClaw | Build | focus | prog=0.6 | files=[V7 Agent-Floor.html, agent_floor_bridge.py, floor_producer.py]
Rina     |       | working | files=[field-notes.txt]        <- written by the folder watcher, not by code
```
