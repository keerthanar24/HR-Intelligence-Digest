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


def has_no_page(platform: str, entity: str) -> bool:
    """True where config records the entity as absent from the platform."""
    return platform_url(platform, entity).strip().lower() == "none"


def expected_new(week: dt.date) -> dict[tuple[str, str], int]:
    """How many new reviews each page gained, from the change in its count.

    This is the sweep's target number. The count is the platform's own tally,
    so it says how many reviews exist that the sweeper has not read yet -
    turning "did I get everything?" from a feeling into arithmetic.
    """
    prev = (week - dt.timedelta(days=7)).isoformat()
    this = week.isoformat()
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in H.read_csv(H.RATINGS_CSV):
        key = (row.get("entity"), row.get("platform"))
        count = H.to_int(row.get("review_count"), -1)
        if row.get("week_of") == this:
            counts.setdefault(key, {})["now"] = count
        elif row.get("week_of") == prev:
            counts.setdefault(key, {})["prev"] = count
    out = {}
    for key, seen in counts.items():
        if seen.get("now", -1) >= 0 and seen.get("prev", -1) >= 0:
            out[key] = seen["now"] - seen["prev"]
    return out


def show_status(week: dt.date) -> int:
    entities = H.entity_names()
    rows = [r for r in H.read_csv(H.RATINGS_CSV) if r.get("week_of") == week.isoformat()]
    have = {(r.get("entity"), r.get("platform")): r for r in rows}

    import collections
    logged = collections.Counter(
        (m.get("entity"), m.get("platform"))
        for m in H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), week))
    expected = expected_new(week)

    print(f"Rating snapshot for week of {H.fmt_week(week)}\n")
    missing = 0
    for entity_id, name in entities.items():
        for platform in REVIEW_PLATFORMS:
            row = have.get((entity_id, platform))
            label = f"  {name:<20} {platform:<12}"
            if row:
                rating = row.get("overall_rating") or "?"
                count = row.get("review_count") or "?"
                key = (entity_id, platform)
                note = ""
                if key in expected:
                    want, got = expected[key], logged.get(key, 0)
                    if want > got:
                        note = f"  <-- {want} new review(s), {got} logged: {want - got} TO READ"
                    elif want > 0:
                        note = f"  ({want} new, all logged)"
                print(f"{label} {rating:>5}  ({count} reviews){note}")
            elif has_no_page(platform, entity_id):
                print(f"{label}     -  no page on this platform")
            else:
                missing += 1
                url = platform_url(platform, entity_id)
                print(f"{label}     -  NOT RECORDED")
                if url:
                    print(f"  {'':<33}{url}")
    total = sum(1 for e in entities for p in REVIEW_PLATFORMS if not has_no_page(p, e))
    print(f"\n{total - missing}/{total} recorded.")

    shortfall = {k: v - logged.get(k, 0) for k, v in expected.items() if v > logged.get(k, 0)}
    if shortfall:
        outstanding = sum(shortfall.values())
        print(f"\n{outstanding} review(s) exist that have not been logged as mentions:")
        for (entity_id, platform), count in sorted(shortfall.items()):
            print(f"  {entities.get(entity_id, entity_id):<20} {platform:<12} {count} to read")
        print("\nOpen each page, sort by newest, and log them:")
        print("  python3 scripts/log_mention.py --vocab")
        print("\nThe count is the platform's own tally, so it is the target. If a page shows")
        print("fewer new reviews than the count implies, a review was edited or removed -")
        print("note it and move on rather than hunting.")
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
    parser.add_argument("-c", "--reviews", type=int,
                        help="total review count on the page; omit only if the page "
                             "does not show one, and it will be flagged")
    parser.add_argument("--culture", type=float, help="sub-score: culture and values")
    parser.add_argument("--work-life", type=float, help="sub-score: work/life balance")
    parser.add_argument("--career", type=float, help="sub-score: career opportunities")
    parser.add_argument("--pay", type=float, help="sub-score: compensation and benefits")
    parser.add_argument("--job-security", type=float, help="sub-score: job security")
    parser.add_argument("--recommend", type=int, help="percent who recommend")
    parser.add_argument("--ceo-approval", type=int,
                        help="percent who approve of the CEO (Glassdoor, when the page shows it)")
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
    if args.rating is None:
        print("--rating is required.", file=sys.stderr)
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
        "review_count": "" if args.reviews is None else str(args.reviews),
        # A blank here used to mean either "the platform does not publish this"
        # or "nobody recorded it", and only the second is a problem worth
        # chasing. AmbitionBox prints neither figure; Glassdoor prints CEO
        # approval only on profiles with enough ratings.
        "recommend_pct": (str(args.recommend) if args.recommend is not None
                          else H.absent_value(args.platform, "recommend_pct")),
        "ceo_approval_pct": (str(args.ceo_approval) if args.ceo_approval is not None
                             else H.absent_value(args.platform, "ceo_approval_pct")),
        "work_life_balance": "" if args.work_life is None else f"{args.work_life:.1f}",
        "salary_benefits": "" if args.pay is None else f"{args.pay:.1f}",
        "job_security": "" if args.job_security is None else f"{args.job_security:.1f}",
        "career_growth": "" if args.career is None else f"{args.career:.1f}",
        "culture": "" if args.culture is None else f"{args.culture:.1f}",
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

    count_text = f"{args.reviews} reviews" if args.reviews is not None else "review count MISSING"
    print(f"Recorded {entities[args.entity]} / {args.platform}: "
          f"{args.rating:.2f} ({count_text}), week of {week}.")
    if args.reviews is None:
        print("  WARNING: no review count. A rating move is unreadable without it - "
              "0.1 on 40 reviews is one review. Add it with --replace when you have it.")
    elif args.reviews < 10:
        print(f"  NOTE: only {args.reviews} review(s). At this base a single new review "
              "swings the score by a lot; treat week-on-week movement as noise.")

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
