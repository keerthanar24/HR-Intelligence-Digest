#!/usr/bin/env python3
"""Run the automatable part of the weekly cycle, in order.

    collect feeds  ->  validate  ->  build the digest

What this does NOT do, because it cannot: Glassdoor, AmbitionBox and LinkedIn
block automated collection and offer no public API, and the brief commits to
staying inside their terms. Those - and sentiment tagging - stay with a person.
This exists so the machine does the parts it can and hands a person a
half-finished digest rather than a blank page.

    python3 scripts/weekly_run.py              # the reporting week
    python3 scripts/weekly_run.py --week 2026-09-19
    python3 scripts/weekly_run.py --no-collect # skip the network step
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def run(label: str, args: list[str]) -> int:
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
    result = subprocess.run([sys.executable] + args, cwd=os.path.dirname(HERE))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="week_of start day; default = the reporting week")
    parser.add_argument("--no-collect", action="store_true", help="skip the feed fetch")
    parser.add_argument("--strict", action="store_true",
                        help="fail if the week still has untagged mentions")
    args = parser.parse_args()

    week = H.parse_date(args.week) if args.week else H.last_complete_week()
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.week_start_of(week)

    print(f"Weekly run for {H.fmt_week(week)}  (today {dt.date.today()})")

    if not args.no_collect:
        # A feed outage must not stop the digest being built from what is
        # already logged, so a non-zero exit here is reported, not fatal.
        if run("1. Collect feeds (Reddit, news, X where configured)",
               ["scripts/collect_feeds.py", "--week", week.isoformat()]):
            print("\nCollection reported a problem - continuing with what is already logged.")

    validate_code = run("2. Validate config and data",
                        ["scripts/validate_data.py", "--week", week.isoformat()])
    if validate_code:
        print("\nValidation found ERRORS. Fix them before sending; "
              "the digest below is built anyway so you can see the state.")

    digest_args = ["scripts/build_digest.py", "--week", week.isoformat()]
    if args.strict:
        digest_args.append("--strict")
    digest_code = run("3. Build the digest", digest_args)

    mentions = H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), week)
    untagged = [m for m in mentions if not (m.get("sentiment") or "").strip()]
    ratings = [r for r in H.read_csv(H.RATINGS_CSV) if r.get("week_of") == week.isoformat()]

    print(f"\n{'=' * 68}\nSTILL NEEDS A PERSON\n{'=' * 68}")
    todo = []
    if not ratings:
        todo.append("Sweep Glassdoor and AmbitionBox and record the ratings "
                    "(python3 scripts/log_rating.py --status)")
    if untagged:
        todo.append(f"Tag {len(untagged)} collected mention(s): summary, sentiment, themes")
    todo.append("Sweep LinkedIn, and the fortnightly channels if due (make sweep)")
    todo.append("Confirm any red flags and send them same-day "
                "(python3 scripts/red_flags.py --scan)")
    if not todo[:1]:
        todo.append("Nothing outstanding - review the digest and send")
    for i, item in enumerate(todo, start=1):
        print(f"  {i}. {item}")

    return 1 if (validate_code or digest_code) else 0


if __name__ == "__main__":
    raise SystemExit(main())
