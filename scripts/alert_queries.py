#!/usr/bin/env python3
"""Print ready-to-paste search strings for alerts and manual sweeps.

Generated from config/entities.yaml so the alerts and the collector's filter
can never drift apart. Nothing here touches the network — it prints text you
paste into Google Alerts, X, LinkedIn and the review sites.

    python3 scripts/alert_queries.py                 # everything
    python3 scripts/alert_queries.py --entity rk_group
    python3 scripts/alert_queries.py --format google # just the alert queries
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

# A short context bucket for narrowing a noisy brand name. Deliberately not the
# full 60-term list from entities.yaml — Google Alerts handles a long OR chain
# badly, and these six catch most employment chatter.
NARROW_TERMS = ["salary", "employee", "appraisal", "interview", "manager", "resign"]

# Terms worth a standing alert of their own, across all entities at once.
RED_FLAG_TERMS = ["unpaid", "harassment", "labour court", "layoff"]

# Sites worth an X-ray (site:) search by hand. Deliberately review and
# discussion pages only.
#
# NOTE: the classic recruiting "X-ray" targets linkedin.com/in/ to enumerate
# people's profiles. That is the surveillance pattern the brief rules out
# (docs/00-brief.md section 4), so it is not generated here and should not be
# added. We search where the company is discussed, not where individuals live.
XRAY_SITES = [
    "ambitionbox.com",
    "glassdoor.co.in",
    "indeed.co.in",
    "reddit.com",
    "quora.com",
]


def quoted_aliases(entity: dict, include_unconfirmed: bool = True) -> list[str]:
    names = list(entity.get("aliases") or [])
    if include_unconfirmed:
        names += list(entity.get("needs_confirmation") or [])
    # Alias spellings that differ only by punctuation are the same search to
    # Google, so drop the duplicates rather than pad the query.
    seen, out = set(), []
    for name in names:
        key = H.normalise(name)
        if key not in seen:
            seen.add(key)
            out.append(f'"{name}"')
    return out


def broad_query(entity: dict) -> str:
    return " OR ".join(quoted_aliases(entity))


def narrow_query(entity: dict) -> str:
    aliases = " OR ".join(quoted_aliases(entity))
    context = " OR ".join(NARROW_TERMS)
    excludes = " ".join(f'-"{x}"' for x in (entity.get("exclude_terms") or []))
    query = f"({aliases}) ({context})"
    return f"{query} {excludes}".strip()


def xray_query(entity: dict) -> str:
    aliases = " OR ".join(quoted_aliases(entity)[:4])
    sites = " OR ".join(f"site:{site}" for site in XRAY_SITES)
    return f"({sites}) ({aliases})"


def boolean_query(entity: dict) -> str:
    aliases = " OR ".join(quoted_aliases(entity))
    context = " OR ".join(NARROW_TERMS)
    return f"({aliases}) AND ({context})"


# One short line per hand-searched platform. The LIST of platforms is derived
# from config/sources.yaml - only the wording lives here, so a platform added
# to the source map cannot go missing from the worksheet for want of a hint.
SWEEP_HINTS = {
    "x": "if no API plan; logged-out search",
    "quora": "answers naming the group",
    "youtube": "comments on videos about the group; employment only",
    "google_reviews": "employment only - skip customer and product reviews",
    "indeed": "reviews and interview experiences",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", help="limit to one entity id")
    parser.add_argument("--format",
                        choices=["all", "google", "manual", "matrix", "sweep"],
                        default="all")
    parser.add_argument("--week", help="week_of for the sweep worksheet; "
                                       "decides which fortnightly channels are due")
    args = parser.parse_args()

    cfg = H.load_yaml("entities")
    entities = cfg.get("entities", [])
    if args.entity:
        entities = [e for e in entities if e["id"] == args.entity]
        if not entities:
            print(f"No entity with id {args.entity!r}", file=sys.stderr)
            return 2

    if args.format == "sweep":
        sources = H.load_yaml("sources")
        settings = H.load_yaml("settings")
        platforms = sources.get("platforms", [])
        names = {e["id"]: e["name"] for e in cfg.get("entities", [])}

        week = H.parse_date(args.week) if args.week else H.last_complete_week()
        if week is None:
            print(f"Could not read --week {args.week!r}", file=sys.stderr)
            return 2
        week = H.week_start_of(week)
        week_no = H.weeks_into_trial(week, settings)

        # Which platforms carry a working feed, so the collector covers them.
        fed = {f.get("platform") for f in sources.get("feeds", [])
               if f.get("enabled") and f.get("platform")}

        def due(platform):
            return H.cadence_due(platform.get("cadence", "weekly"), week, settings)

        pages = sorted((p for p in platforms if p.get("urls")),
                       key=lambda p: (p.get("priority", 9), p["id"]))
        feeds = sorted((p for p in platforms if not p.get("urls") and p["id"] in fed),
                       key=lambda p: (p.get("priority", 9), p["id"]))
        # Everything left is a hand search. Derived, never typed: Indeed sat in
        # sources.yaml and in the paper checklist but had been left out of this
        # list, so the worksheet the desk actually works from never named it.
        hand = sorted((p for p in platforms if not p.get("urls") and p["id"] not in fed),
                      key=lambda p: (p.get("priority", 9), p["id"]))

        print("=" * 72)
        print(f"WEEKLY SWEEP WORKSHEET  -  {H.fmt_week(week)}"
              + (f"  (trial week {week_no + 1})" if week_no is not None else ""))
        print("=" * 72)
        print("Work top to bottom. Sort each page by NEWEST, not relevance.")
        print()
        for platform in pages:
            print(f"--- {platform['name']}{'' if due(platform) else '  (fortnightly - NOT due this week)'} ---")
            if not due(platform):
                print()
                continue
            if "ratings" in (platform.get("captures") or []):
                print("    Record the rating AND the review count, even if nothing is new:")
                print("      python3 scripts/log_rating.py -e <entity> -p %s -r <rating> -c <count>"
                      % platform["id"])
            for entity_id, url in (platform.get("urls") or {}).items():
                if entity_id not in names:
                    continue
                text = str(url or "").strip()
                if text.lower() == "none":
                    note = "(no page on this platform - nothing to open)"
                elif H.is_todo(text) or not text:
                    note = "(no page - write none in config if there is none)"
                else:
                    note = text
                print(f"  [ ] {names[entity_id]}")
                print(f"      {note}")
            print()

        if feeds:
            print("--- Feed-collected, no page to open ---")
            print("  [ ] python3 scripts/collect_feeds.py"
                  f"      ({', '.join(p['name'] for p in feeds)})")
            print("  [ ] Reddit comments - the feed only sees posts")
            print()

        print("--- Search by hand, no fixed page ---")
        for platform in hand:
            cadence = str(platform.get("cadence", "weekly")).lower()
            hint = SWEEP_HINTS.get(platform["id"], "")
            if not due(platform):
                print(f"  [ ] {platform['name']}  -  fortnightly, NOT due this week (skip)")
                continue
            label = platform["name"] + (f" - {hint}" if hint else "")
            if cadence == "fortnightly":
                label += "   [fortnightly, DUE this week]"
            print(f"  [ ] {label}")
        print()
        print("Search strings: python3 scripts/alert_queries.py --format manual")
        print("Progress:       python3 scripts/log_rating.py --status")
        return 0

    if args.format == "matrix":
        # Paste-ready rows for the workbook's Keyword_Matrix tab.
        print("Entity Name\tName Variations & Aliases\t"
              "Google X-Ray Search String\tLinkedIn / Social Boolean String")
        for entity in entities:
            aliases = ", ".join(a.strip('"') for a in quoted_aliases(entity))
            print("\t".join([entity["name"], aliases,
                             xray_query(entity), boolean_query(entity)]))
        print()
        print("Paste into Keyword_Matrix!A1. The X-ray strings target review and")
        print("discussion sites only — profile X-ray (site:linkedin.com/in/) is")
        print("excluded on purpose; see docs/00-brief.md section 4.")
        return 0

    if args.format in ("all", "google"):
        print("=" * 72)
        print("GOOGLE ALERTS  —  one alert per entity, Deliver to: RSS feed")
        print("=" * 72)
        print("Create at https://www.google.com/alerts")
        print("Sources: Automatic  ·  Language: English  ·  Region: Any")
        print("How often: At most once a day  ·  Deliver to: RSS feed")
        print()
        for entity in entities:
            noisy = bool(entity.get("exclude_terms"))
            print(f"--- {entity['name']} ({entity['id']}) ---")
            print()
            print("  Start with the broad query:")
            print(f"    {broad_query(entity)}")
            print()
            print("  If it returns unrelated companies, replace it with the narrow one:")
            print(f"    {narrow_query(entity)}")
            if noisy:
                print()
                print(f"    (Expect noise — {entity['name']} collides with: "
                      f"{', '.join(entity['exclude_terms'])})")
            print()
            print(f"  Paste the RSS URL into config/sources.yaml as feed "
                  f"'google_alerts_{entity['id']}' and set enabled: true")
            print()

        print("--- Cross-entity red-flag alert (one extra alert, all entities) ---")
        print()
        all_aliases = []
        for entity in cfg.get("entities", []):
            all_aliases += quoted_aliases(entity, include_unconfirmed=False)[:2]
        print(f"    ({' OR '.join(all_aliases)}) ({' OR '.join(RED_FLAG_TERMS)})")
        print()
        print("  This one is worth checking daily rather than weekly — it is the")
        print("  closest thing to same-day cover between sweeps.")
        print()

    if args.format in ("all", "manual"):
        print("=" * 72)
        print("MANUAL SWEEP  —  paste into each platform's own search box")
        print("=" * 72)
        print()
        for entity in entities:
            print(f"--- {entity['name']} ---")
            print("  X / LinkedIn / Reddit / Quora:")
            print(f"    {narrow_query(entity)}")
            print("  Review sites (no context terms needed — every review is employment):")
            print(f"    {broad_query(entity)}")
            print()
        print("Sort by newest, not relevance, or you will re-read the same reviews")
        print("every week. Restrict to the past week where the platform allows it.")
        print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Someone piped us into `head` or `less` and closed the pipe early.
        # Exit quietly rather than dumping a traceback over their output.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)
