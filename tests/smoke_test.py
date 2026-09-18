#!/usr/bin/env python3
"""End-to-end check of the digest kit against the fixtures in tests/fixtures.

Run before relying on a change to the scripts:

    python3 tests/smoke_test.py

It exercises entity matching, the week arithmetic, the six digest sections and
the red-flag draft, and asserts the numbers the digest would actually report.
No network, no writes outside a temporary directory.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import hrintel as H  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
H.MENTIONS_CSV = os.path.join(FIXTURES, "mentions.csv")
H.RATINGS_CSV = os.path.join(FIXTURES, "ratings.csv")
H.ESCALATIONS_CSV = os.path.join(FIXTURES, "escalations.csv")

import build_digest  # noqa: E402
import collect_feeds  # noqa: E402
import red_flags  # noqa: E402

WEEK = dt.date(2026, 9, 7)
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        failures.append(name)


def test_matching() -> None:
    print("entity matching")
    matcher = H.EntityMatcher()
    cases = [
        ("Worked at R.K. Group for 3 years, terrible manager", "rk_group", True),
        ("westburry kommerce interview experience", "westbury_kommerce", True),
        ("Robust Commerce salary not credited", "robust_kommerce", True),
        ("RK World Tours refund not received", None, False),
        ("RK Group of Hotels is hiring", None, False),
    ]
    for text, expected, _ in cases:
        hits = matcher.match(text)
        got = hits[0].entity_id if hits else None
        check(f"{text[:38]!r} -> {expected}", got == expected, f"(got {got})")
    # An entity name with no employment context should still match the entity,
    # but must be reported as lacking context so the collector can filter it.
    hits = matcher.match("RK World opened a new warehouse in Surat")
    check("bare mention carries has_context=False",
          bool(hits) and hits[0].has_context is False)
    # Customer wording is a hint, not an automatic exclusion.
    hits = matcher.match("Robust Kommerce employee refused my refund, terrible manager")
    check("customer wording sets out_of_scope_hint",
          bool(hits) and hits[0].out_of_scope_hint is True)


def test_weeks() -> None:
    print("week arithmetic")
    check("last_complete_week on a Friday", H.last_complete_week(dt.date(2026, 9, 18)) == WEEK)
    check("last_complete_week on a Monday", H.last_complete_week(dt.date(2026, 9, 14)) == WEEK)
    check("monday_of a Sunday", H.monday_of(dt.date(2026, 9, 13)) == WEEK)
    check("week label", H.fmt_week(WEEK) == "7–13 Sep 2026", f"(got {H.fmt_week(WEEK)!r})")
    check("cross-month label",
          H.fmt_week(dt.date(2026, 8, 31)) == "31 Aug – 6 Sep 2026",
          f"(got {H.fmt_week(dt.date(2026, 8, 31))!r})")


def test_urls() -> None:
    print("url canonicalisation")
    a = H.canonical_url("https://www.Reddit.com/r/x/comments/abc/?utm_source=share&si=7#row")
    b = H.canonical_url("http://reddit.com/r/x/comments/abc")
    check("tracking params and host variants collapse", a == b, f"({a!r} vs {b!r})")
    check("distinct posts stay distinct",
          H.canonical_url("https://a.test/p/1") != H.canonical_url("https://a.test/p/2"))


def test_digest() -> None:
    print("digest build")
    settings = H.load_yaml("settings")
    settings.setdefault("digest", {})["data_link"] = "https://sheets.example.invalid/hr-intel"
    subject, body_html, body_text, stats = build_digest.build(WEEK, settings)

    check("six mentions in the week", stats["total"] == 6, f"(got {stats['total']})")
    check("three mentions the week before", stats["total_prev"] == 3, f"(got {stats['total_prev']})")
    check("one untagged row counted", stats["untagged"] == 1, f"(got {stats['untagged']})")
    check("one red flag", stats["red_flags"] == 1, f"(got {stats['red_flags']})")
    check("red flag shows in the subject", "red flag" in subject.lower(), f"({subject!r})")

    for heading in ("1 · Headline", "2 · Rating Movement", "3 · What's New",
                    "4 · Themes", "5 · Red Flags", "6 · Data"):
        check(f"html has section {heading!r}", heading in body_html)
    for heading in ("1. HEADLINE", "2. RATING MOVEMENT", "3. WHAT'S NEW",
                    "4. THEMES", "5. RED FLAGS", "6. DATA"):
        check(f"text has section {heading!r}", heading in body_text)

    # RK World: ambitionbox 3.4 -> 3.3 is the movement the digest must show.
    check("rating drop reported", "3.30" in body_html and "-0.10" in body_html)
    check("platform display names, not config ids",
          "AmbitionBox" in body_html and "ambitionbox" not in body_html)
    check("review count growth reported", "+3" in body_html or "+3" in body_text)
    check("boundary note present in both bodies",
          "Customer and product complaints are out of scope" in body_html
          and "Customer and product complaints are out of scope" in body_text)
    check("trailing-indicator caveat present", "trailing indicator" in body_text)
    check("untagged rows disclosed", "not yet sentiment-tagged" in body_html)
    check("data link rendered", "sheets.example.invalid" in body_html)

    # Appraisal appears twice this week and must surface as a recurring theme.
    check("recurring theme surfaced", "Appraisal" in body_html)
    check("theme cap respected",
          body_html.count("</li>") <= int(settings["digest"].get("max_themes", 4)))

    # Net sentiment: the six rows tag as mixed(0), very_negative(-2),
    # positive(+1), negative(-1), negative(-1) and one untagged -> -3/5 = -0.60.
    week_rows = H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), WEEK)
    net = H.net_sentiment(week_rows)
    check("net sentiment excludes untagged rows", abs(net + 0.6) < 1e-9, f"(got {net})")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "digest.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body_html)
        check("html body is non-trivial", os.path.getsize(path) > 2000)


def test_collector() -> None:
    """The collector's parse + filter path, without touching the network."""
    print("feed collection")
    matcher = H.EntityMatcher()
    platforms = H.platform_names()
    context_required = set(
        H.load_yaml("settings").get("collector", {}).get("context_required_for", [])
    )

    rss = collect_feeds.parse_feed(open(os.path.join(FIXTURES, "feed-rss.xml"), "rb").read())
    check("rss parsed", len(rss) == 4, f"(got {len(rss)})")
    atom = collect_feeds.parse_feed(open(os.path.join(FIXTURES, "feed-atom.xml"), "rb").read())
    check("atom parsed", len(atom) == 2, f"(got {len(atom)})")
    check("atom link read from href",
          atom[0]["url"].startswith("https://reddit.example.invalid/"))
    check("rfc822 date parsed",
          collect_feeds.parse_published(rss[0]["published"]) == dt.date(2026, 9, 11))
    check("iso date parsed",
          collect_feeds.parse_published(atom[0]["published"]) == dt.date(2026, 9, 12))
    check("html stripped from summary",
          "<b>" not in collect_feeds.strip_html(rss[0]["summary"])
          and "RK World" in collect_feeds.strip_html(rss[0]["summary"]))

    feed = {"id": "test_news", "platform": "news", "entity": "rk_world"}
    rows, skipped = collect_feeds.collect_from_items(
        rss, feed, matcher, platforms, WEEK, set(), context_required
    )
    check("only the employment story kept", len(rows) == 1, f"(got {len(rows)})")
    check("similarly-named company excluded", skipped["no_entity"] == 2,
          f"(got {skipped['no_entity']})")
    check("bare corporate news filtered on context", skipped["no_context"] == 1,
          f"(got {skipped['no_context']})")
    if rows:
        row = rows[0]
        check("row lands as needs_review", row["status"] == "needs_review")
        check("row is untagged for a human", row["sentiment"] == "" and row["themes"] == "")
        check("row dated from the feed, not today", row["post_date"] == "2026-09-11")
        check("row filed in the right week", row["week_of"] == WEEK.isoformat())
        check("row records its provenance", "test_news" in row["notes"])

    # Same feed, second run: nothing new.
    seen = {H.canonical_url(r["url"]) for r in rows}
    rows2, skipped2 = collect_feeds.collect_from_items(
        rss, feed, matcher, platforms, WEEK, seen, context_required
    )
    check("re-running a feed adds nothing", rows2 == [], f"(got {len(rows2)})")
    check("repeat counted as duplicate", skipped2["duplicate"] == 1)

    reddit_feed = {"id": "test_reddit", "platform": "reddit", "entity": "westbury_kommerce"}
    rows3, _ = collect_feeds.collect_from_items(
        atom, reddit_feed, matcher, platforms, WEEK, set(), context_required
    )
    check("both reddit threads kept", len(rows3) == 2, f"(got {len(rows3)})")
    check("misspelling attributed correctly", rows3[0]["entity"] == "westbury_kommerce")
    check("falls back to the entity actually mentioned",
          rows3[1]["entity"] == "robust_kommerce", f"(got {rows3[1]['entity']})")

    # Review platforms are exempt from the context filter.
    bare = [{"title": "RK World", "url": "https://x.invalid/1", "summary": "", "published": ""}]
    kept_review, _ = collect_feeds.collect_from_items(
        bare, {"id": "f", "platform": "ambitionbox", "entity": "rk_world"},
        matcher, platforms, WEEK, set(), context_required
    )
    kept_news, _ = collect_feeds.collect_from_items(
        bare, {"id": "f", "platform": "news", "entity": "rk_world"},
        matcher, platforms, WEEK, set(), context_required
    )
    check("review platforms exempt from context filter", len(kept_review) == 1)
    check("news platforms require context", len(kept_news) == 0)


def test_red_flags() -> None:
    print("red flags")
    mentions = H.read_csv(H.MENTIONS_CSV)
    escalations = H.read_csv(H.ESCALATIONS_CSV)
    flags = red_flags.open_flags(mentions, escalations)
    check("one open flag", len(flags) == 1, f"(got {len(flags)})")

    body = red_flags.draft_alert(flags[0][0], H.load_yaml("settings"), H.load_yaml("recipients"))
    check("alert names the entity", "RK World" in body)
    check("alert states the trigger", "non payment" in body)
    check("alert asks only for acknowledgement", "Acknowledgement only" in body)
    check("alert carries the boundary reminder", "public, employment-related" in body)

    suggested = red_flags.matches_pattern("Salary not paid for two months, went to labour court")
    check("scan spots non-payment wording", "non_payment" in suggested)
    check("scan spots legal wording", "legal_or_regulatory" in suggested)
    check("scan stays quiet on an ordinary review",
          red_flags.matches_pattern("Nice canteen, average pay") == [])


def main() -> int:
    for test in (test_matching, test_weeks, test_urls, test_collector,
                 test_digest, test_red_flags):
        test()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
