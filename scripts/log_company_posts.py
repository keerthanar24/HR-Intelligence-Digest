#!/usr/bin/env python3
"""Log a batch of LinkedIn company-page posts from their URLs.

Company page activity is in scope (docs/00-brief.md section 3), so the baseline
needs every post the four pages published between 28 Jul and 25 Sep - not just
the one that happened to get noticed. That is four pages of scrolling, and the
tedious part is not the reading: it is dating each post, deciding which side of
the window edge it falls, and not logging the same URL twice.

So paste the URLs and let this do that part. Each line is:

    <entity>  <post URL>  [themes]  [| one-line summary]

    robust_kommerce  https://...activity-7507227023769600000-AbCd  culture
    rk_world  https://...activity-75072...-XyZa  growth_learning | Post announcing 12 openings

Then:

    python3 scripts/log_company_posts.py posts.txt              # dry run, writes nothing
    python3 scripts/log_company_posts.py posts.txt --write

The dry run is the default on purpose - this writes many rows at once, and the
window decision is the whole point of looking before you commit.

Rows land as author_type=company with NO sentiment, which is what keeps the
employer out of its own score; see docs/05-sentiment-and-themes.md.

A company page also posts about its business. Put `out_of_scope` in the themes
field for a post that is commercial rather than employment - a store opening, a
product line, a festival greeting. It is still recorded, so the month-2 review
can see it was read and judged, and it counts toward nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402
import linkedin_post_date as L  # noqa: E402


def parse_line(line: str) -> tuple[dict | None, str]:
    """(row-ish dict, error). One line in, one post out."""
    text = line.split("#", 1)[0].strip()
    if not text:
        return None, ""
    summary = ""
    if "|" in text:
        text, summary = text.split("|", 1)
        summary = summary.strip()
    parts = text.split()
    if len(parts) < 2:
        return None, "need at least an entity and a URL"
    entity, url = parts[0], parts[1]
    themes = parts[2] if len(parts) > 2 else ""
    return {"entity": entity, "url": url, "themes": themes, "summary": summary}, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="file of lines; omit to read stdin")
    parser.add_argument("--week", help="reporting week; default = the current one")
    parser.add_argument("--platform", default="linkedin")
    parser.add_argument("--by", default="desk")
    parser.add_argument("--write", action="store_true",
                        help="actually write the rows (default is a dry run)")
    args = parser.parse_args()

    raw = (open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read())
    week = H.week_start_of(H.parse_date(args.week) if args.week else dt.date.today())
    settings = H.load_yaml("settings")
    window = H.baseline_window(week, settings)
    if window:
        first, last, days = window
        label = f"the {days}-day baseline, {first} to {last}"
    else:
        first, last = week, week + dt.timedelta(days=6)
        label = f"week {first} to {last}"

    entities = H.entity_names()
    existing = H.read_csv(H.MENTIONS_CSV)
    seen = {(r.get("url") or "").strip() for r in existing if (r.get("url") or "").strip()}

    keep, skipped, bad = [], [], []
    for number, line in enumerate(raw.splitlines(), 1):
        parsed, error = parse_line(line)
        if parsed is None:
            if error:
                bad.append((number, line.strip(), error))
            continue
        if parsed["entity"] not in entities:
            bad.append((number, parsed["url"], f"unknown entity {parsed['entity']!r}; "
                                               f"one of {', '.join(entities)}"))
            continue
        # A company page posts about its business, not only about itself as an
        # employer. A store launch or a product line is company page activity
        # and is NOT an employment signal, and logging it in scope would bury
        # three real employee reviews under four pieces of retail marketing.
        # Marking it out_of_scope keeps the record that it was read and judged
        # - which is the fact the month-2 review needs - without it counting.
        parsed["out_of_scope"] = parsed["themes"].strip().lower() == "out_of_scope"
        if parsed["out_of_scope"]:
            parsed["themes"] = ""
        for theme in H.split_themes(parsed["themes"]):
            if theme not in H.THEMES:
                bad.append((number, parsed["url"], f"unknown theme {theme!r}"))
                break
        else:
            post_id = L.activity_id(parsed["url"])
            moment = L.published(post_id) if post_id else None
            if moment is None:
                bad.append((number, parsed["url"],
                            "no activity id - use the post's own link, not the page's"))
                continue
            day = moment.date()
            if parsed["url"] in seen:
                skipped.append((parsed, day, "already logged"))
            elif not first <= day <= last:
                side = "before the window" if day < first else "after the window"
                skipped.append((parsed, day, side))
            else:
                parsed["post_date"] = day
                keep.append(parsed)

    print(f"\n{label}\n")
    for parsed in keep:
        mark = "OUT " if parsed["out_of_scope"] else "KEEP"
        what = ("not an employment signal" if parsed["out_of_scope"]
                else parsed["themes"] or "(no theme)")
        print(f"  {mark}  {parsed['post_date']}  {entities[parsed['entity']]:<22} {what}")
    for parsed, day, why in skipped:
        print(f"  skip  {day}  {entities[parsed['entity']]:<22} {why}")
    for number, where, why in bad:
        print(f"  BAD   line {number}: {why}")
        print(f"        {where}")

    if bad:
        print(f"\n{len(bad)} line(s) could not be read. Nothing written - fix those first.")
        return 2
    if not keep:
        print("\nNothing to log. Every URL was outside the window or already recorded.")
        return 0
    if not args.write:
        print(f"\n{len(keep)} row(s) would be logged. Dry run - nothing written.")
        print("Re-run with --write once the dates above look right.")
        return 0

    rows = list(existing)
    for parsed in keep:
        # week_of is the week the POST falls in, not the week it was captured.
        # The baseline gathers sixty days by post_date, so a row keyed to the
        # reporting week would sit in the digest at the right time and in the
        # wrong week everywhere else - and week 2 onward would compare against
        # a week that never held it.
        post_week = H.week_start_of(parsed["post_date"])
        rows.append({
            **{field: "" for field in H.MENTION_FIELDS},
            "mention_id": H.next_mention_id(rows, post_week),
            "week_of": post_week.isoformat(),
            "captured_at": dt.date.today().isoformat(),
            "captured_by": args.by,
            "entity": parsed["entity"],
            "platform": args.platform,
            "source_name": "Company page",
            "url": parsed["url"],
            "post_date": parsed["post_date"].isoformat(),
            "item_type": "post",
            "author_type": "company",
            "one_line_summary": parsed["summary"],
            "themes": parsed["themes"],
            # No sentiment, ever. The employer does not score itself.
            "sentiment": "",
            "status": ("out_of_scope" if parsed["out_of_scope"]
                       else "reviewed" if parsed["summary"] else "needs_review"),
        })
    H.write_csv(H.MENTIONS_CSV, H.MENTION_FIELDS, rows)

    print(f"\nLogged {len(keep)} company post(s) for {H.fmt_week(week)}.")
    out = sum(1 for p in keep if p["out_of_scope"])
    if out:
        print(f"{out} recorded as out of scope - read, judged commercial rather than "
              "employment, and excluded from every count.")
    missing = [p for p in keep if not p["summary"] and not p["out_of_scope"]]
    if missing:
        print(f"{len(missing)} have no one-line summary, so they are left as "
              "needs_review. Add one with the | form, or edit the row.")
    print("None carries a sentiment tag - that is deliberate; see "
          "docs/05-sentiment-and-themes.md.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except H.FileInUse as locked:
        print(f"\n{locked}", file=sys.stderr)
        raise SystemExit(4)
