#!/usr/bin/env python3
"""Record a rating snapshot during the sweep, and show what is still missing.

The baseline sweep is eight numbers - four entities on two review sites - and
they are the one thing in this programme that cannot be reconstructed later.
This validates and files each one as you read it off the page.

    python3 scripts/log_rating.py --status
    python3 scripts/log_rating.py -e rk_world -p ambitionbox -r 3.3 -c 121
    python3 scripts/log_rating.py --status --week 2026-09-21
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

REVIEW_PLATFORMS = ["ambitionbox", "glassdoor"]


def platform_url(platform: str, entity: str) -> str:
    for spec in H.load_yaml("sources").get("platforms", []):
        if spec["id"] == platform:
            url = (spec.get("urls") or {}).get(entity, "")
            return "" if H.is_todo(url) else url
    return ""


def show_status(week: dt.date) -> int:
    entities = H.entity_names()
    rows = [r for r in H.read_csv(H.RATINGS_CSV) if r.get("week_of") == week.isoformat()]
    have = {(r.get("entity"), r.get("platform")): r for r in rows}

    print(f"Rating snapshot for week of {H.fmt_week(week)}\n")
    missing = 0
    for entity_id, name in entities.items():
        for platform in REVIEW_PLATFORMS:
            row = have.get((entity_id, platform))
            label = f"  {name:<20} {platform:<12}"
            if row:
                rating = row.get("overall_rating") or "?"
                count = row.get("review_count") or "?"
                print(f"{label} {rating:>5}  ({count} reviews)")
            else:
                missing += 1
                url = platform_url(platform, entity_id)
                print(f"{label}     -  NOT RECORDED")
                if url:
                    print(f"  {'':<33}{url}")
    total = len(entities) * len(REVIEW_PLATFORMS)
    print(f"\n{total - missing}/{total} recorded.")
    if missing:
        print("Record each one with:")
        print("  python3 scripts/log_rating.py -e <entity> -p <platform> -r <rating> -c <count>")
    else:
        print("Week complete. Next: python3 scripts/build_digest.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-e", "--entity")
    parser.add_argument("-p", "--platform")
    parser.add_argument("-r", "--rating", type=float)
    parser.add_argument("-c", "--reviews", type=int, help="total review count on the page")
    parser.add_argument("--week", help="week_of Monday; defaults to the current week")
    parser.add_argument("--by", default="desk")
    parser.add_argument("--notes", default="")
    parser.add_argument("--status", action="store_true", help="show what is still missing")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite an existing snapshot for this entity/platform/week")
    args = parser.parse_args()

    week = H.parse_date(args.week) if args.week else dt.date.today()
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.monday_of(week)

    if args.status or not args.entity:
        return show_status(week)

    entities = H.entity_names()
    if args.entity not in entities:
        print(f"Unknown entity {args.entity!r}. One of: {', '.join(entities)}", file=sys.stderr)
        return 2
    if args.platform not in REVIEW_PLATFORMS:
        print(f"Unknown platform {args.platform!r}. One of: {', '.join(REVIEW_PLATFORMS)}",
              file=sys.stderr)
        return 2
    if args.rating is None or args.reviews is None:
        print("Both --rating and --reviews are needed: a rating move means nothing "
              "without the count behind it.", file=sys.stderr)
        return 2
    if not 1.0 <= args.rating <= 5.0:
        print(f"Rating {args.rating} is outside 1.0-5.0 - misread?", file=sys.stderr)
        return 2

    existing = H.read_csv(H.RATINGS_CSV)
    key = (args.entity, args.platform, week.isoformat())
    clash = [r for r in existing
             if (r.get("entity"), r.get("platform"), r.get("week_of")) == key]
    if clash and not args.replace:
        prior = clash[-1]
        print(f"Already recorded for this week: {prior.get('overall_rating')} "
              f"({prior.get('review_count')} reviews). Use --replace to correct it.",
              file=sys.stderr)
        return 1

    rows = [r for r in existing if (r.get("entity"), r.get("platform"), r.get("week_of")) != key]
    rows.append({
        "week_of": week.isoformat(),
        "captured_at": dt.date.today().isoformat(),
        "captured_by": args.by,
        "entity": args.entity,
        "platform": args.platform,
        "overall_rating": f"{args.rating:.2f}",
        "review_count": str(args.reviews),
        "url": platform_url(args.platform, args.entity),
        "notes": args.notes,
    })
    rows.sort(key=lambda r: (r.get("week_of", ""), r.get("entity", ""), r.get("platform", "")))

    import csv
    with open(H.RATINGS_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=H.RATING_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in H.RATING_FIELDS})

    print(f"Recorded {entities[args.entity]} / {args.platform}: "
          f"{args.rating:.2f} ({args.reviews} reviews), week of {week}.")

    # Show the movement immediately - it is the whole point of the series.
    prior_week = (week - dt.timedelta(days=7)).isoformat()
    prior = [r for r in existing
             if (r.get("entity"), r.get("platform"), r.get("week_of"))
             == (args.entity, args.platform, prior_week)]
    if prior:
        was = H.to_float(prior[-1].get("overall_rating"))
        if was is not None:
            diff = args.rating - was
            print(f"  vs last week: {was:.2f} -> {args.rating:.2f} "
                  f"({'+' if diff >= 0 else ''}{diff:.2f})")
    else:
        print("  First snapshot for this entity/platform - this is the baseline.")
    print()
    return show_status(week)


if __name__ == "__main__":
    raise SystemExit(main())
