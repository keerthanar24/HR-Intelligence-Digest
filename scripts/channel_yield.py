#!/usr/bin/env python3
"""What each channel has actually returned, against what it costs to sweep.

docs/07-phase3-review.md asks for "total mentions by entity and platform" and
names "volume concentrated in one entity or platform" as pointing to narrowing
scope. That is a question about yield, and yield is only meaningful beside
coverage: a channel with nothing found and nothing swept says nothing at all,
and is the easy one to mistake for a quiet channel.

So this puts the two columns side by side. A channel swept every week with
nothing to show has earned its answer. A channel nobody opened has not.

    python3 scripts/channel_yield.py
    python3 scripts/channel_yield.py --since 2026-09-19

It answers "is this channel worth the time" with a number rather than an
impression, which is the difference between narrowing scope and guessing.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def gather(since: dt.date | None) -> tuple[dict, dict, dict, int]:
    """(found, swept_weeks, cadence, weeks) per platform."""
    mentions = [m for m in H.read_csv(H.MENTIONS_CSV)
                if (m.get("status") or "") != "out_of_scope"]
    sweeps = H.read_csv(H.SWEEPS_CSV)
    ratings = H.read_csv(H.RATINGS_CSV)
    if since:
        cutoff = since.isoformat()
        mentions = [m for m in mentions if (m.get("week_of") or "") >= cutoff]
        sweeps = [s for s in sweeps if (s.get("week_of") or "") >= cutoff]
        ratings = [r for r in ratings if (r.get("week_of") or "") >= cutoff]

    found = collections.Counter(m.get("platform") for m in mentions if m.get("platform"))
    swept = collections.defaultdict(set)
    for row in sweeps:
        if row.get("platform") and row.get("week_of"):
            swept[row["platform"]].add(row["week_of"])
    # A review site proves its own coverage through the rating snapshot; it
    # never appears in sweeps.csv and would otherwise read as never swept.
    for row in ratings:
        if row.get("platform") and row.get("week_of"):
            swept[row["platform"]].add(row["week_of"])

    weeks = {w for w in (
        [m.get("week_of") for m in mentions] + [s.get("week_of") for s in sweeps]
        + [r.get("week_of") for r in ratings]) if w}
    cadence = {p["id"]: str(p.get("cadence", "weekly"))
               for p in H.load_yaml("sources").get("platforms", [])}
    return found, swept, cadence, len(weeks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", help="only weeks from this week_of onward")
    args = parser.parse_args()

    since = H.parse_date(args.since) if args.since else None
    if args.since and since is None:
        print(f"Could not read --since {args.since!r}", file=sys.stderr)
        return 2
    found, swept, cadence, weeks = gather(since)
    names = H.platform_names()
    if not weeks:
        print("Nothing recorded yet.")
        return 0

    print(f"\nAcross {weeks} recorded week(s)"
          f"{' since ' + since.isoformat() if since else ''}\n")
    print(f"  {'Channel':<16} {'Found':>6} {'Swept':>6}  {'Cadence':<12} Reading")
    print(f"  {'-' * 16} {'-' * 6} {'-' * 6}  {'-' * 12} {'-' * 34}")

    ordered = sorted(names, key=lambda p: (-found.get(p, 0), names[p]))
    for platform in ordered:
        hits, cover = found.get(platform, 0), len(swept.get(platform, ()))
        if not cover:
            reading = "NEVER SWEPT - says nothing yet"
        elif hits:
            reading = f"{hits / cover:.1f} per week swept"
        else:
            reading = "nothing, and it was looked at"
        print(f"  {names[platform]:<16} {hits:>6} {cover:>6}  "
              f"{cadence.get(platform, 'weekly'):<12} {reading}")

    productive = [p for p in names if found.get(p, 0)]
    barren = [p for p in names if not found.get(p, 0) and swept.get(p)]
    unknown = [p for p in names if not swept.get(p)]
    total = sum(found.values())

    print()
    if productive:
        share = sum(found[p] for p in productive[:3])
        print(f"{total} mention(s) in all, from {len(productive)} of {len(names)} channels: "
              f"{', '.join(names[p] for p in productive)}.")
        if total and share == total and len(productive) <= 3:
            print("  Everything found came from those. On this evidence the Month 2 "
                  "question is whether the rest earn their weekly slot.")
    if barren:
        print(f"\n{len(barren)} channel(s) swept and empty: {', '.join(names[p] for p in barren)}.")
        print("  That is a real answer - the time was spent and nothing was there.")
    if unknown:
        print(f"\n{len(unknown)} channel(s) NEVER swept: {', '.join(names[p] for p in unknown)}.")
        print("  These are not quiet channels; they are unmeasured ones. Dropping a "
              "channel on this basis would be guessing, not narrowing.")
    print("\nThis is the volume-by-platform input to docs/07-phase3-review.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
