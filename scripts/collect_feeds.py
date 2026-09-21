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
import json
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


X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
X_QUERY_LIMIT = 512          # X Basic tier; Pro allows 1024
X_TOKEN_ENV = "X_BEARER_TOKEN"

# Employment context for the X query. Deliberately a spread across the themes
# rather than the head of the entities.yaml list, which is all pay terms: X is
# where a harassment thread or a layoff claim goes public, and a
# compensation-only filter would never see one.
X_CONTEXT = [
    "salary", "unpaid", "appraisal", "manager", "hr", "interview",
    '"notice period"', "resign", "layoff", "fired", "harassment", "toxic",
    '"work culture"', "employee",
]


def build_x_query(entity: dict, context_terms: list[str] | None = None) -> str:
    """An X recent-search query for one entity.

    Shaped by the 512-character limit on the Basic tier, so spacing and
    punctuation variants are collapsed first - X tokenises them the same way,
    and leaving them in would crowd out a real trading name.
    """
    names, seen = [], set()
    for alias in list(entity.get("aliases") or []) + list(entity.get("needs_confirmation") or []):
        shape = "".join(ch for ch in alias.lower() if ch.isalnum())
        if shape not in seen:
            seen.add(shape)
            names.append(alias)

    context = " OR ".join(context_terms or X_CONTEXT)
    # -is:retweet keeps one row per post; a viral complaint would otherwise
    # arrive hundreds of times and drown the week.
    suffix = f") ({context}) -is:retweet"
    query = "(" + " OR ".join(f'"{n}"' for n in names) + suffix
    while len(query) > X_QUERY_LIMIT and len(names) > 1:
        names.pop()
        query = "(" + " OR ".join(f'"{n}"' for n in names) + suffix
    return query


def parse_x_payload(payload: dict) -> list[dict]:
    """Normalise an X recent-search response to the shared feed item shape."""
    usernames = {
        user["id"]: user.get("username", "")
        for user in payload.get("includes", {}).get("users", [])
    }

    items = []
    for tweet in payload.get("data", []):
        metrics = tweet.get("public_metrics", {}) or {}
        handle = usernames.get(tweet.get("author_id", ""), "")
        # Without the author handle X still resolves a post by id alone.
        url = (f"https://x.com/{handle}/status/{tweet['id']}" if handle
               else f"https://x.com/i/web/status/{tweet['id']}")
        items.append({
            "title": " ".join((tweet.get("text") or "").split())[:300],
            "url": url,
            "summary": tweet.get("text", ""),
            "published": (tweet.get("created_at") or "")[:10],
            "author": f"@{handle}" if handle else "",
            "engagement": (metrics.get("like_count", 0) + metrics.get("retweet_count", 0)
                           + metrics.get("reply_count", 0) + metrics.get("quote_count", 0)),
        })
    return items


