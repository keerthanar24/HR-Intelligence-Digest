#!/usr/bin/env python3
"""Pull new candidate mentions from the publisher-provided feeds in config/sources.yaml.

What this does NOT do, by design: it does not scrape Glassdoor, AmbitionBox or
LinkedIn. Those platforms block automated collection and offer no public API, so
they stay on the manual sweep (docs/03-weekly-sop.md). This script only reads
feeds a publisher offers openly for machine reading — Google Alerts RSS, Reddit
search RSS, news feeds.

Rows land in data/mentions.csv with status=needs_review and no sentiment. A
human tags them during the sweep; nothing reaches the digest untouched.

    python3 scripts/collect_feeds.py                  # fetch enabled feeds
    python3 scripts/collect_feeds.py --dry-run        # show what would be added
    python3 scripts/collect_feeds.py --week 2026-09-07
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import os
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def build_feed_url(feed: dict, entities: dict) -> str:
    """Resolve a feed's URL, generating it from the alias register where asked.

    A feed with `auto_query: reddit` has its search built from the entity's
    current aliases, so adding a trading name to config/entities.yaml updates
    the feed too. Hand-written search URLs silently go stale the moment a new
    name is discovered, which is exactly the failure this programme exists to
    avoid.
    """
    kind = feed.get("auto_query")
    if not kind:
        return feed.get("url", "")

    entity = entities.get(feed.get("entity"))
    if not entity:
        return feed.get("url", "")

    # Reddit's search rejects very long queries, so spend the slots on
    # genuinely different names. Spacing and punctuation variants ("RK World",
    # "R K World", "R.K. World") are one term to a search engine, so collapse
    # them first - otherwise they crowd out a real trading name like ValueCart.
    names = list(entity.get("aliases") or []) + list(entity.get("needs_confirmation") or [])
    distinct, seen = [], set()
    for alias in names:
        shape = "".join(ch for ch in alias.lower() if ch.isalnum())
        if shape not in seen:
            seen.add(shape)
            distinct.append(alias)
    query = " OR ".join(f'"{alias}"' for alias in distinct[:8])

    if kind == "reddit":
        return ("https://www.reddit.com/search.rss?q="
                + urllib.parse.quote(query) + "&sort=new&t=week")
    raise ValueError(f"unknown auto_query kind {kind!r} on feed {feed.get('id')}")


def fetch(url: str, user_agent: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _text(element, *paths) -> str:
    for path in paths:
        found = element.find(path, NS)
        if found is not None:
            if found.text and found.text.strip():
                return found.text.strip()
            href = found.get("href")
            if href:
                return href.strip()
    return ""


def parse_feed(payload: bytes) -> list[dict]:
    """Parse RSS 2.0 or Atom into a flat list of items."""
    root = ET.fromstring(payload)
    items = root.findall(".//item") or root.findall(".//atom:entry", NS)
    parsed = []
    for item in items:
        title = _text(item, "title", "atom:title")
        link = _text(item, "link", "atom:link")
        if not link:
            # Atom puts the URL on the link element's href attribute.
            link_el = item.find("atom:link", NS)
            link = link_el.get("href", "") if link_el is not None else ""
        summary = _text(item, "description", "atom:summary", "atom:content")
        published = _text(
            item, "pubDate", "atom:published", "atom:updated", "dc:date"
        )
        parsed.append(
            {
                "title": title,
                "url": link,
                "summary": summary,
                "published": published,
                "author": _text(item, "author", "dc:creator", "atom:author/atom:name"),
            }
        )
    return parsed


def parse_published(value: str) -> dt.date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return H.parse_date(value[:10])


def strip_html(text: str) -> str:
    """Feed summaries arrive as HTML fragments; we only want the words."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())


