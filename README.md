# Daily sync: Google Sheet -> website

One command performs your daily routine:

```
python daily_sync.py --config config.json
```

It downloads the sheet as CSV, checks the file is sane, saves it under `downloads/`, then uploads it to the website endpoint and reports the HTTP result. Every run is appended to `logs/daily-sync.log`, and the last run's metadata (rows, bytes, SHA-256) is written to `downloads/last-run.json`.

## What I still need from you

Only two values are missing. Everything else already has a working default.

1. **The sheet** — either `sheet.sheet_id` + `sheet.gid`, or paste a ready-made CSV link into `sheet.export_url` (see below).
2. **The upload target** — `upload.url`: the address that actually accepts the file.

Fill them in `config.json`, then check your work:

```
python daily_sync.py --config config.json --check
```

`--check` prints exactly what is missing and exits `1` until the config is ready. Nothing is uploaded during `--check`.

## Where to get each value

### The sheet

If the sheet is shared as **"Anyone with the link" (Viewer)**, use:

- `sheet.sheet_id`: the long id between `/d/` and `/edit` in the sheet URL.
- `sheet.gid`: the number after `#gid=` in the URL — this picks one tab. Or use `sheet.sheet_name` with the tab's visible name instead.

If the sheet is **private to your account**, the export URL returns a sign-in page, and the script tells you so rather than uploading junk. Fix it one of two ways:

- In the sheet: **File > Share > Publish to web**, choose CSV, and paste that `.../pub?output=csv` link into `sheet.export_url`. This keeps the sheet itself private.
- Or download the CSV yourself and run with `--source-file your.csv`, which skips the download entirely and still does the validation, saving and upload.

### The upload target

`upload.url` must be the endpoint that receives the file, not the human-facing page. On the site: open the page where you normally upload, press F12, open the **Network** tab, do the upload once by hand, click the request that carries your CSV, and copy its URL plus the form field name into `upload.url` and `upload.file_field`. Then:

```
python daily_sync.py --config config.json --dry-run   # proves the download side
```

Useful options when the endpoint differs from a plain form post:

- `upload.extra_fields` — extra form values the site requires (e.g. a report type or date).
- `upload.method` — `POST` or `PUT`, when the site's API expects `PUT`.
- `upload.expected_status` — accept other success codes if the site returns them.
- `upload.mode: "manual"` — download and validate only, printing the file path and the page to open, so you drag the file in yourself. Use this if the site has no scriptable endpoint or a CAPTCHA.
- `upload.form_url` — the page to open in manual mode.

## Secrets

Do not paste tokens or passwords into `config.json`. Reference the environment instead:

```json
"headers": { "Authorization": "Bearer ${ENV:MY_SITE_TOKEN}" }
```

`${ENV:NAME}` is read at run time, and `${FILE:path}` reads a value from a local file. If the variable is missing, the run stops with a clear message instead of sending an unauthenticated request.

## Verification

```
python selftest.py
```

Runs the whole pipeline against a throwaway local server — download, column check, multipart upload, response handling — plus the failure paths (private sheet, changed columns, trailing blank headers, dead endpoint, incomplete config). 27 checks, no accounts or network needed.

## Run the Agent Floor UI locally

With Node.js installed, run `node serve.js` from this folder, then open <http://127.0.0.1:4173/>. This serves the `原型/V9 Agent-Floor.html` prototype in simulation mode. The live agent feed additionally requires the Python bridge described in `bridge/README.md`.

## Deploy the Agent Floor UI to Vercel

Import this repository in Vercel and deploy it from the project root. `vercel.json` rewrites the root URL to the current prototype in `原型/`. The live agent feed bridge is a separate local Python service and is not deployed by this static-site setup.

## Safety nets built in

- An empty or half-written export is refused before upload (`sheet.min_rows`).
- A trailing blank CSV header is refused by default (`sheet.forbid_trailing_blank_header`).
- `sheet.expected_columns` stops the run if the sheet's columns change, so a restructured sheet can't silently overwrite the site with wrong data.
- Downloads retry on transient `429/5xx` and network errors.
- The CSV is only uploaded after it is validated and saved, so a failed upload still leaves you today's file.

## Running it daily

Once the two values are in place and a real run succeeds, this can be attached to a daily schedule at a time you choose — say the word and I will set it up. Until the config is filled, a schedule would only produce daily failures.
