#!/usr/bin/env python3
"""The short sheet: one tab, only what a reader needs.

The tracking sheet keeps every field the digest is built from. This is the
other one - a single tab listing each employee review or post in the window,
newest first, with where it was posted, what it said and a link to it.
Company posts and out-of-scope finds are left out, as they are in the digest.

  python3 scripts/summary_sheet.py                    # last 60 days to today
  python3 scripts/summary_sheet.py --from 2026-08-18 --to 2026-10-16

Writes out/summary-sheet.csv, ready for File > Import in Google Sheets.
With --push it also writes the rows into the sheet digest.data_link names,
replacing its first tab. That needs a service-account key the sheet is shared
with: a path in GOOGLE_SERVICE_ACCOUNT_JSON (or --key). The key never belongs
in this repo.

  python3 scripts/summary_sheet.py --push --key /path/to/key.json
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

COLUMNS = ["Posted", "Company", "Site", "Stars", "Sentiment", "Themes",
           "What they said", "Red flag", "Link"]

THEME_LABELS = {"growth_learning": "Growth", "harassment_safety": "Harassment",
                "payroll_delay": "Payroll delay", "compensation": "Pay",
                "job_security": "Job security", "work_hours": "Work hours"}

FLAG_LABELS = {"harassment_or_safety": "Harassment / safety",
               "names_individual": "Names an individual"}


def theme_text(themes: str) -> str:
    return ", ".join(THEME_LABELS.get(t, t.replace("_", " ").capitalize())
                     for t in (themes or "").split("|") if t.strip())


def rows_for(mentions: list[dict]) -> list[list[str]]:
    entities = H.entity_names()
    platforms = H.platform_names()
    out = []
    for m in mentions:
        if H.is_company_voice(m) or (m.get("status") or "").strip() == "out_of_scope":
            continue
        posted = H.parse_date(m.get("post_date", "")) or H.parse_date(m.get("captured_at", ""))
        flag = ""
        if (m.get("red_flag") or "").strip().lower() == "yes":
            reason = (m.get("red_flag_reason") or "").strip()
            flag = FLAG_LABELS.get(reason, reason.replace("_", " ").capitalize() or "Yes")
        link = (m.get("url") or "").strip() or H.profile_url(m.get("entity", ""),
                                                             m.get("platform", ""))
        out.append([
            posted.isoformat() if posted else "",
            entities.get(m.get("entity", ""), m.get("entity", "")),
            platforms.get(m.get("platform", ""), m.get("source_name", "")),
            (m.get("rating_given") or "").strip(),
            (m.get("sentiment") or "").strip().capitalize() or "Not yet read",
            theme_text(m.get("themes", "")),
            (m.get("one_line_summary") or m.get("title_or_snippet") or "").strip(),
            flag,
            link,
        ])
    out.sort(key=lambda r: r[0], reverse=True)
    return out


SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"


def access_token(key_path: str) -> str:
    """A Sheets token for the service account, signed here with no Google SDK."""
    with open(key_path, encoding="utf-8") as fh:
        key = json.load(fh)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")  # noqa: E731
    now = int(time.time())
    claims = {"iss": key["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
              "aud": key["token_uri"], "iat": now, "exp": now + 3600}
    unsigned = (b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + b"."
                + b64(json.dumps(claims).encode()))
    # openssl rather than the cryptography package, which is not reliably
    # importable on every machine this runs on. The PEM goes to a private temp
    # file only for the length of the call.
    with tempfile.TemporaryDirectory() as tmp:
        pem = os.path.join(tmp, "k.pem")
        with open(os.open(pem, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
            fh.write(key["private_key"])
        signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem], input=unsigned,
                                   capture_output=True, check=True).stdout
    assertion = unsigned + b"." + b64(signature)
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": assertion.decode()}).encode()
    with urllib.request.urlopen(key["token_uri"], body, timeout=30) as resp:
        return json.load(resp)["access_token"]


def call(token: str, method: str, url: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def push(rows: list[list[str]], link: str, key_path: str, title: str = "Reviews") -> None:
    """Replace the first tab of the linked sheet with these rows."""
    found = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", link or "")
    if not found:
        raise SystemExit(f"digest.data_link is not a Google Sheets link: {link!r}")
    sid = found.group(1)
    token = access_token(key_path)
    tab = call(token, "GET", f"{SHEETS}/{sid}?fields=sheets.properties")["sheets"][0]["properties"]
    gid = tab["sheetId"]
    call(token, "POST", f"{SHEETS}/{sid}/values/{urllib.parse.quote(tab['title'])}:clear", {})
    call(token, "POST", f"{SHEETS}/{sid}:batchUpdate", {"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": gid, "title": title,
                                                  "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "title,gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}}]})
    call(token, "PUT", f"{SHEETS}/{sid}/values/{urllib.parse.quote(title)}!A1"
                       "?valueInputOption=USER_ENTERED", {"values": [COLUMNS] + rows})
    call(token, "POST", f"{SHEETS}/{sid}:batchUpdate", {"requests": [
        {"autoResizeDimensions": {"dimensions": {"sheetId": gid, "dimension": "COLUMNS",
                                                 "startIndex": 0, "endIndex": len(COLUMNS)}}}]})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="first", help="first post date, YYYY-MM-DD")
    ap.add_argument("--to", dest="last", help="last post date, YYYY-MM-DD")
    ap.add_argument("--out", default=os.path.join(H.ROOT, "out", "summary-sheet.csv"))
    ap.add_argument("--push", action="store_true", help="also write the rows into the linked sheet")
    ap.add_argument("--key", default=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
                    help="service-account key file (default: $GOOGLE_SERVICE_ACCOUNT_JSON)")
    args = ap.parse_args()

    last = dt.date.fromisoformat(args.last) if args.last else dt.date.today()
    first = dt.date.fromisoformat(args.first) if args.first else last - dt.timedelta(days=59)
    rows = rows_for(H.mentions_in(H.read_csv(H.MENTIONS_CSV), first, last))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(f"{len(rows)} row(s), {first:%d %b} to {last:%d %b %Y} -> {args.out}")
    if args.push:
        if not args.key or not os.path.isfile(args.key):
            print("No service-account key - pass --key or set GOOGLE_SERVICE_ACCOUNT_JSON.")
            return 1
        link = str(H.load_yaml("settings").get("digest", {}).get("data_link", ""))
        push(rows, link, args.key)
        print(f"Wrote {len(rows)} row(s) to {link}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
