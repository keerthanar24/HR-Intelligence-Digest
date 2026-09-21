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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bump", nargs=3, metavar=("PLATFORM", "ENTITY", "COUNT"),
                        help="record that a page's count moved, without a full snapshot")
    args = parser.parse_args()

    entities = H.entity_names()
    counts = latest_counts()

    if args.bump:
        platform, entity, count = args.bump
        if entity not in entities or platform not in REVIEW_PLATFORMS:
            print("Unknown entity or platform.", file=sys.stderr)
            return 2
        before = H.to_int(counts.get((entity, platform), ("", ""))[0], -1)
        after = H.to_int(count, -1)
        print(f"{entities[entity]} / {platform}: {before} -> {after}")
        if after > before >= 0:
            print(f"\n{after - before} new review(s). Open the page and read them:")
            print(f"  {platform_url(platform, entity)}")
            print("\nLog each one, then check it against the five red-flag triggers:")
            print("  python3 scripts/log_mention.py --vocab")
            print("  python3 scripts/red_flags.py --scan")
        else:
            print("No increase - nothing to read.")
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
