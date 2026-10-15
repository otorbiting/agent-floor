#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Self-test for daily_sync.py using a local HTTP server (no external accounts needed).

Run:  python selftest.py
Prints PASS/FAIL per check and exits non-zero on any failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "daily_sync.py")

CSV_BODY = b"id,name,amount\r\n1,alpha,10\r\n2,beta,20\r\n3,gamma,30\r\n"
BLANK_HEADER_CSV_BODY = b"id,name,amount,\r\n1,alpha,10,\r\n2,beta,20,\r\n"
RECEIVED = {"upload": None, "multipart_head": None}

failures = []


def check(name, condition, detail=""):
    print(("PASS  " if condition else "FAIL  ") + name + (("  -- " + detail) if detail and not condition else ""))
    if not condition:
        failures.append(name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/sheet.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(CSV_BODY)))
            self.end_headers()
            self.wfile.write(CSV_BODY)
        elif self.path.startswith("/blank-header.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(BLANK_HEADER_CSV_BODY)))
            self.end_headers()
            self.wfile.write(BLANK_HEADER_CSV_BODY)
        elif self.path.startswith("/private"):
            page = b"<!DOCTYPE html><html><body>Sign in to continue</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        RECEIVED["upload"] = body
        RECEIVED["headers"] = dict(self.headers)
        RECEIVED["multipart_head"] = body[:400].decode("utf-8", "replace")
        payload = json.dumps({"received_bytes": len(body)}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_case(cfg, extra_args=(), expect_code=0):
    workdir = tempfile.mkdtemp(prefix="dailysync-")
    cfg_path = os.path.join(workdir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    proc = subprocess.run([sys.executable, SCRIPT, "--config", cfg_path] + list(extra_args),
                          capture_output=True, text=True, cwd=workdir)
    return proc, workdir, expect_code


def base_cfg(base_url):
    return {
        "sheet": {"export_url": base_url + "/sheet.csv", "expected_columns": ["id", "name"], "min_rows": 2},
        "download": {"dir": "downloads", "filename_pattern": "sheet-{date}.csv", "latest_copy": "latest.csv"},
        "upload": {"mode": "http", "url": base_url + "/upload", "file_field": "csvfile",
                   "extra_fields": {"source": "selftest"}, "headers": {"X-Selftest": "yes"}},
        "logging": {"enabled": True, "dir": "logs"},
    }


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    base_url = "http://127.0.0.1:%d" % port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("local test server on %s\n" % base_url)

    try:
        # 1. happy path: download + validate + upload
        proc, workdir, _ = run_case(base_cfg(base_url))
        check("happy path exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
        summary = [l for l in proc.stdout.splitlines() if l.startswith("SUMMARY ")]
        data = json.loads(summary[0][len("SUMMARY "):]) if summary else {}
        check("summary reports ok", data.get("ok") is True, json.dumps(data))
        check("row count parsed from csv", data.get("rows") == 4, json.dumps(data))

        downloaded = os.path.join(workdir, data.get("file", ""))
        check("downloaded file exists", os.path.isfile(downloaded), downloaded)
        check("downloaded bytes match source",
              os.path.isfile(downloaded) and open(downloaded, "rb").read() == CSV_BODY)
        check("latest.csv copy written", os.path.isfile(os.path.join(workdir, "downloads", "latest.csv")))
        check("manifest written", os.path.isfile(os.path.join(workdir, "downloads", "last-run.json")))
        check("log file written", os.path.isfile(os.path.join(workdir, "logs", "daily-sync.log")))

        # 2. the server really received a multipart POST containing the csv
        body = RECEIVED["upload"] or b""
        check("server received the upload", bool(body))
        check("configured request header sent", (RECEIVED.get("headers") or {}).get("X-Selftest") == "yes",
              str(RECEIVED.get("headers")))
        check("multipart field name honoured", 'name="csvfile"' in (RECEIVED["multipart_head"] or ""),
              RECEIVED["multipart_head"] or "")
        check("uploaded file name attached", 'filename="' in (RECEIVED["multipart_head"] or ""))
        check("extra form field sent", 'name="source"' in (RECEIVED["multipart_head"] or ""))
        check("csv payload present in upload body", CSV_BODY in body)
        check("upload response surfaced", "HTTP 201" in proc.stdout, proc.stdout)

        # 3. missing config -> exit 1 with a readable list
        cfg = base_cfg(base_url)
        cfg["sheet"]["export_url"] = ""
        cfg["upload"]["url"] = ""
        proc, _, _ = run_case(cfg, ["--check"])
        check("--check reports not ready and exits 1",
              proc.returncode == 1 and "NOT ready" in proc.stdout, proc.stdout)
        check("--check names sheet.url problem", "sheet.sheet_id" in proc.stdout, proc.stdout)
        check("--check names upload url problem", "upload.url" in proc.stdout, proc.stdout)

        # 4. private sheet (login page instead of csv) -> exit 2, clear hint
        cfg = base_cfg(base_url)
        cfg["sheet"]["export_url"] = base_url + "/private"
        proc, _, _ = run_case(cfg)
        check("login page detected as download error", proc.returncode == 2, proc.stdout)
        check("hint mentions sharing the sheet", "Anyone with the link" in proc.stdout, proc.stdout)

        # 5. changed columns -> exit 3, no upload
        RECEIVED["upload"] = None
        cfg = base_cfg(base_url)
        cfg["sheet"]["expected_columns"] = ["id", "amount", "missing_column"]
        proc, _, _ = run_case(cfg)
        check("column drift stops the run", proc.returncode == 3, proc.stdout)
        check("nothing was uploaded on validation failure", RECEIVED["upload"] is None)

        # 6. a trailing blank header must be rejected before upload
        RECEIVED["upload"] = None
        cfg = base_cfg(base_url)
        cfg["sheet"]["export_url"] = base_url + "/blank-header.csv"
        proc, _, _ = run_case(cfg)
        check("trailing blank header stops the run",
              proc.returncode == 3 and "last column has an empty header" in proc.stdout, proc.stdout)
        check("nothing was uploaded for a blank trailing header", RECEIVED["upload"] is None)

        # 7. dry run -> downloads, does not upload
        RECEIVED["upload"] = None
        proc, _, _ = run_case(base_cfg(base_url), ["--dry-run"])
        check("dry run exits 0", proc.returncode == 0, proc.stdout)
        check("dry run does not upload", RECEIVED["upload"] is None)

        # 8. unreachable upload endpoint -> exit 4
        cfg = base_cfg(base_url)
        cfg["upload"]["url"] = "http://127.0.0.1:1/upload"
        proc, _, _ = run_case(cfg)
        check("dead endpoint exits 4", proc.returncode == 4, proc.stdout)
    finally:
        server.shutdown()

    print("\n%d check(s) failed" % len(failures))
    for name in failures:
        print("  - %s" % name)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