def fetch_x_search(query: str, token: str, timeout: int, max_results: int = 100) -> list[dict]:
    """Query X's recent-search endpoint.

    Recent search covers the last 7 days, which is exactly the digest's window.
    """
    params = urllib.parse.urlencode({
        "query": query,
        "max_results": max(10, min(int(max_results), 100)),
        "tweet.fields": "created_at,public_metrics,lang",
        "expansions": "author_id",
        "user.fields": "username",
    })
    request = urllib.request.Request(
        f"{X_SEARCH_URL}?{params}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "HR-Intelligence-Digest/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_x_payload(json.loads(response.read().decode("utf-8")))


# Reddit throttles unauthenticated search hard. Firing the four entity queries
# back-to-back got 429 on three of them, so three of the four entities were
# never actually searched and the run still reported "an empty week" - the
# worst kind of wrong, because it looks like a finding.
# 2.0s was not enough: a real run still lost two of four Reddit queries to 429
# after retrying. Reddit throttles unauthenticated search hard, and a CI runner
# shares its IP. This is a weekly job, so patience is nearly free and a skipped
# entity is not.
MIN_SECONDS_BETWEEN_HITS = 5.0
_last_hit: dict[str, float] = {}


def _space_out(host: str) -> None:
    """Keep at least MIN_SECONDS_BETWEEN_HITS between requests to one host."""
    wait = MIN_SECONDS_BETWEEN_HITS - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def fetch(url: str, user_agent: str, timeout: int, attempts: int = 4) -> bytes:
    """Fetch a feed, backing off when the host throttles us.

    A 429 is not an answer, so retrying is the difference between searching an
    entity and silently skipping it. Honours Retry-After when the host sends
    one, otherwise backs off 2s, 4s, 8s.
    """
    host = urllib.parse.urlsplit(url).netloc
    delay = 2
    for attempt in range(1, attempts + 1):
        _space_out(host)
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == attempts:
                raise
            wait = delay
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and str(retry_after).strip().isdigit():
                wait = min(int(str(retry_after).strip()), 30)
            print(f"  {host} returned {exc.code}; waiting {wait}s "
                  f"(attempt {attempt} of {attempts})")
            time.sleep(wait)
            delay *= 2
    raise urllib.error.HTTPError(url, 429, "rate limited after retries", None, None)


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


def feed_title(payload: bytes) -> str:
    """The feed's own title, which for Google Alerts is the alert query.

    Four alert URLs pasted into four config entries is four chances to put one
    in the wrong place, and a misrouted feed files real mentions under the
    wrong entity - a silent, plausible-looking error. Printing the title next
    to the feed id makes a swap obvious the first time it runs.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ""
    for path in ("channel/title", "atom:title", "title"):
        found = root.find(path, NS)
        if found is not None and (found.text or "").strip():
            return " ".join((found.text or "").split())[:110]
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
    skipped = {"no_entity": 0, "no_context": 0, "duplicate": 0,
               "out_of_scope_hint": 0, "personal_profile": 0}
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

        # Never log a link to someone's personal profile, whatever matched.
        if H.personal_profile_reason(item["url"]):
            skipped["personal_profile"] = skipped.get("personal_profile", 0) + 1
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
                "engagement": str(item.get("engagement", "") or ""),
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
    skipped = {"no_entity": 0, "no_context": 0, "duplicate": 0,
               "out_of_scope_hint": 0, "personal_profile": 0}

    x_token = os.environ.get(X_TOKEN_ENV, "").strip()
    x_context = X_CONTEXT

    for index, feed in enumerate(feeds):
        if feed.get("source") == "x_api":
            entity = entities_by_id.get(feed.get("entity"))
            if not entity:
                print(f"  skip {feed['id']}: unknown entity {feed.get('entity')!r}")
                continue
            if not x_token:
                print(f"  skip {feed['id']}: no ${X_TOKEN_ENV} set \u2014 X stays on the "
                      "manual sweep (scripts/alert_queries.py --format manual)")
                continue
            query = build_x_query(entity, x_context)
            try:
                items = fetch_x_search(query, x_token, timeout,
                                       int(collector.get("x_max_results", 100)))
            except urllib.error.HTTPError as exc:
                hint = {401: "token rejected", 403: "plan does not allow recent search",
                        429: "rate limited \u2014 try again later"}.get(exc.code, "")
                print(f"  FAIL {feed['id']}: HTTP {exc.code} {hint}", file=sys.stderr)
                continue
            except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
                print(f"  FAIL {feed['id']}: {exc}", file=sys.stderr)
                continue
        else:
            url = build_feed_url(feed, entities_by_id)
            if H.is_todo(url) or not url:
                print(f"  skip {feed['id']}: URL still a TODO placeholder")
                continue
            try:
                payload = fetch(url, user_agent, timeout)
                items = parse_feed(payload)
                title = feed_title(payload)
                if title:
                    print(f"  {feed['id']}: feed says {title!r}")
            except (urllib.error.URLError, urllib.error.HTTPError,
                    ET.ParseError, OSError) as exc:
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
    if skipped.get("personal_profile"):
        print(f"{skipped['personal_profile']} item(s) dropped for linking to a personal "
              "profile - out of scope.")
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
