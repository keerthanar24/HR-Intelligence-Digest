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
import import_sheet  # noqa: E402
import red_flags  # noqa: E402

# The reporting week runs Saturday to Friday and is reported on the Friday it
# ends (config/settings.yaml).
WEEK = dt.date(2026, 9, 12)   # Sat 12 - Fri 18 Sep 2026
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
    # A date cell read out of .xlsx stringifies with a time part. Unparsed, the
    # importer fell back to the date a rating was CHECKED instead of the week it
    # belonged to, silently filing two weeks' snapshots under one week and
    # wiping out the week-on-week movement in section 2.
    check("spreadsheet datetime string parses",
          H.parse_date("2026-08-31 00:00:00") == dt.date(2026, 8, 31))
    check("iso datetime string parses",
          H.parse_date("2026-08-31T00:00:00") == dt.date(2026, 8, 31))
    check("datetime with a real time parses",
          H.parse_date("2026-08-31 14:30:00") == dt.date(2026, 8, 31))
    check("plain date still parses", H.parse_date("2026-08-31") == dt.date(2026, 8, 31))
    check("day-first date still parses", H.parse_date("31/08/2026") == dt.date(2026, 8, 31))
    check("nonsense is still rejected", H.parse_date("not a date") is None)
    check("configured week starts on Saturday", H.week_start_day() == 5,
          f"(got {H.week_start_day()})")
    # The week ends on the send day, so Friday reports the week finishing that
    # same day - not the one that ended a week earlier.
    check("the Friday send reports the week ending that day",
          H.last_complete_week(dt.date(2026, 9, 18)) == WEEK)
    check("mid-week reports the last finished week",
          H.last_complete_week(dt.date(2026, 9, 21)) == WEEK,
          f"(got {H.last_complete_week(dt.date(2026, 9, 21))})")
    check("the day after the send starts a new week",
          H.week_start_of(dt.date(2026, 9, 19)) == dt.date(2026, 9, 19))
    check("a Monday falls in the week that began Saturday",
          H.week_start_of(dt.date(2026, 9, 14)) == WEEK)
    check("the Friday is the last day of that week",
          H.week_start_of(dt.date(2026, 9, 18)) == WEEK)
    # Every day must land in exactly one week - a gap would silently drop a
    # mention posted on the missing day.
    covered = {H.week_start_of(WEEK + dt.timedelta(days=i)) for i in range(7)}
    check("all seven days belong to one week", covered == {WEEK}, f"({covered})")
    check("week label", H.fmt_week(WEEK) == "12–18 Sep 2026", f"(got {H.fmt_week(WEEK)!r})")
    check("cross-month label",
          H.fmt_week(dt.date(2026, 8, 29)) == "29 Aug – 4 Sep 2026",
          f"(got {H.fmt_week(dt.date(2026, 8, 29))!r})")


def test_urls() -> None:
    print("url canonicalisation")
    a = H.canonical_url("https://www.Reddit.com/r/x/comments/abc/?utm_source=share&si=7#row")
    b = H.canonical_url("http://reddit.com/r/x/comments/abc")
    check("tracking params and host variants collapse", a == b, f"({a!r} vs {b!r})")
    check("distinct posts stay distinct",
          H.canonical_url("https://a.test/p/1") != H.canonical_url("https://a.test/p/2"))


