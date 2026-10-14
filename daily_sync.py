#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Daily work helper: download a Google Sheet as CSV, then upload it to a website.

Usage:
    python daily_sync.py --config config.json              # full run
    python daily_sync.py --config config.json --check      # validate config only (exit 1 if not ready)
    python daily_sync.py --config config.json --dry-run    # download + validate, no upload
    python daily_sync.py --config config.json --source-file already.csv   # skip the download

Exit codes:
    0 ok
    1 config problem
    2 download problem
    3 validation problem (empty / bad columns)
    4 upload problem
    5 unexpected problem

Only the Python standard library is used.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CSV_CONTENT_TYPE = "text/csv"
USER_AGENT = "daily-sync/1.0 (+local automation)"


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class SyncError(Exception):
    code = 5

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


class ConfigError(SyncError):
    code = 1


class DownloadError(SyncError):
    code = 2


class ValidationError(SyncError):
    code = 3


class UploadError(SyncError):
    code = 4


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
PLACEHOLDER_RE = re.compile(r"\$\{(ENV|FILE):([^}]+)\}")


def expand_placeholders(value):
    """Expand ${ENV:NAME} and ${FILE:path} anywhere in the config."""
    if isinstance(value, str):
        def repl(match):
            kind, name = match.group(1).upper(), match.group(2).strip()
            if kind == "ENV":
                val = os.environ.get(name)
                if val is None:
                    raise ConfigError("config references ${ENV:%s} but that environment variable is not set" % name)
                return val
            with open(name, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        return PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, dict):
        return dict((k, expand_placeholders(v)) for k, v in value.items())
    if isinstance(value, list):
        return [expand_placeholders(v) for v in value]
    return value


def load_config(path):
    if not os.path.isfile(path):
        raise ConfigError("config file not found: %s" % path,
                          hint="copy the template, or run with --config <path>")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except ValueError as exc:
        raise ConfigError("config file is not valid JSON: %s" % exc)
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    return expand_placeholders(raw)


def check_config(cfg):
    """Return a list of human-readable problems. Empty list means ready to run."""
    problems = []
    sheet = cfg.get("sheet") or {}
    upload = cfg.get("upload") or {}

    if not sheet.get("export_url"):
        if not sheet.get("sheet_id"):
            problems.append("sheet.sheet_id is empty (or set sheet.export_url instead)")
        if not sheet.get("gid") and not sheet.get("sheet_name"):
            problems.append("set sheet.gid (the #gid=... number) or sheet.sheet_name (the tab name)")

    if not upload.get("url"):
        problems.append("upload.url is empty (the endpoint or form URL that receives the file)")

    mode = (upload.get("mode") or "http").lower()
    if mode not in ("http", "manual"):
        problems.append("upload.mode must be 'http' or 'manual', got %r" % upload.get("mode"))

    if mode == "http" and upload.get("url", "").startswith("https://docs.google.com"):
        problems.append("upload.url still points at Google; it must be the site that receives the file")

    return problems


# --------------------------------------------------------------------------
# sheet download
# --------------------------------------------------------------------------
def build_sheet_url(sheet):
    """Turn the config into a direct CSV export URL."""
    if sheet.get("export_url"):
        url = sheet["export_url"]
        if sheet.get("sheet_name"):
            url += ("&" if "?" in url else "?") + "sheet=" + urllib.parse.quote(sheet["sheet_name"])
        return url

    base = "https://docs.google.com/spreadsheets/d/%s" % sheet["sheet_id"]
    if sheet.get("gid"):
        return "%s/export?format=csv&gid=%s" % (base, str(sheet["gid"]).strip())
    if sheet.get("sheet_name"):
        return "%s/gviz/tq?tqx=out:csv&sheet=%s" % (base, urllib.parse.quote(sheet["sheet_name"]))
    return "%s/export?format=csv" % base


def http_get(url, timeout=60, attempts=3, backoff=2.0):
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"}
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()[:300]
            except Exception:
                pass
            last = DownloadError("HTTP %s from %s: %s" % (exc.code, url, body.decode("utf-8", "replace")),
                                 hint=("404 usually means a wrong sheet id or gid"
                                       if exc.code == 404 else None))
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts:
                time.sleep(backoff * attempt)
                continue
            raise last
        except urllib.error.URLError as exc:
            last = DownloadError("could not reach %s: %s" % (url, exc.reason),
                                 hint="check the network, VPN, or proxy")
            if attempt < attempts:
                time.sleep(backoff * attempt)
                continue
            raise last
    raise last


