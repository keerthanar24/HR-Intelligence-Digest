#!/usr/bin/env python3
"""The 3-minute daily check that makes same-day escalation possible.

Reading every review daily is not realistic. Checking a NUMBER is: each review
page shows a review count, and the count moving is the only signal needed. If
it has not moved, nothing was posted and the check is over. If it has, open
that one page and read what arrived.

This prints each page with its last known count, so the check is a comparison
rather than a search.

    python3 scripts/daily_check.py                 # today's check
    python3 scripts/daily_check.py --bump ambitionbox rk_world 52
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

REVIEW_PLATFORMS = ["ambitionbox", "glassdoor"]


def latest_counts() -> dict[tuple[str, str], tuple[str, str]]:
    """(entity, platform) -> (review_count, week_of) from the newest snapshot."""
    latest: dict[tuple[str, str], dict] = {}
    for row in H.read_csv(H.RATINGS_CSV):
        key = (row.get("entity"), row.get("platform"))
        if key not in latest or row.get("week_of", "") >= latest[key].get("week_of", ""):
            latest[key] = row
    return {k: (v.get("review_count", ""), v.get("week_of", "")) for k, v in latest.items()}


def platform_url(platform: str, entity: str) -> str:
    for spec in H.load_yaml("sources").get("platforms", []):
        if spec["id"] == platform:
            url = (spec.get("urls") or {}).get(entity, "")
            return "" if H.is_todo(url) else url
    return ""


def record_count(entity: str, platform: str, count: int, by: str = "desk") -> None:
    """Write the new count into this week's rating snapshot.

    --bump said it recorded and did not: it computed the difference, printed
    it, and returned. So nothing anywhere showed that a daily check had ever
    been done, and "same-day cover" rested on somebody's memory of having
    looked - the failure this whole project is built to prevent, sitting in
    the script whose entire job is preventing it.

    Only review_count and the capture stamp move. A bump knows the count and
    nothing else; overwriting the rating or the sub-scores with blanks would
    lose the Friday snapshot's work.
    """
    today = dt.date.today()
    week = H.week_start_of(today)
    rows = H.read_csv(H.RATINGS_CSV)
    for row in rows:
        if (row.get("entity") == entity and row.get("platform") == platform
                and row.get("week_of") == week.isoformat()):
            row["review_count"] = str(count)
            row["captured_at"] = today.isoformat()
            row["captured_by"] = by
            break
    else:
        rows.append({**{f: "" for f in H.RATING_FIELDS},
                     "week_of": week.isoformat(),
                     "captured_at": today.isoformat(), "captured_by": by,
                     "entity": entity, "platform": platform,
                     "review_count": str(count),
                     "notes": "count only, from the daily check"})
    rows.sort(key=lambda r: (r.get("week_of", ""), r.get("entity", ""),
                             r.get("platform", "")))
    H.write_csv(H.RATINGS_CSV, H.RATING_FIELDS, rows)


def last_checked() -> dt.date | None:
    """The most recent day anybody looked at a review page."""
    return H.last_review_page_check()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bump", nargs=3, metavar=("PLATFORM", "ENTITY", "COUNT"),
                        help="record that a page's count moved, without a full snapshot")
    parser.add_argument("--stale-after", type=int, metavar="DAYS",
                        help="exit non-zero if nobody has checked a review page "
                             "in this many days; for CI, where the useful signal "
                             "is that the check is NOT being done")
    args = parser.parse_args()

    entities = H.entity_names()
    counts = latest_counts()

    if args.stale_after is not None:
        seen = last_checked()
        if seen is None:
            print("No review page has ever been checked. Same-day cover on "
                  "AmbitionBox and Glassdoor is not being delivered.", file=sys.stderr)
            return 1
        age = (dt.date.today() - seen).days
        if age > args.stale_after:
            print(f"Last review-page check was {seen} - {age} days ago.",
                  file=sys.stderr)
            print("The digest tells four people that escalation is same-day. On "
                  "these two platforms that is currently untrue.", file=sys.stderr)
            print("  python3 scripts/daily_check.py", file=sys.stderr)
            return 1
        print(f"Last review-page check: {seen} ({age} day(s) ago). Within "
              f"{args.stale_after}.")
        return 0

    if args.bump:
        platform, entity, count = args.bump
        if entity not in entities or platform not in REVIEW_PLATFORMS:
            print("Unknown entity or platform.", file=sys.stderr)
            return 2
        before = H.to_int(counts.get((entity, platform), ("", ""))[0], -1)
        after = H.to_int(count, -1)
        print(f"{entities[entity]} / {platform}: {before} -> {after}")
        if after >= 0:
            record_count(entity, platform, after)
            print(f"Recorded. {H.RATINGS_CSV.rsplit('/', 1)[-1]} now shows "
                  f"{after} for this week.")
        if after > before >= 0:
            print(f"\n{after - before} new review(s). Open the page and read them:")
            print(f"  {platform_url(platform, entity)}")
            print("\nLog each one, then check it against the five red-flag triggers:")
            print("  python3 scripts/log_mention.py --vocab")
            print("  python3 scripts/red_flags.py --scan")
        elif after < before:
            # build_digest raises count_dropped at the Friday gate, which is
            # five days after the person who could still remember what they
            # read. A count cannot fall on its own: either a review was taken
            # down - itself worth knowing - or the page was misread. Saying so
            # here costs one line and saves a week-on-week delta built on a
            # number nobody questioned.
            print(f"\nWARNING: the count FELL by {before - after}. A review count "
                  "does not fall on its own.")
            print("  Either a review was removed - worth noting - or the page was "
                  "misread. Check before relying on it.")
            print("  Recorded anyway; the Friday gate will raise count_dropped too.")
        else:
            print("No change - nothing to read.")
        return 0

    print(f"Daily check  {dt.date.today().strftime('%a %d %b %Y')}")
    print("Compare the count on each page with the number below. "
          "Only open a page whose count has moved.\n")

    rows = 0
    for entity_id, name in entities.items():
        for platform in REVIEW_PLATFORMS:
            url = platform_url(platform, entity_id)
            if not url or url.strip().lower() == "none":
                continue
            count, week = counts.get((entity_id, platform), ("?", ""))
            rows += 1
            print(f"  [ ] {name:<20} {platform:<12} last known: {count or '?':>4} reviews"
                  f"  (as of {week or 'never'})")
            print(f"      {url}")
    print(f"\n{rows} page(s). Roughly 20 seconds each.")
    print("\nIf a count moved:")
    print("  python3 scripts/daily_check.py --bump <platform> <entity> <new count>")
    print("\nThis is what makes same-day escalation real on the platforms that cannot be")
    print("polled. It does not replace the Friday sweep, which reads and tags everything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