def test_x_collection() -> None:
    """X recent-search parsing and filtering, without calling the API."""
    print("x collection")
    import json

    entities = {e["id"]: e for e in H.load_yaml("entities").get("entities", [])}
    query = collect_feeds.build_x_query(entities["rk_world"])
    check("query fits the API tier limit",
          len(query) <= collect_feeds.X_QUERY_LIMIT, f"({len(query)} chars)")
    # ValueCart is a separate company and out of scope, so it must not appear
    # in any entity's query - not RK World Infocom's, and not at all.
    check("out-of-scope company absent from the query", "ValueCart" not in query)
    check("the registered-name variants are in the query",
          '"RK World Infocom"' in query and '"Worldinfocom"' in query)
    check("out-of-scope company is not an entity", "valuecart" not in entities)
    check("retweets excluded so a viral post is one row", "-is:retweet" in query)
    check("context spans more than pay",
          all(term in query for term in ("harassment", "layoff", "interview")))
    # An alias list long enough to blow the limit must be trimmed, not sent.
    huge = {"aliases": [f"Company Name Number {i} Private Limited" for i in range(60)]}
    check("an overlong alias list is trimmed to fit",
          len(collect_feeds.build_x_query(huge)) <= collect_feeds.X_QUERY_LIMIT)

    with open(os.path.join(FIXTURES, "x-search-response.json"), encoding="utf-8") as fh:
        items = collect_feeds.parse_x_payload(json.load(fh))
    check("all posts parsed", len(items) == 4, f"(got {len(items)})")
    check("url built from the author handle",
          items[0]["url"] == "https://x.com/exemployee_blr/status/1800000000000000001",
          f"({items[0]['url']})")
    check("a post with no handle still gets a resolvable url",
          items[2]["url"].startswith("https://x.com/i/web/status/"))
    check("date taken from created_at", items[0]["published"] == "2026-09-16")
    # Engagement is the only red-flag trigger with a numeric threshold, and X is
    # the one source that supplies it.
    check("engagement sums all four metrics",
          items[0]["engagement"] == 180 + 64 + 22 + 9, f"(got {items[0]['engagement']})")

    matcher = H.EntityMatcher()
    feed = {"id": "x_search_rk_world", "platform": "x", "entity": "rk_world"}
    rows, skipped = collect_feeds.collect_from_items(
        items, feed, matcher, H.platform_names(), WEEK, set(), {"x"})
    # Dropped: the "RK World Tours" post (different company) and the ValueCart
    # post (separate company, deliberately out of scope).
    check("out-of-scope and wrong-company posts dropped", len(rows) == 2, f"(got {len(rows)})")
    check("both exclusions counted", skipped["no_entity"] == 2, f"(got {skipped['no_entity']})")
    check("no ValueCart post reaches the sheet",
          not any("ValueCart" in r["title_or_snippet"] for r in rows))

    by_url = {r["url"]: r for r in rows}
    hot = by_url["https://x.com/exemployee_blr/status/1800000000000000001"]
    check("engagement reaches the mention row", hot["engagement"] == "275",
          f"(got {hot['engagement']!r})")

    threshold = int(H.load_yaml("settings")["red_flags"]["virality_engagement_threshold"])
    check("a viral complaint trips the virality scan",
          "public_escalation_risk" in red_flags.matches_pattern(red_flags.mention_text(hot))
          or H.to_int(hot["engagement"]) >= threshold)
    check("an ordinary post does not",
          H.to_int(by_url["https://x.com/devjobs_in/status/1800000000000000002"]["engagement"])
          < threshold)
    check("rows still land untagged for a human",
          all(r["sentiment"] == "" and r["status"] == "needs_review" for r in rows))


def test_config_consistency() -> None:
    """The sheet's vocabulary and the importer's map must not drift apart.

    Renaming an entity in entities.yaml without adding the new display name to
    column_map.yaml leaves a dropdown value the importer cannot resolve - the
    row imports with a bogus entity and the digest silently loses it.
    """
    print("config consistency")
    cfg = H.load_yaml("column_map")
    entity_map = {k.strip().lower(): v for k, v in cfg["values"]["entity"].items()}
    for entity_id, name in H.entity_names().items():
        check(f"display name {name!r} maps back to {entity_id}",
              entity_map.get(name.strip().lower()) == entity_id,
              f"(got {entity_map.get(name.strip().lower())!r})")

    platform_map = {k.strip().lower(): v for k, v in cfg["values"]["platform"].items()}
    for platform_id, name in H.platform_names().items():
        if platform_id in ("news",):   # feed-only, never typed into the sheet
            continue
        check(f"platform {name!r} maps back to {platform_id}",
              platform_map.get(name.strip().lower()) == platform_id,
              f"(got {platform_map.get(name.strip().lower())!r})")


