#!/usr/bin/env python3
"""Record that a channel was checked, whether or not it held anything.

A review site proves its own coverage: the rating snapshot carries the review
count, and the change in that count is arithmetic anyone can check. LinkedIn,
X, Indeed, Quora, YouTube and Google Reviews carry no count. So a morning spent
on YouTube finding nothing leaves no trace, and at the month-2 review an empty
channel and one nobody ever opened look exactly alike - which is the difference
the decision turns on.

This writes the one fact that cannot be derived: somebody looked.

    python3 scripts/log_sweep.py                      # walk this week's channels
    python3 scripts/log_sweep.py --checked quora,x    # straight in
    python3 scripts/log_sweep.py --show
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def due(week: dt.date, settings: dict) -> list[str]:
    """The channels this prompt should ask about.

    A channel the collector genuinely covers - Reddit, news, Quora - is not
    asked about here; the collector records it on a successful run, and a
    failed run still leaves it on the digest's not-swept list.

    A feed is not always cover, though. Indeed has an alert AND stays on the
    manual rotation: its company pages are indexed but individual reviews
    often are not, and an alert only fires on what Google newly indexes. That
    distinction is already in sources.yaml as `collection:` - manual means a
    person still has to open it, whatever feeds point at it - so this reads
    that rather than inferring cover from the existence of a feed.
    """
    sources = H.load_yaml("sources")
    fed = {f.get("platform") for f in sources.get("feeds", [])
           if f.get("enabled") and f.get("platform")}
    collection = {p["id"]: str(p.get("collection", "manual")).lower()
                  for p in sources.get("platforms", [])}
    return [p for p in H.unverified_channels(week, settings)
            if not (collection.get(p, "manual") != "manual" and p in fed)]


def ask(prompt: str, *, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    return input(f"  {prompt}{shown}\n  > ").strip() or default


def record(week: dt.date, platforms: list[str], by: str,
           found: dict | None = None, notes: dict | None = None) -> int:
    """Write one row per channel, replacing any earlier row for the same week."""
    found, notes = found or {}, notes or {}
    existing = [r for r in H.read_csv(H.SWEEPS_CSV)
                if not (r.get("week_of") == week.isoformat()
                        and r.get("platform") in platforms)]
    rows = existing + [{
        "week_of": week.isoformat(),
        "platform": platform,
        "checked_at": dt.date.today().isoformat(),
        "checked_by": by,
        "found": found.get(platform, ""),
        "notes": notes.get(platform, ""),
    } for platform in platforms]
    rows.sort(key=lambda r: (r.get("week_of", ""), r.get("platform", "")))
    H.write_csv(H.SWEEPS_CSV, H.SWEEP_FIELDS, rows)
    return len(platforms)


def show(settings: dict) -> int:
    rows = H.read_csv(H.SWEEPS_CSV)
    if not rows:
        print("No channel checks recorded yet.")
        print("Record this week's with: python3 scripts/log_sweep.py")
        return 0
    names = H.platform_names()
    by_week: dict[str, list[dict]] = {}
    for row in rows:
        by_week.setdefault(row.get("week_of", ""), []).append(row)
    for week_of in sorted(by_week):
        week = H.parse_date(week_of)
        expected = set(due(week, settings)) if week else set()
        checked = {r["platform"] for r in by_week[week_of]}
        print(f"\n{H.fmt_week(week) if week else week_of}")
        for row in sorted(by_week[week_of], key=lambda r: r["platform"]):
            found = row.get("found") or "0"
            print(f"  checked   {names.get(row['platform'], row['platform']):<16} "
                  f"{found} found   {row.get('checked_by', '')}")
        for platform in sorted(expected - checked):
            print(f"  NOT DONE  {names.get(platform, platform)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", help="week_of start day; default = the current week")
    parser.add_argument("--checked", help="comma-separated platform ids, skipping the prompts")
    parser.add_argument("--show", action="store_true", help="what has been recorded")
    parser.add_argument("--by", default="", help="who did the sweep")
    args = parser.parse_args()

    settings = H.load_yaml("settings")
    if args.show:
        return show(settings)

    week = H.parse_date(args.week) if args.week else dt.date.today()
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.week_start_of(week)

    owner = str(settings.get("programme", {}).get("owner", ""))
    by = args.by or (owner if owner and not H.is_todo(owner) else "desk")
    names = H.platform_names()
    expected = due(week, settings)
    if not expected:
        print(f"No channel needs recording for {H.fmt_week(week)} — "
              "the review sites prove their own coverage.")
        return 0

    if args.checked:
        wanted = [p.strip().lower() for p in args.checked.split(",") if p.strip()]
        unknown = [p for p in wanted if p not in names]
        if unknown:
            print(f"Unknown platform id: {', '.join(unknown)}", file=sys.stderr)
            print(f"One of: {', '.join(sorted(names))}", file=sys.stderr)
            return 2
        record(week, wanted, by)
        print(f"Recorded {len(wanted)} channel(s) checked for {H.fmt_week(week)}.")
        return 0

    already = H.channels_checked(week)
    print(f"\nChannels to record for {H.fmt_week(week)}")
    print("These carry no review count, so nothing else can show they were looked at.")
    print("Answer for the ones you actually opened; blank skips a channel.\n")

    checked, found, notes = [], {}, {}
    for platform in expected:
        label = names.get(platform, platform)
        mark = "  (already recorded)" if platform in already else ""
        answer = ask(f"{label} — did you check it? y/N{mark}", default="n")
        if not answer.lower().startswith("y"):
            continue
        checked.append(platform)
        count = ask(f"  how many in-scope items did {label} hold? (0 is a real answer)",
                    default="0")
        found[platform] = count if count.isdigit() else "0"
        if found[platform] != "0":
            notes[platform] = ask("  anything worth remembering? Or blank")

    if not checked:
        print("\nNothing recorded. The digest will report these channels as not swept.")
        return 0

    record(week, checked, by, found, notes)
    total = sum(int(found.get(p, "0")) for p in checked)
    skipped = [names.get(p, p) for p in expected if p not in checked]
    print(f"\nRecorded {len(checked)} channel(s) checked, {total} item(s) found.")
    if skipped:
        print(f"Still not swept: {', '.join(skipped)} — the digest will say so.")
    print("See it all with: python3 scripts/log_sweep.py --show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
