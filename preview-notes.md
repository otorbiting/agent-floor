# Verified states (what the screenshots showed)

Recorded so the facts survive even if the images are replaced.

## Standalone file — `原型/V9 Agent-Floor.html` opened directly
- Assign-work panel is visible (not hidden) — diagnostic read `OPTS=10 FIRST=MAYA HIDDEN=FALSE`.
- Dropdown lists all ten desks; default selection `Maya`.
- Clicking **Assign** with "Standalone test task" and Maya selected gave:
  - panel header `1 RUNNING · 0 QUEUED`
  - queue row `Maya · Standalone test task · running`
  - floor bubble over Maya: `Started: Standalone test task`
- Editing (name / from / to / skills) applies locally and shows on the card.

## Live bridge mode — `http://127.0.0.1:8787/`
- Badge next to the title: `live · 3 agents · 0s ago`; wall board reads `FLOOR BOARD · LIVE FEED`.
- Roster: `AutoClaw — WORKING (Agent editor: name, shift, s…)`, `Budi — IDLE`, `Rina Putri — WORKING (Check the evidence folder)`; desks 04–10 `EMPTY · no agent assigned`.
- HUD counters at that moment: `2 working · 0 aisle · 1 away · 9 shipped`.
- Queue row: `Rina Putri · Check the evidence folder · running`.
- Floor log lines (real work, real files): `Rina Putri shipped check-t13.md`, `Rina Putri finished Check the evidence folder`,
  `Budi shipped inventory-t14.csv`, `Rina Putri shipped table-t12.csv`.
- Shifts/skills on record: `AutoClaw 00:00–23:59 [build, verify, docs]`, `Budi 08:30–17:30 [python, etl, infra]`,
  `Rina Putri 09:00–18:00 [research, sql, writing]`.

## Behaviour verified earlier (not visible in one frame)
- Second claim while a task runs → `409 busy` (strictly one task at a time).
- Off shift: task stays queued and does not start; after the shift window it starts by itself.
- Rename keeps id/desk/queue/files; no duplicate agent record is created.
- Idle/away desks are labelled `desk NN · unassigned` with dark monitors — nothing is faked for desks nobody occupies.

## Capture defect (measured)
- Headless captures of this app now composite a *foreign* canvas layer: floor sample region (650,380)-(950,520) mean RGB = (193,191,184) vs the scene's own floor ~(60,58,66); whole-frame mean (152,187,136) is green-dominant.
- Same-frame HTML chrome is correct and matches `GET /status`: brand badge `live · 3 agents · 0s ago`, roster `AutoClaw WORKING / Budi IDLE / Rina Putri WORKING`, desks `Desk 04..Desk 10 EMPTY · no agent assigned`, panel header `0 RUNNING · 0 QUEUED` (between tasks), agent editor prefilled `AutoClaw / 00:00 / 23:59 / build, verify, docs`, floor log `16:56 Rina Putri shipped check-t13.md`, `16:56 Budi shipped inventory-t14.csv`, `16:56 Rina Putri shipped table-t12.csv`, wall board `FLOOR BOARD · LIVE FEED 16:56`, HUD `1 working · 0 aisle · 2 away · 9 shipped`.
- Legacy headless (`--headless=old`) is unavailable in this Chrome build (no screenshot written).
- Consequence: the delivered preview sheet shows real UI text as evidence and intentionally omits the animated floor; open the file or http://127.0.0.1:8787/ to see the scene canvas.

## Reference video facts — `promo.mp4` (my own extraction, 2026-10-12)
Vertical 540x960, 36 s, 30 fps. Product wordmark "officeverse" in orange, lowercase, on dark; closing card "COMING SOON" + `officeverse.id`.
Captions seen: "This is Officeverse." / "Every desk = an AI agent" / "agent at work" / "Agents that collaborate" / "hand off tasks" /
"Every screen = real work" / "live:" / "Chat. Send files. Get Excel" / "Chat with any" / "in Excel." /
"Approvals - Meetings - Routines ... place." / "Your own character ... character, game." / "Coming soon at officeverse.id".
Frames show: bright isometric cutaway office, grey/white desks in rows, dark chairs, glowing monitors, glass-walled meeting room,
lounge with sofa, wood floor in the meeting area, potted plants, outdoor greenery; agent chat panel; "My character" dialog
(Appearance skin/eyes/hair, shirt, trousers, shoes; Name field; "Date: 02 August"; Cancel / Save character); file chips (xlsx).

## Reference image 2 facts (bright world brief)
Recorded in full in `原型/reference-notes.md`: elevated light platform in a green miniature world (grass, trees, cliffs, turquoise lake,
waterfall, dock, boat, dirt paths, flowers, wooden bridge, village with cream walls and red/blue roofs); white desks, black ergonomic
chairs, mostly two monitors per desk; lounge with beige sofa, two blue armchairs, striped rug, wooden coffee table, warm floor lamp;
wood-slat walls with "Better Ideas Bigger Goals" and "Good Vibes Work Better"; whiteboard "Team / Build - Improve - Grow - Together";
round wall clock; bookshelves; large windows onto the landscape; sideboard, reception counter, water dispenser, planters,
black mat "Good Vibes Work here"; warm sunlight from upper left, soft shadows.

## Preview card state at delivery (17:0x)
`原型/V9 Agent-Floor.html` 64977 bytes, mtime 16:48:18, JS syntax OK. Manage panel + queue + agent editor intact
(`id="manage"`, `id="mq"`, `a-save`, `renderQueue` all present). Simulation meetings removed (`startMeeting` 0 hits),
day/night toggle removed (`b-night` 0 hits); bright-world elements partially present (grass 5, lake 1, waterfall 1, village 1,
sofa 6, shelf 3) but `platform` 0 and `sunlight` 0 -> transformation is mid-flight, done by another session editing the same file.
Bridge at 17:07: AutoClaw working (0 done, 1 file), Budi idle (5 done, 5 files), Rina Putri idle (9 done, 6 files);
newest floor log "16:56 Rina Putri finished Check the evidence folder".

## Undo outcome (completed, verified 2026-10-12)
- `原型/V9 Agent-Floor.html` restored to my pre-transformation build: 65152 bytes (64 KiB cap = 65536); JS syntax OK.
- Restored features (marker counts): `id="manage"` 1, `id="mq"` 1, `renderQueue` 1, agent editor `a-name` 3 / `a-from` 5 / `a-to` 5 / `a-skills` 3 / `a-save` 2,
  local queue `a.lq` 6 / `a.lc` 4, id-first desk mapping `deskFor(f.id` 1, simulation `startMeeting` 2, day/night `b-night` 2, `TASKS =` 2.
- Transformation and trims confirmed gone: `grass|lake|waterfall|village` 0, `class="hint"` 0, `scenehelp` 0, `const sx0 = 17.0` 0, `#mq .x` 0.
- Nothing was destroyed: the other session's transformation work-in-progress is preserved as `原型/archive/V9-transform-WIP.html` (64977 bytes, mtime 16:48).
- Trims applied to fit the cap: sim break/chat schedulers, wall hint pill (+ kbd rule), scenehelp paragraph, one-line brand SVG, `.manage button:hover`,
  `#mq` span rules, PLANTS 7->5, rack LEDs 11->8, rack printer boxes, desk paper prop, floor-board bars 16->10, `.card .log em` rule, `#skip=` hook,
  right-wall window pane + night stars + its mullions.
- Bridge unchanged and still running (serves this file; it re-reads on mtime change).