def test_sheet_import() -> None:
    """The workbook's own headers and dropdown vocabulary map onto the schema."""
    print("sheet import")
    cfg = H.load_yaml("column_map")
    notes = import_sheet.Notes()

    rows = import_sheet.read_csv_file(os.path.join(FIXTURES, "sheet-raw-data-log.csv"))
    mentions = import_sheet.import_mentions(rows, cfg, notes)
    check("all data rows imported", len(mentions) == 6, f"(got {len(mentions)})")

    # Headers in the workbook carry trailing spaces ('Entity       ').
    check("trailing whitespace in headers tolerated",
          all(m["entity"] for m in mentions))
    check("'RKWorld' maps to the rk_world id",
          any(m["entity"] == "rk_world" for m in mentions))
    check("'X / Twitter' maps to the x platform",
          any(m["platform"] == "x" for m in mentions))
    check("'Salary & Appraisals' maps to a known theme",
          any(m["themes"] == "compensation" for m in mentions))
    check("every entity is a known id",
          all(m["entity"] in H.entity_names() for m in mentions))
    check("every platform is a known id",
          all(m["platform"] in H.platform_names() for m in mentions))

    # 'Red Flag' sits in the Sentiment dropdown but is not a point on the scale.
    flagged = [m for m in mentions if H.is_yes(m["red_flag"])]
    check("'Red Flag' sentiment sets the flag", len(flagged) == 1, f"(got {len(flagged)})")
    check("'Red Flag' sentiment is not invented as a score",
          flagged and flagged[0]["sentiment"] == "")
    check("the substitution is reported, not silent",
          any("Red Flag" in w and "re-tag" in w for w in notes.warnings))
    check("missing red-flag reason is reported",
          any("Red Flag Reason" in w for w in notes.warnings))

    # week_of is derived from Date Posted, since the sheet has no week column.
    dated = [m for m in mentions if m["post_date"] == "2026-09-14"]
    check("week derived from Date Posted",
          dated and dated[0]["week_of"] == WEEK.isoformat(),
          f"(got {dated[0]['week_of'] if dated else None})")
    check("row with no Date Posted is reported",
          any("no Date Posted" in w for w in notes.warnings))
    check("mention ids generated and unique",
          len({m["mention_id"] for m in mentions}) == 6)
    check("untagged rows marked needs_review",
          all(m["status"] in H.STATUSES for m in mentions))

    # Ratings: the wide tab un-pivots to one row per entity x platform.
    rt = import_sheet.read_csv_file(os.path.join(FIXTURES, "sheet-rating-tracker.csv"))
    ratings = import_sheet.import_ratings(rt, cfg, notes)
    check("wide rating rows un-pivot to long form", len(ratings) == 3, f"(got {len(ratings)})")
    check("a blank platform rating produces no row",
          not any(r["entity"] == "robust_kommerce" and r["platform"] == "glassdoor"
                  for r in ratings))
    check("ambiguous Total Reviews Count not attributed",
          all(r["review_count"] == "" for r in ratings))
    check("the ambiguity is reported",
          any("Total Reviews Count" in w for w in notes.warnings))
    check("single-snapshot overwrite risk is reported",
          any("APPEND" in w for w in notes.warnings))

    # The imported rows must survive validation and produce a digest.
    import validate_data
    report = validate_data.Report()
    validate_data.check_mentions(report, mentions, WEEK)
    schema_errors = [e for e in report.errors if "unknown" in e or "duplicate" in e]
    check("imported rows pass schema validation", not schema_errors,
          f"({schema_errors[:1]})")


