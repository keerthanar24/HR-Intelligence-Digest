#!/usr/bin/env python3
"""Record the week: how long it took, and whether any of it was news.

docs/07-phase3-review.md decides at week 8 whether this programme becomes
permanent, and two of the seven things it asks for cannot be derived from the
data: how many hours the sweep actually took, and how much of the digest was
genuinely new to the four recipients. Reconstructed from memory eight weeks
later, both answers are whatever the person answering already believes - which
is how a trial gets institutionalised on vibes.

So they are asked once a week, at the moment the digest goes out, while the
answers are still fresh. Everything else on that list is counted from the data
and filled in automatically.

    python3 scripts/log_week.py                 # the reporting week
    python3 scripts/log_week.py --week 2026-09-19
    python3 scripts/log_week.py --show          # what has been recorded
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def mentions_of(week: dt.date, settings: dict) -> list[dict]:
    """The mentions this week's digest reported - baseline window included.

    Week 1 reports a sixty-day baseline, not seven days. If the effort log
    counted seven, it would ask how many of nought mentions were new while the
    digest that just went out carried sixty days of them.
    """
    rows = H.read_csv(H.MENTIONS_CSV)
    window = H.baseline_window(week, settings)
    if window:
        first, last, _days = window
        return H.mentions_in(rows, first, last)
    return H.mentions_for_week(rows, week)


def derived(week: dt.date, settings: dict | None = None) -> dict:
    """The parts of the week that the data already knows."""
    settings = H.load_yaml("settings") if settings is None else settings
    mentions = mentions_of(week, settings)
    in_scope = [m for m in mentions if (m.get("status") or "") != "out_of_scope"]
    escalations = [e for e in H.read_csv(H.ESCALATIONS_CSV)
                   if e.get("week_of") == week.isoformat()]
    ratings = [r for r in H.read_csv(H.RATINGS_CSV) if r.get("week_of") == week.isoformat()]
    platforms = {r.get("platform") for r in ratings if r.get("platform")}
    platforms |= {m.get("platform") for m in in_scope if m.get("platform")}
    return {
        "mentions": len(in_scope),
        "red_flags": len(escalations),
        "out_of_scope": len(mentions) - len(in_scope),
        "platforms_swept": "|".join(sorted(p for p in platforms if p)),
    }


def ask(prompt: str, *, default: str = "", numeric: bool = False,
        most: int | None = None) -> str:
    while True:
        shown = f" [{default}]" if default else ""
        raw = input(f"  {prompt}{shown}\n  > ").strip() or default
        if numeric and raw and not raw.isdigit():
            print("    a whole number, please.")
            continue
        if most is not None and raw.isdigit() and int(raw) > most:
            print(f"    there were only {most} - it cannot be more than that.")
            continue
        return raw


def show() -> int:
    rows = H.read_csv(H.WEEKLY_LOG_CSV)
    if not rows:
        print("No weeks recorded yet.")
        return 0
    print(f"{len(rows)} week(s) recorded\n")
    print(f"  {'week':<12} {'mins':>5} {'mentions':>9} {'flags':>6} {'new to them':>12}  swept by")
    total_minutes = 0
    for row in sorted(rows, key=lambda r: r.get("week_of", "")):
        minutes = H.to_int(row.get("minutes_spent"), 0)
        total_minutes += minutes
        print(f"  {row.get('week_of',''):<12} {minutes:>5} {row.get('mentions',''):>9} "
              f"{row.get('red_flags',''):>6} {row.get('new_to_recipients',''):>12}  "
              f"{row.get('swept_by','')}")
    hours = total_minutes / 60
    print(f"\n  {hours:.1f} hours across {len(rows)} week(s), "
          f"averaging {hours / len(rows):.1f} per week.")
    print("  Budget is 3-4 hours a week (docs/00-brief.md).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", help="week_of start day; default = the reporting week")
    parser.add_argument("--show", action="store_true", help="what has been recorded so far")
    parser.add_argument("--by", default="", help="who did the sweep")
    args = parser.parse_args()

    if args.show:
        return show()

    week = H.parse_date(args.week) if args.week else H.last_complete_week()
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.week_start_of(week)

    existing = H.read_csv(H.WEEKLY_LOG_CSV)
    if any(r.get("week_of") == week.isoformat() for r in existing):
        print(f"{H.fmt_week(week)} is already recorded. "
              "Re-running would double-count the hours.", file=sys.stderr)
        return 3

    settings = H.load_yaml("settings")
    facts = derived(week, settings)
    window = H.baseline_window(week, settings)
    print(f"\nRecording {H.fmt_week(week)}")
    if window:
        first, last, days = window
        print(f"  Week 1 - the {days}-day baseline, "
              f"{H.day_month(first)} to {H.day_month(last, year=True)}.")
    print(f"  From the data: {facts['mentions']} mention(s), {facts['red_flags']} red flag(s), "
          f"{facts['out_of_scope']} out of scope.\n")

    owner = str(settings.get("programme", {}).get("owner", ""))
    minutes = ask("Minutes spent on the whole cycle - sweeping, tagging, building, sending",
                  numeric=True)
    new_count = ask(f"Of those {facts['mentions']} mention(s), how many were genuinely NEW to "
                    "the four? (not already known through normal channels)",
                    numeric=True, most=facts["mentions"])
    acted = ask("Was anything acted on outside this programme because of the digest? "
                "Briefly, or blank")
    notes = ask("Anything else worth remembering about this week? Or blank")

    row = {
        "week_of": week.isoformat(),
        "logged_at": dt.date.today().isoformat(),
        "swept_by": args.by or (owner if owner and not H.is_todo(owner) else "desk"),
        "minutes_spent": minutes,
        "new_to_recipients": new_count,
        "acted_on_elsewhere": acted,
        "notes": notes,
        **facts,
    }
    H.append_csv(H.WEEKLY_LOG_CSV, H.WEEKLY_LOG_FIELDS, [row])
    print(f"\nRecorded {H.fmt_week(week)}: {minutes or '?'} minutes, "
          f"{new_count or '?'} of {facts['mentions']} new to the four.")
    print("See it all with: python3 scripts/log_week.py --show")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except H.FileInUse as locked:
        # A locked file is somebody's Excel window, not a bug. Say so once,
        # without a traceback that buries the one sentence that matters.
        print(f"\n{locked}", file=sys.stderr)
        raise SystemExit(4)
