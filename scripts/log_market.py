#!/usr/bin/env python3
"""Record the two scope figures that are neither a review nor a rating.

The project scope asks for two things the digest never carried:

  "job-market trends" - named in the scope's opening line, and in none of the
  six deliverables. For a programme about the group AS AN EMPLOYER, the trend
  that matters is the group's own hiring: how many roles each entity is
  advertising, week on week. A spike in openings beside a run of exit reviews
  is the correlation this digest exists to surface, and neither half shows it
  alone.

  "salary insights" - listed as in-scope content on Glassdoor and AmbitionBox,
  with nowhere to put it. What those platforms publish per company is a COUNT
  of salary entries, not a figure. A company-wide median would be an average
  over unrelated roles - a number nobody should act on - so the count is what
  gets recorded: how much salary data employees have volunteered, and whether
  it is moving.

Both are weekly snapshots, like a rating. One row per entity per week, and the
digest reports the change rather than the level.

    python3 scripts/log_market.py -e rk_world --roles 3 --salaries 51
    python3 scripts/log_market.py --status
    python3 scripts/log_market.py --show
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def latest(rows: list[dict], entity: str, before: str) -> dict | None:
    """The most recent snapshot for an entity strictly before a week."""
    earlier = [r for r in rows
               if r.get("entity") == entity and r.get("week_of", "") < before]
    return max(earlier, key=lambda r: r.get("week_of", "")) if earlier else None


def status(week: dt.date) -> int:
    """Which entities still need a snapshot this week."""
    rows = H.read_csv(H.MARKET_CSV)
    names = H.entity_names()
    have = {r.get("entity") for r in rows if r.get("week_of") == week.isoformat()}
    print(f"\nJob market and salary entries for {H.fmt_week(week)}\n")
    for entity_id, name in names.items():
        row = next((r for r in rows
                    if r.get("week_of") == week.isoformat()
                    and r.get("entity") == entity_id), None)
        if row:
            print(f"  ok       {name:<20} {row.get('open_roles') or '-':>4} role(s), "
                  f"{row.get('salary_entries') or '-':>5} salary entries")
        else:
            print(f"  MISSING  {name}")
    print(f"\n  {len(have)}/{len(names)} recorded.")
    if len(have) < len(names):
        print("  python3 scripts/log_market.py -e <entity> --roles <n> --salaries <n>")
    return 0


def show() -> int:
    rows = H.read_csv(H.MARKET_CSV)
    if not rows:
        print("No market snapshots recorded yet.")
        return 0
    names = H.entity_names()
    for week_of in sorted({r.get("week_of", "") for r in rows}):
        print(f"\n{week_of}")
        for row in sorted((r for r in rows if r.get("week_of") == week_of),
                          key=lambda r: r.get("entity", "")):
            before = latest(rows, row.get("entity", ""), week_of)
            move = ""
            if before:
                delta = H.to_int(row.get("open_roles"), 0) - H.to_int(before.get("open_roles"), 0)
                move = f"  ({delta:+d} roles)" if delta else "  (no change)"
            print(f"  {names.get(row.get('entity'), row.get('entity')):<20} "
                  f"{row.get('open_roles') or '-':>4} role(s), "
                  f"{row.get('salary_entries') or '-':>5} salary entries{move}")
    return 0


# Glassdoor and AmbitionBox both key every tab for a company off the same
# identifier, so the Salaries and Jobs pages can be derived from the Reviews
# URL already in config rather than being a second thing to keep current.
# DERIVED, not verified - nothing in this project has loaded them. A wrong one
# is a 404 the moment it is opened, which is the cheap kind of wrong.
def tab_urls(entity_id: str) -> list[tuple[str, str]]:
    """(label, url) for every page worth opening to count roles and salaries."""
    sources = H.load_yaml("sources")
    urls = {p["id"]: (p.get("urls") or {}) for p in sources.get("platforms", [])}
    out = []

    glassdoor = str(urls.get("glassdoor", {}).get(entity_id) or "")
    if glassdoor and not H.is_todo(glassdoor) and glassdoor.lower() != "none":
        # Glassdoor's path segment and its slug word differ, and not by a rule:
        # /Salary/<Name>-Salaries-E<id>.htm but /Jobs/<Name>-Jobs-E<id>.htm.
        for label, segment, word in (("Salaries", "Salary", "Salaries"),
                                     ("Jobs", "Jobs", "Jobs")):
            out.append((f"Glassdoor {label}",
                        glassdoor.replace("/Reviews/", f"/{segment}/")
                                 .replace("-Reviews-", f"-{word}-")))

    ambitionbox = str(urls.get("ambitionbox", {}).get(entity_id) or "")
    if ambitionbox and not H.is_todo(ambitionbox) and ambitionbox.lower() != "none":
        for tab in ("salaries", "jobs"):
            out.append((f"AmbitionBox {tab}",
                        ambitionbox.replace("/reviews/", f"/{tab}/")
                                   .replace("-reviews", f"-{tab}")))

    linkedin = str(urls.get("linkedin", {}).get(entity_id) or "")
    if linkedin and not H.is_todo(linkedin) and linkedin.lower() != "none":
        out.append(("LinkedIn Jobs", linkedin.rstrip("/") + "/jobs/"))
    return out


def worksheet(week: dt.date) -> int:
    """Every page to open, and the command to record what it says."""
    names = H.entity_names()
    done = {r.get("entity") for r in H.read_csv(H.MARKET_CSV)
            if r.get("week_of") == week.isoformat()}
    print(f"\nJob market and salary entries — {H.fmt_week(week)}")
    print("\nOPEN ROLES is how many the entity is advertising, across the pages below,")
    print("counted once (the same role listed twice is one role).")
    print("SALARY ENTRIES is the COUNT the platform reports, not a figure — a")
    print("company-wide median averages unrelated roles and nobody should act on it.")
    print("\n0 is a real answer and worth recording. Omitting it is not.\n")

    for entity_id, name in names.items():
        mark = "  (already recorded)" if entity_id in done else ""
        print(f"\n{name}{mark}")
        pages = tab_urls(entity_id)
        if not pages:
            print("    no pages configured — nothing to count")
            continue
        for label, url in pages:
            print(f"    {label:<22} {url}")
        print(f"\n    python3 scripts/log_market.py -e {entity_id} "
              f"--roles <n> --salaries <n> \\\n"
              f"        --source \"where you counted them\"")
    print("\nThe URLs are derived from the Reviews pages in config/sources.yaml and have")
    print("never been loaded. If one 404s, the real one belongs in config.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-e", "--entity")
    parser.add_argument("--roles", type=int,
                        help="open roles advertised across the platforms you checked")
    parser.add_argument("--salaries", type=int,
                        help="salary entries the platform reports for this company")
    parser.add_argument("--source", default="",
                        help="where you counted them, e.g. 'LinkedIn Jobs + AmbitionBox'")
    parser.add_argument("--week", help="week_of start day; default = the current week")
    parser.add_argument("--by", default="desk")
    parser.add_argument("--notes", default="")
    parser.add_argument("--status", action="store_true",
                        help="which entities still need a snapshot this week")
    parser.add_argument("--show", action="store_true", help="every snapshot recorded")
    parser.add_argument("--worksheet", action="store_true",
                        help="every page to open, per entity, and the command to record it")
    args = parser.parse_args()

    week = H.week_start_of(H.parse_date(args.week) if args.week else dt.date.today())
    if args.show:
        return show()
    if args.worksheet:
        return worksheet(week)
    if args.status:
        return status(week)

    names = H.entity_names()
    if not args.entity or args.entity not in names:
        print(f"Need -e with one of: {', '.join(names)}", file=sys.stderr)
        return 2
    if args.roles is None and args.salaries is None:
        print("Nothing to record. Give --roles, --salaries, or both.", file=sys.stderr)
        print("  0 roles is a real answer and worth recording; omitting it is not.",
              file=sys.stderr)
        return 2

    rows = [r for r in H.read_csv(H.MARKET_CSV)
            if not (r.get("entity") == args.entity
                    and r.get("week_of") == week.isoformat())]
    rows.append({
        "week_of": week.isoformat(),
        "captured_at": dt.date.today().isoformat(),
        "captured_by": args.by,
        "entity": args.entity,
        "open_roles": "" if args.roles is None else str(args.roles),
        "salary_entries": "" if args.salaries is None else str(args.salaries),
        "source": args.source,
        "notes": args.notes,
    })
    rows.sort(key=lambda r: (r.get("week_of", ""), r.get("entity", "")))
    H.write_csv(H.MARKET_CSV, H.MARKET_FIELDS, rows)

    print(f"Recorded {names[args.entity]} for {H.fmt_week(week)}: "
          f"{args.roles if args.roles is not None else '-'} role(s), "
          f"{args.salaries if args.salaries is not None else '-'} salary entries.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except H.FileInUse as locked:
        print(f"\n{locked}", file=sys.stderr)
        raise SystemExit(4)
