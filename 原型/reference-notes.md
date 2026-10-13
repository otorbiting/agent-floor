# Reference notes — Agent Floor (visual transformation brief)

Written before the attached images leave the conversation context, so the facts below are the record.

## Reference Video — `promo.mp4` (attached workspace file, 540×960 vertical, 36 s, 30 fps)

Frames were rendered and reviewed on 2026-10-12; the facts below are the record of what they showed.

* On-screen product name: **officeverse** (wordmark in orange, lowercase), tagline **"COMING SOON"**, site **officeverse.id**. Opening caption: "This is Officeverse."
* Concept, in the video's own captions: "**Every desk = an AI agent**", "**Every screen = real work**", "**Agents that collaborate**" ("hand off tasks"), "**Chat. Send files. Get Excel**" ("Chat with any" … "in Excel."), "**Approvals · Meetings · Routines**" … "place.", "**Your own character**" (character … "game.").
* Look: bright isometric 3D office, cutaway rooms, grey/white desks in rows, dark office chairs, glowing monitors, glass meeting room, plants, lounge with sofa, wood floor in the meeting area, outdoor greenery on the right.
* UI shown: a chat panel with an agent conversation (e.g. "Summarise our board," asks for the token refresh status, "use voice to auto report"), a **My character** dialog with Appearance (skin/eyes/hair colour, shirt, trousers, shoes), Name field ("Enter your name") and a "Date: 02 August" field, plus "Cancel" / "Save character" buttons.
* Also shown: file chips (e.g. `xlsx` attachment in the chat), and a profile widget with a collaboration/agent list.
* Behaviour shown: agents sitting at their own desks, an agent walking ("live:" frame), a close-up of a person standing at a desk with a monitor showing a UI, and the closing brand card with **COMING SOON** and the `officeverse.id` URL.

## Reference Image 1 — the current app (this project)

* Not literally an image in this conversation; the working app is `原型/V9 Agent-Floor.html` + the local bridge.
* Its data: real agents registered over HTTP (`name`, `role`, `skills`, `shiftFrom/To`, `queue`, `files`, `log`), a per-agent work queue (one task at a time), an assign panel, an agent editor, camera pan/zoom/reset, floor board, roster, activity log, day/night toggle (to be replaced by daylight-only).
* Palette today: dark charcoal office, amber accent. This is what the transformation replaces.

## Reference Image 2 — target look (attached JPEG, WhatsApp Image 2026-10-12 at 3.55.38 PM)

**Setting.** A cutaway isometric office (no ceiling, 3/4 view) standing on an elevated light platform, dropped into a bright green miniature world.

**Outside / world.** Lush grass, dense rounded trees, rocky cliffs, a turquoise lake with a waterfall, a small wooden dock with a boat, winding dirt paths, flower patches, a wooden bridge, and a distant storybook village (cream walls, red and blue roofs, one tall tower). Warm sunlight from the upper left, soft shadows. No space, no stars, no black background.

**Office platform.** Thick light platform slab with a visible edge (light grey, slightly darker edge/plinth), light grey tile floor.

**Workstations.** White desks, black ergonomic chairs, mostly two monitors per desk (a couple with three), keyboards, small desk accessories; arranged in neat rows with generous walkways; monitors glow with real UI-ish content.

**Lounge (left).** Beige/oatmeal sofa, two blue accent armchairs, striped natural rug, wooden coffee table, floor lamp with warm glow, potted plants, wood-slat feature wall with a big landscape picture (mountains + lake).

**Walls / decor.** Left wall: vertical warm wood slats with the sign "Better Ideas Bigger Goals" and a large framed landscape screen. Back wall: white board reading "Team" with checklist "Build / Improve / Grow / Together", a round white-faced wall clock, tall bookshelves with books and plants. Right wall: large windows looking onto the green landscape, wall-mounted shelves, framed views, another sign "Good Vibes Work Better" with a smiley, a blue armchair and a floor lamp.

**Other props.** Long low sideboard/credenza with a monitor and lamp, reception-style counter, white/blue water dispenser, long dark planter boxes with yellow-green plants along the front edge, many potted plants, a black entrance mat at the front with "Good Vibes Work here" and a smiley.

**Colour story.** Warm wood + white/grey floors + lots of green + blue accents (chairs, cooler) on a saturated emerald/turquoise exterior; bright, welcoming, clean, premium.

## Client brief included with the paste (what the transformation must do)

1. Keep all existing agents, names, data, workflows and functionality; redesign only the environment.
2. Bright detailed isometric office: platform + light tiled floor, white desks + black chairs + monitors, lounge (sofas, blue chairs, coffee table, rugs), bookshelves, plants, decorative lighting, reception counter, large windows with views, team board, clock, motivational signage, warm sunlight and soft shadows.
3. Surrounding world: forests, turquoise lake, streams, waterfalls, cliffs/mountains, winding paths, cottages/village, wooden bridges, beaches, flowers, gardens. No space/black background, no flat dashboard.
4. Represent **real** agents as workstations: real names, real status, activity indicator, selectable, opens the agent's panel. No invented agents, no fabricated activity, no hardcoded demo statuses.
5. Interactive: click desk to select (outline/glow + details panel), smooth zoom in/out, reset to full view, optional focus on an agent.
6. Animations: gently moving water and waterfalls, subtle plant movement, soft sunlight, smooth camera moves, subtle monitor activity, hover/selection feedback, smooth panel open/close; lightweight, no flashing, must look good when all agents are idle.
7. Implementation: inspect the existing code, use what fits it (this project is a single-file HTML5 canvas scene, so no new framework), do not place the reference image behind the UI, do not break existing features, test camera/selection/loading/error/empty states, keep it usable on small screens.
8. Do not stop at a proposal — implement in the existing code.

## Consequences for the build (decisions taken)

* Single file, canvas 2D isometric — keep. Do not introduce Three.js (would mean a rewrite and a framework the project does not have).
* **Remove the built-in ten-agent simulation** (fake names, fake tasks, fake "shipped" files). With no bridge the desks stay honestly `unassigned`; real agents appear only when they report. This also frees the code budget the new world needs.
* Keep the local assign/work-in-scene path for a desk the user explicitly gives work to, labelled as scene work (the badge still says `simulation` when no bridge is connected).
* Daylight only — the day/night toggle and night rendering go away (the brief asks for warm sunlight).
* Trim remaining decoration as needed to stay inside the 64 KB single-file budget.
