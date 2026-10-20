#!/usr/bin/env python3
"""The short sheet: one tab, only what a reader needs.

The tracking sheet keeps every field the digest is built from. This is the
other one - a single tab listing each employee review or post in the window,
newest first, with where it was posted, what it said and a link to it.
Company posts and out-of-scope finds are left out, as they are in the digest.

  python3 scripts/summary_sheet.py                    # last 60 days to today
  python3 scripts/summary_sheet.py --from 2026-08-18 --to 2026-10-16

Writes out/summary-sheet.csv, ready for File > Import in Google Sheets.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="first", help="first post date, YYYY-MM-DD")
    ap.add_argument("--to", dest="last", help="last post date, YYYY-MM-DD")
    ap.add_argument("--out", default=os.path.join(H.ROOT, "out", "summary-sheet.csv"))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