def collect_from_items(items, feed, matcher, platforms, week_of, seen,
                       context_required, ignore_context=False):
    """Turn feed items into mention rows, filtering the ones we should not log.

    Returns (rows, skipped) where skipped counts why items were dropped. Split
    out from main() so the smoke test can exercise it without a network call.
    """
    rows: list[dict] = []
    skipped = {"no_entity": 0, "no_context": 0, "duplicate": 0, "out_of_scope_hint": 0}
    platform = feed.get("platform", "news")

    for item in items:
        text = f"{item['title']} {strip_html(item['summary'])}".strip()
        matches = matcher.match(text)
        if not matches:
            skipped["no_entity"] += 1
            continue
        # Prefer the entity the feed was created for; fall back to whatever matched.
        match = next((m for m in matches if m.entity_id == feed.get("entity")), matches[0])

        if platform in context_required and not match.has_context and not ignore_context:
            skipped["no_context"] += 1
            continue

        canonical = H.canonical_url(item["url"])
        if not canonical or canonical in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(canonical)

        posted = parse_published(item["published"])
        row_week = H.monday_of(posted) if posted else week_of
        note = "auto-collected from feed %s" % feed["id"]
        if match.out_of_scope_hint:
            skipped["out_of_scope_hint"] += 1
            note += "; contains customer/product wording \u2014 confirm scope before tagging"

        rows.append(
            {
                "mention_id": "",  # assigned by the caller, which knows the full sheet
                "week_of": row_week.isoformat(),
                "captured_at": dt.date.today().isoformat(),
                "captured_by": "collector",
                "entity": match.entity_id,
                "platform": platform,
                "source_name": platforms.get(platform, platform),
                "url": item["url"],
                "post_date": posted.isoformat() if posted else "",
                "author_type": "unknown",
                "role_or_dept": "",
                "title_or_snippet": item["title"][:300],
                "one_line_summary": "",
                "sentiment": "",
                "themes": "",
                "rating_given": "",
                "engagement": "",
                "names_individual": "",
                "red_flag": "",
                "red_flag_reason": "",
                "status": "needs_review",
                "notes": note,
            }
        )
    return rows, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="week_of Monday (YYYY-MM-DD); default = current week")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    parser.add_argument("--feed", help="run a single feed id only")
    parser.add_argument("--no-context-filter", action="store_true",
                        help="keep hits that lack an employment-context term")
    args = parser.parse_args()

    settings = H.load_yaml("settings")
    sources = H.load_yaml("sources")
    collector = settings.get("collector", {})
    user_agent = collector.get("user_agent", "HR-Intelligence-Digest/1.0")
    timeout = int(collector.get("timeout_seconds", 20))
    delay = float(collector.get("delay_seconds", 2))
    context_required = set(collector.get("context_required_for", []))

    week_of = H.parse_date(args.week) if args.week else H.monday_of(dt.date.today())
    if week_of is None:
        print(f"Could not read --week {args.week!r}; expected YYYY-MM-DD", file=sys.stderr)
        return 2
    week_of = H.monday_of(week_of)

    matcher = H.EntityMatcher()
    existing = H.read_csv(H.MENTIONS_CSV)
    seen = {H.canonical_url(r.get("url", "")) for r in existing if r.get("url")}
    platforms = H.platform_names()

    entities_by_id = {e["id"]: e for e in H.load_yaml("entities").get("entities", [])}
    feeds = [f for f in sources.get("feeds", []) if f.get("enabled")]
    if args.feed:
        feeds = [f for f in sources.get("feeds", []) if f.get("id") == args.feed]
        if not feeds:
            print(f"No feed with id {args.feed!r} in config/sources.yaml", file=sys.stderr)
            return 2

    if not feeds:
        print("No enabled feeds in config/sources.yaml — nothing to do.")
        print("Add Google Alerts RSS URLs and set enabled: true to switch collection on.")
        return 0

    new_rows: list[dict] = []
    skipped = {"no_entity": 0, "no_context": 0, "duplicate": 0, "out_of_scope_hint": 0}

    for index, feed in enumerate(feeds):
        url = build_feed_url(feed, entities_by_id)
        if H.is_todo(url) or not url:
            print(f"  skip {feed['id']}: URL still a TODO placeholder")
            continue
        try:
            payload = fetch(url, user_agent, timeout)
            items = parse_feed(payload)
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, OSError) as exc:
            print(f"  FAIL {feed['id']}: {exc}", file=sys.stderr)
            continue

        rows, counts = collect_from_items(
            items, feed, matcher, platforms, week_of, seen, context_required,
            ignore_context=args.no_context_filter,
        )
        for key, value in counts.items():
            skipped[key] += value
        for row in rows:
            row["mention_id"] = H.next_mention_id(
                existing + new_rows, H.parse_date(row["week_of"])
            )
            new_rows.append(row)
        kept = len(rows)

        print(f"  {feed['id']}: {len(items)} items, {kept} new")
        if index < len(feeds) - 1:
            time.sleep(delay)

    print(
        "\nSkipped — no entity match: {no_entity}, no employment context: {no_context}, "
        "already logged: {duplicate}".format(**skipped)
    )
    if skipped["out_of_scope_hint"]:
        print(f"{skipped['out_of_scope_hint']} row(s) flagged as possibly customer-side; check before tagging.")

    if not new_rows:
        print("No new mentions. An empty week is a valid result — report it as one.")
        return 0

    if args.dry_run:
        print(f"\nDRY RUN — {len(new_rows)} row(s) would be added:")
        for row in new_rows:
            print(f"  [{row['entity']}/{row['platform']}] {row['title_or_snippet'][:80]}")
            print(f"      {row['url']}")
        return 0

    written = H.append_csv(H.MENTIONS_CSV, H.MENTION_FIELDS, new_rows)
    print(f"\nAdded {written} row(s) to data/mentions.csv with status=needs_review.")
    print("Next: tag sentiment, themes and the one-line summary during the sweep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
