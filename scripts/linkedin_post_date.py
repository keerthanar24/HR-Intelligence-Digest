#!/usr/bin/env python3
"""Turn a LinkedIn post URL into the date the post was published.

LinkedIn shows a relative timestamp - "3w", "1mo", "2mo" - and nothing else.
That is fine for reading and useless for this programme: week 1 reports a
60-day baseline with a hard edge at 28 Jul, and "1mo" straddles nothing while
"2mo" could fall either side of it. Logging the wrong date puts a row in the
wrong window, and on a 60-day baseline that is the difference between a
mention being in the digest and not existing.

The publish time is already in the URL. Every post carries an activity id, and
its top 42 bits are the Unix time in milliseconds - so the date can be read off
without opening anything or asking LinkedIn.

    python3 scripts/linkedin_post_date.py "https://www.linkedin.com/posts/...-activity-7370000000000000000-AbCd"
    python3 scripts/linkedin_post_date.py 7370000000000000000 --week 2026-09-19

This is an observed encoding, not a documented one. Treat it as a cross-check:
if it disagrees with the "3w" the page shows, believe the page and say so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402

# urn:li:activity:7370…, …-activity-7370…-AbCd, or the bare number.
ID_PATTERN = re.compile(r"(?:activity[:\-]|share[:\-]|ugcPost[:\-])?(\d{19})")

# The id is 64 bits; the top 42 are milliseconds since the epoch.
TIMESTAMP_BITS = 22


def activity_id(text: str) -> int | None:
    match = ID_PATTERN.search(text or "")
    return int(match.group(1)) if match else None


def published(post_id: int) -> dt.datetime | None:
    """The post's publish time, or None if the id decodes to nonsense."""
    moment = dt.datetime.utcfromtimestamp((post_id >> TIMESTAMP_BITS) / 1000)
    # LinkedIn ids of this length start in 2022. Anything outside a sane band
    # means the number was not an activity id, and a confident wrong date is
    # worse here than no date at all.
    if not dt.datetime(2020, 1, 1) <= moment <= dt.datetime.utcnow() + dt.timedelta(days=2):
        return None
    return moment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the post URL, or just its activity id")
    parser.add_argument("--week", help="check it against this reporting week's window")
    args = parser.parse_args()

    post_id = activity_id(args.url)
    if post_id is None:
        print("No activity id in that. Use the post's own link - the three dots on "
              "the post, then 'Copy link to post'. The company page URL will not do.",
              file=sys.stderr)
        return 2

    moment = published(post_id)
    if moment is None:
        print(f"{post_id} does not decode to a plausible date. Read the date off the "
              "page instead.", file=sys.stderr)
        return 2

    day = moment.date()
    print(f"\nActivity id : {post_id}")
    print(f"Published   : {day.isoformat()} ({moment:%H:%M} UTC)")
    print(f"Log it with : -d {day.isoformat()}")

    if not args.week:
        return 0
    week = H.parse_date(args.week)
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.week_start_of(week)
    settings = H.load_yaml("settings")
    window = H.baseline_window(week, settings)
    if window:
        first, last, days = window
        label = f"the {days}-day baseline, {first} to {last}"
    else:
        first, last = week, week + dt.timedelta(days=6)
        label = f"week {first} to {last}"

    print()
    if first <= day <= last:
        print(f"IN WINDOW  - {label}.")
        return 0
    side = "before it starts" if day < first else "after it ends"
    print(f"OUT OF WINDOW - {label}. This post is {side}.")
    print("  A post outside the window is not a finding for this digest. Leave it "
          "unlogged; the sweep row already records that the page was read.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