def download_sheet(sheet, timeout=60):
    url = build_sheet_url(sheet)
    status, body, headers = http_get(url, timeout=timeout,
                                     attempts=int(sheet.get("retries", 3)),
                                     backoff=float(sheet.get("retry_backoff_seconds", 2)))
    if status != 200:
        raise DownloadError("sheet export returned HTTP %s" % status)

    head = body[:400].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        raise DownloadError(
            "the sheet returned a web page instead of CSV, so it is not readable without signing in",
            hint=("In Google Sheets: Share > General access > 'Anyone with the link' (Viewer), "
                  "or File > Share > Publish to web and put the .../pub?output=csv link in sheet.export_url"))
    return url, body, headers


def validate_csv(body, sheet):
    """Parse, sanity-check, and return (row_count, header list)."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("latin-1")

    rows = [r for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any((c or "").strip() for c in r)]

    min_rows = int(sheet.get("min_rows", 2))
    if len(rows) < min_rows:
        raise ValidationError("the export has %d non-empty row(s), expected at least %d"
                              % (len(rows), min_rows),
                              hint="an empty or half-written sheet usually means the export is not ready")

    header = [(c or "").strip() for c in rows[0]]
    expected = sheet.get("expected_columns") or []
    if expected:
        lower = [h.lower() for h in header]
        missing = [c for c in expected if c.strip().lower() not in lower]
        if missing:
            raise ValidationError("export is missing expected column(s): %s (got: %s)"
                                  % (", ".join(missing), ", ".join(header)),
                                  hint="the sheet layout may have changed; fix config or the sheet")

    if bool(sheet.get("forbid_trailing_blank_header", True)) and header and not header[-1]:
        raise ValidationError("last column has an empty header")
    return len(rows), header


def save_download(body, cfg, when):
    dl = cfg.get("download") or {}
    out_dir = dl.get("dir") or "downloads"
    os.makedirs(out_dir, exist_ok=True)

    pattern = dl.get("filename_pattern") or "{date}.csv"
    name = pattern.replace("{date}", when.strftime("%Y-%m-%d")).replace("{time}", when.strftime("%H%M%S"))
    path = os.path.join(out_dir, name)
    with open(path, "wb") as fh:
        fh.write(body)

    latest = dl.get("latest_copy")
    if latest is None:
        latest = "latest.csv"
    latest_path = None
    if latest:
        latest_path = os.path.join(out_dir, latest)
        with open(latest_path, "wb") as fh:
            fh.write(body)
    return path, latest_path


def write_manifest(path, cfg, when, url, body, rows, header, extra=None):
    dl = cfg.get("download") or {}
    if dl.get("manifest") is False:
        return None
    manifest_path = os.path.join(dl.get("dir") or "downloads", "last-run.json")
    payload = {
        "ran_at": when.isoformat(),
        "source_url": url,
        "file": os.path.basename(path),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "rows": rows,
        "header": header,
    }
    if extra:
        payload.update(extra)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return manifest_path


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------
def guess_content_type(path, override=None):
    if override:
        return override
    if path.lower().endswith(".csv"):
        return CSV_CONTENT_TYPE
    return "application/octet-stream"


def build_multipart(field_name, filename, payload, content_type, extra_fields=None):
    boundary = "----dailysync%s" % uuid.uuid4().hex
    out = io.BytesIO()

    def line(text):
        out.write(text.encode("utf-8"))

    for key, value in (extra_fields or {}).items():
        line("--%s\r\n" % boundary)
        line('Content-Disposition: form-data; name="%s"\r\n\r\n' % str(key).replace('"', "'"))
        line(str(value))
        line("\r\n")

    line("--%s\r\n" % boundary)
    line('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
         % (str(field_name).replace('"', "'"), os.path.basename(filename).replace('"', "'")))
    line("Content-Type: %s\r\n\r\n" % content_type)
    out.write(payload)
    line("\r\n--%s--\r\n" % boundary)
    return out.getvalue(), "multipart/form-data; boundary=%s" % boundary


def upload_file(cfg, path):
    up = cfg.get("upload") or {}
    url = up["url"]
    field = up.get("file_field") or "file"
    timeout = float(up.get("timeout_seconds", 120))

    with open(path, "rb") as fh:
        payload = fh.read()

    body, content_type = build_multipart(
        field_name=field,
        filename=up.get("upload_filename") or os.path.basename(path),
        payload=payload,
        content_type=guess_content_type(path, up.get("content_type")),
        extra_fields=up.get("extra_fields") or {},
    )

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    headers.update(up.get("headers") or {})
    headers["Content-Type"] = content_type

    method = (up.get("method") or "POST").upper()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, text = resp.status, resp.read(2000)
    except urllib.error.HTTPError as exc:
        detail = b""
        try:
            detail = exc.read()[:500]
        except Exception:
            pass
        raise UploadError("upload failed: HTTP %s from %s: %s"
                          % (exc.code, url, detail.decode("utf-8", "replace")),
                          hint=("401/403 usually means a missing or expired token in upload.headers"
                                if exc.code in (401, 403) else
                                "404/405 usually means a wrong upload endpoint" if exc.code in (404, 405) else None))
    except urllib.error.URLError as exc:
        raise UploadError("could not reach the upload endpoint %s: %s" % (url, exc.reason))

    expected = up.get("expected_status") or [200, 201, 202, 204]
    if status not in expected:
        raise UploadError("upload returned HTTP %s, expected one of %s: %s"
                          % (status, expected, text.decode("utf-8", "replace")[:300]))

    return {"status": status, "response": text.decode("utf-8", "replace")[:300],
            "bytes_sent": len(payload), "endpoint": url}


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def log_line(cfg, text):
    dl = cfg.get("download") or {}
    log_dir = (cfg.get("logging") or {}).get("dir")
    if (cfg.get("logging") or {}).get("enabled", True) is False:
        return
    log_dir = log_dir or "logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "daily-sync.log"), "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (_dt.datetime.now().isoformat(timespec="seconds"), text))
    except OSError:
        pass


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def run(cfg, args):
    started = _dt.datetime.now()
    summary = {"started_at": started.isoformat(), "ok": False}

    if args.check:
        problems = check_config(cfg)
        summary["problems"] = problems
        summary["ok"] = not problems
        print("config check: %s" % ("OK, ready to run" if not problems else "NOT ready"))
        for problem in problems:
            print("  - %s" % problem)
        return summary

    problems = check_config(cfg)
    if problems:
        raise ConfigError("config is incomplete: " + "; ".join(problems),
                          hint="run with --check to list every missing field")

    sheet = cfg.get("sheet") or {}
    source_file = None

    if args.source_file:
        source_file = args.source_file
        if not os.path.isfile(source_file):
            raise ConfigError("--source-file not found: %s" % source_file)
        with open(source_file, "rb") as fh:
            body = fh.read()
        url = "file://%s" % os.path.abspath(source_file)
        print("source: local file %s (%d bytes)" % (source_file, len(body)))
    else:
        url, body, headers = download_sheet(sheet, timeout=float(sheet.get("timeout_seconds", 60)))
        print("source: %s" % url)
        print("downloaded %d bytes (content-type: %s)" % (len(body), headers.get("Content-Type", "?")))

    rows, header = validate_csv(body, sheet)
    print("validated: %d rows, %d columns" % (rows, len(header)))

    path, latest_path = save_download(body, cfg, started)
    print("saved: %s" % path)
    manifest = write_manifest(path, cfg, started, url, body, rows, header)
    if manifest:
        print("manifest: %s" % manifest)

    summary.update({"rows": rows, "columns": len(header), "downloaded_bytes": len(body),
                    "file": path, "sha256": hashlib.sha256(body).hexdigest()})

    up = cfg.get("upload") or {}
    mode = (up.get("mode") or "http").lower()

    if args.dry_run:
        print("dry run: skipping upload (mode would be %s)" % mode)
        summary["ok"] = True
        return summary

    if mode == "manual":
        page = up.get("form_url") or up.get("url")
        print("manual mode: nothing uploaded")
        print("  step 1: open %s" % page)
        print("  step 2: choose this file: %s" % os.path.abspath(path))
        log_line(cfg, "manual mode, file=%s rows=%d" % (path, rows))
        summary.update({"ok": True, "mode": "manual", "form_url": page})
        return summary

    result = upload_file(cfg, path)
    print("uploaded: HTTP %s from %s (%d bytes sent)" % (result["status"], result["endpoint"], result["bytes_sent"]))
    if result["response"].strip():
        print("response: %s" % result["response"].strip())
    log_line(cfg, "upload OK status=%s rows=%d bytes=%d file=%s" % (result["status"], rows, result["bytes_sent"], path))
    summary.update({"ok": True, "mode": "http", "upload": result})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download a Google Sheet as CSV and upload it to a website.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--check", action="store_true", help="validate the config and exit")
    parser.add_argument("--dry-run", action="store_true", help="download and validate, but do not upload")
    parser.add_argument("--source-file", help="use a local CSV instead of downloading the sheet")
    args = parser.parse_args(argv)

    summary = {"ok": False}
    try:
        cfg = load_config(args.config)
        summary = run(cfg, args)
        # --check exits 1 when the config is not ready, so wrappers can fail fast.
        exit_code = 0 if summary.get("ok") else (1 if args.check else 5)
    except SyncError as exc:
        exit_code = exc.code
        print("ERROR: %s" % exc)
        if exc.hint:
            print("hint: %s" % exc.hint)
        summary["error"] = str(exc)
        try:
            log_line(load_config(args.config), "FAILED(%s) %s" % (exc.code, exc))
        except Exception:
            pass
    except Exception as exc:  # unexpected
        exit_code = 5
        print("ERROR: unexpected %s: %s" % (type(exc).__name__, exc))
        summary["error"] = "%s: %s" % (type(exc).__name__, exc)

    print("SUMMARY %s" % json.dumps(summary, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