def test_sheet_import_v2() -> None:
    """The corrected workbook layout maps with no warnings at all."""
    print("sheet import (corrected workbook)")
    cfg = H.load_yaml("column_map")
    notes = import_sheet.Notes()

    rows = import_sheet.import_mentions(
        import_sheet.read_csv_file(os.path.join(FIXTURES, "sheet-v2-raw-data-log.csv")),
        cfg, notes)
    ratings = import_sheet.import_ratings(
        import_sheet.read_csv_file(os.path.join(FIXTURES, "sheet-v2-rating-tracker.csv")),
        cfg, notes)
    escalations = import_sheet.import_escalations(
        import_sheet.read_csv_file(os.path.join(FIXTURES, "sheet-v2-escalations.csv")),
        cfg, notes)

    check("no warnings on the corrected layout", notes.warnings == [],
          f"({notes.warnings[:1]})")
    check("mentions imported", len(rows) == 4, f"(got {len(rows)})")

    by_id = {r["mention_id"]: r for r in rows}
    check("sheet-supplied mention ids are kept, not regenerated",
          "M-20260912-002" in by_id)
    check("'Mixed' sentiment survives the round trip",
          any(r["sentiment"] == "mixed" for r in rows))
    check("'Payroll Delay' maps to its own theme, not compensation",
          by_id["M-20260912-002"]["themes"] == "payroll_delay")
    check("author type vocabulary maps",
          by_id["M-20260912-002"]["author_type"] == "ex_employee")
    check("red flag reason maps to a canonical trigger",
          by_id["M-20260912-002"]["red_flag_reason"] in H.RED_FLAG_REASONS)
    check("status vocabulary maps",
          all(r["status"] in H.STATUSES for r in rows))

    # The split review-count columns are the point of the Rating_Tracker fix.
    check("two weeks x two platforms un-pivot", len(ratings) == 4, f"(got {len(ratings)})")
    ab = [r for r in ratings if r["platform"] == "ambitionbox"]
    check("review counts now attributed per platform",
          sorted(r["review_count"] for r in ab) == ["118", "121"],
          f"(got {[r['review_count'] for r in ab]})")
    check("in-sheet delta columns are ignored, not imported",
          all("delta" not in k for r in ratings for k in r))

    check("escalation severity maps", escalations[0]["severity"] == "high")
    check("escalation reason maps", escalations[0]["reason"] == "non_payment")
    check("escalation status maps", escalations[0]["status"] == "acknowledged")

    import validate_data
    report = validate_data.Report()
    validate_data.check_mentions(report, rows, WEEK)
    validate_data.check_escalations(report, rows, escalations)
    check("corrected layout passes validation clean", not report.errors,
          f"({report.errors[:1]})")


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

    # A week that has already ended is never labelled partial; one still
    # running must be, or a three-day count reads as a full week.
    check("a finished week is not marked partial", not stats["partial"],
          f"(days_elapsed {stats['days_elapsed']})")
    check("no partial notice on a finished week",
          "PARTIAL WEEK" not in body_text and "Partial week" not in body_html)
    running = H.week_start_of(dt.date.today())
    _, part_html, part_text, part_stats = build_digest.build(running, settings)
    if part_stats["days_elapsed"] < 7:
        check("a running week is marked partial", part_stats["partial"])
        check("the notice names how many days", "of 7 days" in part_text)
        check("the subject warns too",
              "PARTIAL" in build_digest.build(running, settings)[0])
        check("the notice is in both bodies",
              "Partial week" in part_html and "PARTIAL WEEK" in part_text)

    # Appraisal appears twice this week and must surface as a recurring theme.
    check("recurring theme surfaced", "Appraisal" in body_html)

    # RK Group is the parent and the other four are its subsidiaries, so the
    # headline carries a group total as well as the per-entity split.
    check("group total row present", "Group total" in body_html and "Group total" in body_text)
    heads = build_digest.headline_rows(
        H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), WEEK),
        H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), WEEK - dt.timedelta(days=7)),
        H.entity_names())
    total_row = heads[-1]
    check("total is the last row and marked as such", total_row["is_total"])
    check("total equals the sum of the entity rows",
          total_row["count"] == sum(r["count"] for r in heads if not r["is_total"]),
          f"({total_row['count']})")
    check("every entity still has its own row",
          len([r for r in heads if not r["is_total"]]) == len(H.entity_names()))
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
          collect_feeds.parse_published(rss[0]["published"]) == dt.date(2026, 9, 16))
    check("iso date parsed",
          collect_feeds.parse_published(atom[0]["published"]) == dt.date(2026, 9, 17))
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
        check("row dated from the feed, not today", row["post_date"] == "2026-09-16")
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
    for test in (test_matching, test_weeks, test_urls, test_collector, test_x_collection,
                 test_config_consistency, test_sheet_import, test_sheet_import_v2, test_digest,
                 test_red_flags):
        test()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
