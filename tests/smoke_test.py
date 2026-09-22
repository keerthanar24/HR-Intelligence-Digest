#!/usr/bin/env python3
"""End-to-end check of the digest kit against the fixtures in tests/fixtures.

Run before relying on a change to the scripts:

    python3 tests/smoke_test.py

It exercises entity matching, the week arithmetic, the six digest sections and
the red-flag draft, and asserts the numbers the digest would actually report.
No network, no writes outside a temporary directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
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
import validate_data  # noqa: E402
import import_sheet  # noqa: E402
import red_flags  # noqa: E402
import alert_queries  # noqa: E402
import log_mention  # noqa: E402

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


def test_scope_guardrail() -> None:
    """The out-of-scope boundary is enforced, not just printed in the footer."""
    print("scope guardrail")
    blocked = {
        "https://www.linkedin.com/in/some-person": "LinkedIn personal profile",
        "https://linkedin.com/pub/some-person": "LinkedIn personal profile",
        "https://instagram.com/someone": "Instagram profile",
        "https://www.facebook.com/someperson": "Facebook profile",
        "https://x.com/someperson": "X profile",
        "https://twitter.com/someperson/": "X profile",
        "https://www.threads.net/@someone": "Threads profile",
    }
    for url in blocked:
        check(f"blocked: {url.split('//')[1][:38]}", H.personal_profile_reason(url) is not None)

    # A company page or one specific post is a different thing entirely.
    allowed = [
        "https://www.linkedin.com/company/robust-kommerce-india/",
        "https://www.linkedin.com/company/rk-groupp/posts/123",
        "https://x.com/someperson/status/1800000000000000001",
        "https://www.ambitionbox.com/reviews/westbury-kommerce-reviews",
        "https://www.glassdoor.co.in/Reviews/RK-Group-Reviews-E653077.htm",
        "https://www.reddit.com/r/developersIndia/comments/abc/",
        "https://www.instagram.com/p/Cxyz123/",
    ]
    for url in allowed:
        check(f"allowed: {url.split('//')[1][:38]}", H.personal_profile_reason(url) is None,
              f"({H.personal_profile_reason(url)})")

    check("customer wording detected",
          set(H.customer_side_terms("refund never came and the delivery was late"))
          >= {"refund", "delivery"})
    check("employment wording is not flagged as customer-side",
          H.customer_side_terms("appraisal delayed, manager unresponsive, FnF pending") == [])

    # A feed item pointing at a personal profile must never reach the sheet.
    matcher = H.EntityMatcher()
    items = [{"title": "RK World Infocom salary complaint", "summary": "unpaid salary",
              "url": "https://www.linkedin.com/in/someone", "published": "2026-09-16"}]
    rows, skipped = collect_feeds.collect_from_items(
        items, {"id": "f", "platform": "linkedin", "entity": "rk_world"},
        matcher, H.platform_names(), WEEK, set(), set())
    check("collector drops a personal-profile link", rows == [], f"(got {len(rows)})")
    check("and counts why", skipped.get("personal_profile") == 1)

    report = validate_data.Report()
    validate_data.check_mentions(report, [{
        "mention_id": "M-1", "week_of": WEEK.isoformat(), "entity": "rk_world",
        "platform": "linkedin", "url": "https://www.linkedin.com/in/someone",
        "sentiment": "negative", "status": "reviewed", "one_line_summary": "x",
    }], None)
    check("validator errors on a personal-profile URL",
          any("personal social media" in e for e in report.errors), f"({report.errors})")


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

    # Mail clients clip horizontal overflow rather than scrolling, so a table
    # wider than the viewport silently loses its rightmost columns.
    import re as _re
    tables = _re.findall(r"<table.*?</table>", body_html, _re.S)
    check("every table uses fixed layout",
          all("table-layout:fixed" in t for t in tables), f"({len(tables)} tables)")
    for i, table in enumerate(tables, 1):
        widths = [int(w.rstrip("%")) for w in _re.findall(r'width="(\d+)%"', table)]
        check(f"table {i} column widths sum to 100%", sum(widths) == 100, f"(got {sum(widths)})")
    check("long cells wrap instead of overflowing",
          "word-break:break-word" in body_html and "overflow-wrap:anywhere" in body_html)

    # A week that has already ended is never labelled partial; one still
    # running must be, or a three-day count reads as a full week.
    check("a finished week is not marked partial", not stats["partial"],
          f"(days_elapsed {stats['days_elapsed']})")
    check("no partial notice on a finished week",
          "PARTIAL WEEK" not in body_text and "Partial week" not in body_html)
    running = H.week_start_of(dt.date.today())
    part_subject, part_html, part_text, part_stats = build_digest.build(running, settings)
    if part_stats["days_elapsed"] < 7:
        check("a running week is marked partial", part_stats["partial"])
        # The baseline week gets its own wording: "4 of 7 days" is the wrong
        # frame for a period that is sixty days long.
        if build_digest.baseline_window(running, settings):
            check("an open baseline says so, not 'partial week'",
                  "BASELINE STILL OPEN" in part_text and "Baseline still open" in part_html)
            check("and names the day it closes",
                  "It closes" in part_text and "It closes" in part_html)
            check("the subject says it is in progress", "IN PROGRESS" in part_subject,
                  f"(got {part_subject})")
            check("the subject does not read 'week of 60-day baseline'",
                  "week of 60-day" not in part_subject, f"(got {part_subject})")
        else:
            check("the notice names how many days", "of 7 days" in part_text)
            check("the subject warns too", "PARTIAL" in part_subject)
            check("the notice is in both bodies",
                  "Partial week" in part_html and "PARTIAL WEEK" in part_text)

    # Appraisal appears twice this week and must surface as a recurring theme.
    check("recurring theme surfaced", "Appraisal" in body_html)

    # RK Group is the parent and the other four are its subsidiaries, so the
    # headline carries a group total as well as the per-entity split.
    # Deliverable 3: "every new review" cannot be guaranteed, so the digest
    # states its coverage and checks the rating count against what was logged.
    check("coverage gap detected from the review count",
          stats["coverage_gaps"] >= 1, f"(got {stats['coverage_gaps']})")
    # The shortfall is a gate, not a caption. Telling four people the table is
    # incomplete does not make it complete; it moves the problem to their inbox.
    check("the shortfall is not announced to recipients",
          "NOT EVERYTHING WAS CAPTURED" not in body_text
          and "Not everything was captured" not in body_html)
    check("but it is carried where the send can refuse on it",
          bool(stats["coverage_detail"]) and
          all("missing" in g and "url" in g for g in stats["coverage_detail"]))
    check("the outstanding count is the arithmetic, not a guess",
          all(g["missing"] == g["new"] - g["logged"] for g in stats["coverage_detail"]))
    check("what was swept is named", "Swept this week" in body_text)

    # Deliverable 4: a theme recurring across weeks is invisible to a 7-day
    # window; the rolling view is what makes "recurring" achievable.
    check("rolling themes surfaced", stats["rolling_themes"] >= 1,
          f"(got {stats['rolling_themes']})")
    check("the rolling window is labelled",
          "Recurring across the last" in body_text and "Recurring across the last" in body_html)
    check("rolling themes span more than one week", "across 2 weeks" in body_text)

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
    # Counting list items across the page no longer works: section 4 carries a
    # second list for the rolling window. Assert the cap where it is applied.
    cap = int(settings["digest"].get("max_themes", 4))
    week_rows = H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), WEEK)
    check("weekly theme cap respected", len(build_digest.theme_rows(week_rows, cap)) <= cap)
    check("rolling theme cap respected", stats["rolling_themes"] <= cap,
          f"(got {stats['rolling_themes']})")

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


def test_send_guards() -> None:
    """The send refuses in every state where an email should not go out."""
    print("send guards")
    import send_digest

    to, missing = send_digest.recipients("digest")
    check("placeholder addresses are not treated as usable", to == [],
          f"(got {to})")
    check("the four are reported as missing", len(missing) == 4, f"(got {missing})")

    message = send_digest.build_message(
        "Subject line", "<p>html body</p>", "text body",
        ["A <a@example.invalid>"], "From <f@example.invalid>", "r@example.invalid")
    check("sent as multipart/alternative", message.is_multipart())
    types = {part.get_content_type() for part in message.walk() if not part.is_multipart()}
    check("carries both a text and an html body",
          {"text/plain", "text/html"} <= types, f"({types})")
    # The brief says body only, no attachments.
    check("no attachments", not any(
        part.get_content_disposition() == "attachment" for part in message.walk()))
    check("reply-to set", message["Reply-To"] == "r@example.invalid")


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

    # Punctuation variants must match: "full-and-final" is written hyphenated
    # as often as not, and it is the commonest non-payment phrasing here.
    for phrasing in ("full-and-final settlement pending",
                     "full and final settlement pending",
                     "F&F not settled yet",
                     "my FnF is stuck"):
        check(f"{phrasing!r} trips non-payment",
              "non_payment" in red_flags.matches_pattern(phrasing))
    check("a labour-court mention trips the legal trigger",
          "legal_or_regulatory" in red_flags.matches_pattern("took it to the labour court"))

    existing = [{"escalation_id": f"E-{dt.date.today().year}-001"},
                {"escalation_id": f"E-{dt.date.today().year}-002"}]
    check("escalation ids continue the sequence",
          red_flags.next_escalation_id(existing).endswith("-003"),
          f"(got {red_flags.next_escalation_id(existing)})")
    check("first escalation of a year starts at 001",
          red_flags.next_escalation_id([]).endswith("-001"))

    suggested = red_flags.matches_pattern("Salary not paid for two months, went to labour court")
    check("scan spots non-payment wording", "non_payment" in suggested)
    check("scan spots legal wording", "legal_or_regulatory" in suggested)
    check("scan stays quiet on an ordinary review",
          red_flags.matches_pattern("Nice canteen, average pay") == [])


def test_sheet_covers_schema() -> None:
    """Every canonical field has a column in the tracker workbook.

    The workbook is the data link the digest hands out, so a field the digest
    holds but the sheet cannot show is a field nobody can audit. It also used
    to be worse than invisible: import_sheet replaces each CSV wholesale, so a
    field with no column came back blank and wiped the baseline figures that
    were read off Glassdoor and AmbitionBox by hand.
    """
    print("sheet covers the schema")
    try:
        import openpyxl
    except ImportError:
        print("  skip  openpyxl not installed")
        return

    cfg = H.load_yaml("column_map")
    wb = openpyxl.load_workbook(
        os.path.join(ROOT, "templates", "HR_Intelligence_Master_Tracker.xlsx"))
    schemas = {"mentions": H.MENTION_FIELDS, "ratings": H.RATING_FIELDS,
               "escalations": H.ESCALATION_FIELDS}
    for tab, fields in schemas.items():
        spec = cfg["tabs"][tab]
        sheet = import_sheet.find_tab({n: None for n in wb.sheetnames},
                                      spec["sheet_names"])
        check(f"{tab}: the workbook has its tab", sheet is not None)
        if not sheet:
            continue
        headers = [c.value for c in wb[sheet][1] if c.value]
        supplied = import_sheet.fields_in_sheet(tab, [headers], cfg)
        # A wide tab carries the platform in the column name, not in a cell.
        expected = set(fields) - ({"platform"} if spec.get("layout") == "wide" else set())
        missing = sorted(expected - supplied)
        check(f"{tab}: every schema field has a column", not missing,
              f"(no column for {', '.join(missing)})")


def test_carry_forward() -> None:
    """An import must not blank a field the sheet has no column for."""
    print("import carry-forward")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ratings.csv")
        import_sheet.write(path, H.RATING_FIELDS, [{
            "week_of": "2026-09-19", "entity": "rk_group", "platform": "glassdoor",
            "overall_rating": "3.60", "review_count": "16", "recommend_pct": "56",
            "culture": "3.5", "url": "https://gd.invalid/rk",
        }])
        # The sheet supplied rating and count, and has no recommend-% column.
        fresh = [{f: "" for f in H.RATING_FIELDS}]
        fresh[0].update({"week_of": "2026-09-19", "entity": "rk_group",
                         "platform": "glassdoor", "overall_rating": "3.70",
                         "review_count": "17"})
        notes = import_sheet.Notes()
        out = import_sheet.carry_forward(
            path, H.RATING_FIELDS, fresh, "ratings",
            {"overall_rating", "review_count"}, notes)[0]
        check("the new rating wins", out["overall_rating"] == "3.70")
        check("recommend % survives the round trip", out["recommend_pct"] == "56",
              f"(got {out['recommend_pct']!r})")
        check("a sub-score survives the round trip", out["culture"] == "3.5")
        check("the profile URL survives the round trip", out["url"].endswith("/rk"))
        check("and it says so rather than doing it quietly", notes.warnings)

        # A field the sheet DOES have must be clearable.
        cleared = [dict(fresh[0], review_count="")]
        out2 = import_sheet.carry_forward(
            path, H.RATING_FIELDS, cleared, "ratings",
            {"overall_rating", "review_count"}, import_sheet.Notes())[0]
        check("clearing a column the sheet has is respected", out2["review_count"] == "")


def test_workbook_round_trip() -> None:
    """CSV -> workbook -> CSV has to come back unchanged.

    The digest calls the workbook "the raw data", so the two directions have to
    agree. Proving it is also how three quiet importer bugs surfaced: escalation
    rows kept the sheet's spelling of entity and platform instead of the ids
    mentions.csv uses, escalation week_of skipped date normalisation and kept
    the cell's time component, and names_individual never went through the
    Yes/No vocabulary.
    """
    print("workbook round trip")
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        print("  skip  openpyxl not installed")
        return
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import export_to_workbook as export

    cfg = H.load_yaml("column_map")
    source = {
        "mentions": H.read_csv(os.path.join(ROOT, "data", "mentions.sample.csv")),
        "ratings": H.read_csv(os.path.join(ROOT, "data", "ratings.csv")),
        "escalations": H.read_csv(os.path.join(FIXTURES, "escalations.csv")),
    }
    fields = {"mentions": H.MENTION_FIELDS, "ratings": H.RATING_FIELDS,
              "escalations": H.ESCALATION_FIELDS}
    for tab, rows in source.items():
        check(f"{tab}: there is something to round-trip", bool(rows))

    with tempfile.TemporaryDirectory() as tmp:
        book = os.path.join(tmp, "tracker.xlsx")
        shutil.copy(os.path.join(ROOT, "templates",
                                 "HR_Intelligence_Master_Tracker.xlsx"), book)
        wb = openpyxl.load_workbook(book)
        font = Font(name="Arial")
        export.write_long(wb, "mentions", source["mentions"], cfg, font)
        export.write_long(wb, "escalations", source["escalations"], cfg, font)
        export.write_ratings(wb, source["ratings"], cfg, font)
        wb.save(book)

        sheets = import_sheet.read_xlsx(book)
        notes = import_sheet.Notes()
        back = {
            "mentions": import_sheet.import_mentions(sheets["Raw_Data_Log"], cfg, notes),
            "ratings": import_sheet.import_ratings(sheets["Rating_Tracker"], cfg, notes),
            "escalations": import_sheet.import_escalations(sheets["Escalations"], cfg, notes),
        }
        # import_sheet.main() runs carry_forward over the imported rows, so a
        # round trip that skips it tests a path nobody runs. It is also the
        # only thing standing between a field the sheet has no column for and
        # silent deletion, which is exactly what this test is for.
        tabs = {"mentions": "Raw_Data_Log", "ratings": "Rating_Tracker",
                "escalations": "Escalations"}
        for tab, sheet_name in tabs.items():
            csv_path = os.path.join(tmp, f"{tab}.csv")
            import_sheet.write(csv_path, fields[tab], source[tab])
            back[tab] = import_sheet.carry_forward(
                csv_path, fields[tab], back[tab], tab,
                import_sheet.fields_in_sheet(tab, sheets[sheet_name], cfg), notes,
                import_sheet.fields_by_platform(tab, sheets[sheet_name], cfg) or None)

        # Glassdoor has a CEO-approval column and AmbitionBox does not, because
        # AmbitionBox does not publish the figure. Merging the two blocks made
        # the field look supplied for both, so an AmbitionBox value was read as
        # a cell somebody had cleared and was wiped on every import.
        blocks = import_sheet.fields_by_platform("ratings", sheets["Rating_Tracker"], cfg)
        check("Glassdoor supplies ceo_approval_pct",
              "ceo_approval_pct" in blocks.get("glassdoor", set()))
        check("AmbitionBox does not, and is not assumed to",
              "ceo_approval_pct" not in blocks.get("ambitionbox", set()))

        # And the old, merged behaviour really did delete it - otherwise this
        # whole distinction is decoration.
        naive = import_sheet.carry_forward(
            os.path.join(tmp, "ratings.csv"), fields["ratings"],
            import_sheet.import_ratings(sheets["Rating_Tracker"], cfg, notes), "ratings",
            import_sheet.fields_in_sheet("ratings", sheets["Rating_Tracker"], cfg), notes)
        lost = [r for r in naive if r.get("platform") == "ambitionbox"
                and not str(r.get("ceo_approval_pct", "")).strip()]
        kept = [r for r in back["ratings"] if r.get("platform") == "ambitionbox"
                and str(r.get("ceo_approval_pct", "")).strip()]
        check("merging the blocks would have wiped it", bool(lost), f"({naive})")
        check("asking per platform keeps it", len(kept) == len(lost), f"({kept})")

    for tab, rows in source.items():
        check(f"{tab}: every row survives the trip", len(back[tab]) == len(rows),
              f"({len(rows)} out, {len(back[tab])} back)")
        drift = []
        for before, after in zip(rows, back[tab]):
            for field in fields[tab]:
                if str(before.get(field, "")).strip() != str(after.get(field, "")).strip():
                    drift.append(f"{field}: {before.get(field)!r} -> {after.get(field)!r}")
        check(f"{tab}: no field changes on the way", not drift,
              f"({'; '.join(drift[:3])})")


def test_rate_limit_backoff() -> None:
    """A 429 must be retried, not counted as 'nothing found'.

    The first real run of the collector got 429 on three of four Reddit
    queries. Three entities were never searched, and the run still printed
    "an empty week" - which reads as a finding rather than a failure.
    """
    print("collector backoff")
    import urllib.error

    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many Requests", {"Retry-After": "1"}, None)

        class Response:
            def read(self):
                return b"<rss></rss>"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return Response()

    real_open, real_sleep = collect_feeds.urllib.request.urlopen, collect_feeds.time.sleep
    collect_feeds.urllib.request.urlopen = flaky
    collect_feeds.time.sleep = lambda s: sleeps.append(s)
    collect_feeds._last_hit.clear()
    try:
        body = collect_feeds.fetch("https://www.reddit.com/search.rss?q=x", "agent", 10)
        check("a throttled feed is retried until it answers", body == b"<rss></rss>")
        check("it took three attempts", calls["n"] == 3, f"(got {calls['n']})")
        check("it honoured Retry-After", 1 in sleeps, f"(slept {sleeps})")

        calls["n"] = 0
        collect_feeds._last_hit.clear()

        def always429(request, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

        collect_feeds.urllib.request.urlopen = always429
        try:
            collect_feeds.fetch("https://www.reddit.com/search.rss?q=y", "agent", 10)
            check("a permanently throttled feed raises rather than returning empty", False)
        except urllib.error.HTTPError:
            check("a permanently throttled feed raises rather than returning empty", True)
        check("and it gave up after the attempt limit", calls["n"] == 4, f"(got {calls['n']})")

        # Retrying is per-request, so without a cap the worst case multiplies
        # across every feed. One run must not spend twenty minutes sleeping.
        collect_feeds.reset_budget()
        sleeps.clear()
        calls["n"] = 0
        rounds = 10          # 10 x 14s of backoff comfortably exceeds the budget
        for _ in range(rounds):
            try:
                collect_feeds.fetch("https://www.reddit.com/search.rss?q=z", "agent", 10)
            except urllib.error.HTTPError:
                pass
        # The budget governs retry waits, not the polite spacing between
        # requests to one host - spacing is normal operation and scales with
        # the number of feeds, not with how badly a host is throttling.
        check("total retry backoff is capped for the run",
              collect_feeds._backoff_spent <= collect_feeds.TOTAL_BACKOFF_BUDGET,
              f"(spent {collect_feeds._backoff_spent}s, "
              f"budget {collect_feeds.TOTAL_BACKOFF_BUDGET}s)")
        check("and once it is spent a feed fails fast rather than retrying",
              calls["n"] < rounds * 4,
              f"(made {calls['n']} of a possible {rounds * 4} attempts)")
        check("a fresh run gets its patience back",
              (collect_feeds.reset_budget() or collect_feeds._backoff_spent) == 0)
    finally:
        collect_feeds.urllib.request.urlopen = real_open
        collect_feeds.time.sleep = real_sleep
        collect_feeds._last_hit.clear()


def test_red_flag_wording_has_context() -> None:
    """Every red-flag trigger must read as employment context.

    The cross-entity Google Alert searches for unpaid, harassment, labour
    court and layoff. Three of those passed the employment-context filter and
    two did not: matching is word-boundary, so 'layoff' never matched
    'layoffs', and 'labour court' was a trigger with no context term at all.
    A news item about either was dropped before anyone saw it.
    """
    print("red-flag wording carries context")
    matcher = H.EntityMatcher()
    for text in (
        "Westbury Kommerce staff say salary not paid",
        "RK World Infocom layoffs reported this week",
        "Ex-employees take RK Group to labour court over unpaid wages",
        "Robust Kommerce faces harassment complaint",
        "RK Group announces retrenchment at its Bengaluru unit",
    ):
        matches = matcher.match(text)
        check(f"{text[:44]!r} matches an entity", bool(matches))
        check(f"{text[:44]!r} reads as employment",
              bool(matches) and matches[0].has_context)

    # And the filter must still reject a customer complaint that names one.
    customer = matcher.match("Ordered from Westbury Kommerce, parcel never arrived")
    check("a delivery complaint is not employment context",
          not customer or not customer[0].has_context,
          f"(got {customer})")


def test_unrated_entity_is_named() -> None:
    """An entity with no review-site page must be named, not just absent.

    Simply missing from section 2, it reads as a quiet week - when the truth
    would be that the two platforms carrying almost all the evidence cannot
    see it. Tested against injected profiles rather than live config, because
    which entities have pages is a fact about the world that changes.
    """
    print("unrated entity is named")
    entities = H.entity_names()
    every = H.rated_profiles()

    check("with the real source map nobody is unrated",
          build_digest.unrated_entities(entities, every) == [],
          f"(got {build_digest.unrated_entities(entities, every)})")

    # Drop one entity's pages and it must be picked up.
    without = [(e, p) for e, p in every if e != "robust_kommerce"]
    named = build_digest.unrated_entities(entities, without)
    check("an entity whose pages all disappear is picked up",
          named == ["Robust Kommerce"], f"(got {named})")

    # And the wording must reach both bodies. Build with the real config, then
    # with robust_kommerce's page removed, and compare.
    real = H.rated_profiles
    try:
        H.rated_profiles = lambda: without
        _, body_html, body_text, _ = build_digest.build(WEEK, H.load_yaml("settings"))
    finally:
        H.rated_profiles = real
    for label, body in (("text", body_text), ("html", body_html)):
        check(f"the {label} body names it",
              "Robust Kommerce" in body and "no Glassdoor or AmbitionBox page" in body)
        check(f"the {label} body says absence is not evidence",
              "not evidence of a quiet week" in body)


def test_no_platform_specific_date_formats() -> None:
    """No glibc-only strftime directives anywhere in the source.

    '%-d' strips the leading zero on Linux and macOS and raises ValueError on
    Windows. It crashed the first real logging session on a Windows machine,
    one line after the row had been written - so the review was saved and the
    confirmation was what blew up, which is a confusing way to meet a bug.
    H.day_month() formats the integer instead and has no platform opinion.
    """
    print("no platform-specific date formats")
    import glob
    import re

    pattern = re.compile(r"""strftime\(\s*["'][^"']*%[-#]""")
    offenders = []
    for path in (glob.glob(os.path.join(ROOT, "scripts", "*.py"))
                 + glob.glob(os.path.join(ROOT, "tools", "*.py"))):
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if pattern.search(line):
                    offenders.append(f"{os.path.basename(path)}:{number}")
    check("no strftime uses %- or %#", not offenders, f"({', '.join(offenders)})")

    check("day_month drops the leading zero",
          H.day_month(dt.date(2026, 8, 2)) == "2 Aug")
    check("day_month can carry the year",
          H.day_month(dt.date(2026, 8, 2), year=True) == "2 Aug 2026")
    check("a week inside one month reads naturally",
          H.fmt_week(dt.date(2026, 9, 19)) == "19\u201325 Sep 2026",
          f"(got {H.fmt_week(dt.date(2026, 9, 19))})")
    check("a week spanning two months names both",
          H.fmt_week(dt.date(2026, 8, 29)) == "29 Aug \u2013 4 Sep 2026",
          f"(got {H.fmt_week(dt.date(2026, 8, 29))})")


def test_interactive_saves_as_it_goes() -> None:
    """Each review must be on disk before the next one is asked for.

    The first version queued them and wrote at the end of the loop, so a
    Ctrl-C - to check the list, or by accident - threw away everything logged
    so far. On a sixty-day back-read that is an hour of reading gone, and the
    person has no way to know which reviews they had already done.
    """
    print("interactive saves as it goes")
    import builtins, log_mention

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mentions.csv")
        import csv as _csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            _csv.DictWriter(fh, fieldnames=H.MENTION_FIELDS).writeheader()

        answers = iter([
            "rk_world", "ambitionbox", "2026-09-10",
            "Good team, poor pay",          # the review's own words - now required
            "A first summary",
            "mixed", "culture", "unknown",
            "Operations",                   # department or role
            "", "", "", "n", "y",
        ])
        real_input, real_path = builtins.input, H.MENTIONS_CSV
        H.MENTIONS_CSV = path
        builtins.input = lambda _p: next(answers)
        try:
            # Runs out of answers partway through the SECOND review, which is
            # exactly the Ctrl-C case.
            try:
                log_mention.interactive(argparse.Namespace(
                    entity=None, platform=None, by="desk"))
            except (StopIteration, RuntimeError):
                pass
            rows = H.read_csv(path)
        finally:
            builtins.input, H.MENTIONS_CSV = real_input, real_path

    check("the finished review survives the interruption", len(rows) == 1,
          f"(got {len(rows)})")
    check("and it is the one that was completed",
          rows and rows[0]["one_line_summary"] == "A first summary",
          f"(got {rows[0]['one_line_summary'] if rows else None!r})")


def test_prompt_accepts_real_typing() -> None:
    """The guided prompt must not bounce an answer that plainly means the value.

    Found while logging the first real review: "Current_employee" was
    rejected because the vocabulary is lowercase. The person had read the
    list and typed the right thing; being fussy about the shift key only
    teaches them the tool is unpleasant.
    """
    print("prompt accepts real typing")
    import builtins, log_mention

    def answer(typed, allowed, multi=False):
        real = builtins.input
        builtins.input = lambda _prompt: typed
        try:
            return log_mention.ask("x", allowed=allowed, multi=multi)
        finally:
            builtins.input = real

    for typed in ("current_employee", "Current_employee", "CURRENT EMPLOYEE",
                  "current employee", "current-employee"):
        check(f"{typed!r} means current_employee",
              answer(typed, H.AUTHOR_TYPES) == "current_employee")

    check("multi-value answers are normalised too",
          answer("Compensation, Growth_Learning", H.THEMES, multi=True)
          == "compensation|growth_learning")
    check("a genuinely wrong value is still refused",
          answer("", H.AUTHOR_TYPES) == "")


def test_week_one_reports_the_baseline() -> None:
    """Week 1 covers sixty days, not seven.

    The brief makes week 1 a sixty-day baseline, but every digest reported a
    strict week. The first real back-read then landed in the weeks the reviews
    were posted - August and early September - and the week 1 digest reported
    zero mentions with the whole baseline sitting in the file, invisible.
    """
    print("week one reports the baseline")
    settings = H.load_yaml("settings")
    start = H.parse_date(settings["programme"]["trial_start"])
    week_one = H.week_start_of(start)

    window = build_digest.baseline_window(week_one, settings)
    check("week 1 is a baseline", window is not None)
    check("it is sixty days long", window and (window[1] - window[0]).days == 59,
          f"(got {window})")
    check("it ends when week 1 ends", window and window[1] == week_one + dt.timedelta(days=6))
    check("week 2 is an ordinary week",
          build_digest.baseline_window(week_one + dt.timedelta(days=7), settings) is None)

    # A mention posted five weeks before the trial belongs to the baseline.
    old = [{f: "" for f in H.MENTION_FIELDS} | {
        "mention_id": "M-1", "entity": "rk_world", "platform": "ambitionbox",
        "post_date": (week_one - dt.timedelta(days=35)).isoformat(),
        "sentiment": "negative", "one_line_summary": "old but inside sixty days"}]
    inside = build_digest.mentions_in(old, window[0], window[1])
    check("a review from five weeks before the trial is in the baseline",
          len(inside) == 1, f"(got {inside})")

    far = [{f: "" for f in H.MENTION_FIELDS} | {
        "mention_id": "M-2", "post_date": (window[0] - dt.timedelta(days=1)).isoformat()}]
    check("a review one day older is not",
          build_digest.mentions_in(far, window[0], window[1]) == [])

    # Nothing precedes a baseline, so every comparison must read n/a rather
    # than "+3", which would claim three reviews arrived in a week.
    rows = build_digest.headline_rows(old, [], H.entity_names(), comparable=False)
    check("baseline deltas read n/a, not +3",
          all(r["count_delta"] == "n/a" for r in rows),
          f"(got {[r['count_delta'] for r in rows]})")
    check("and so does the group total",
          rows[-1]["is_total"] and rows[-1]["net_delta"] == "n/a")


def test_source_link_falls_back_to_the_page() -> None:
    """A row with no permalink must still give the reader somewhere to go.

    Most AmbitionBox reviews have no link of their own, so section 3 was
    handing readers a summary with nothing to check it against. The review
    page is the right place to look; the label has to say "page" so nobody
    expects to land on the review itself.
    """
    print("source link falls back to the page")
    own = build_digest.source_link(
        {"entity": "rk_group", "platform": "ambitionbox", "url": "https://x.invalid/r/1"})
    check("a real permalink is used as-is", own == ("https://x.invalid/r/1", "link"))

    page, label = build_digest.source_link(
        {"entity": "rk_group", "platform": "ambitionbox", "url": ""})
    check("no permalink falls back to the review page", "ambitionbox.com" in page,
          f"(got {page})")
    check("and says it is the page, not the review", label == "page")

    none = build_digest.source_link(
        {"entity": "robust_kommerce", "platform": "ambitionbox", "url": ""})
    check("a platform with no page for that entity offers nothing",
          none == ("", ""), f"(got {none})")


def test_marketplace_complaints_are_out_of_scope() -> None:
    """Seller-conduct wording must be refused, not just customer-service wording.

    The first real back-read turned this up on AmbitionBox: "It's a thief
    company, fraud seller, they had done fraud selling on Amazon". Posted on
    an employer review site, but about how the company sells, not about
    working there - and the out-of-scope list did not catch it, because it
    only covered refunds, couriers and warranties.
    """
    print("marketplace complaints are out of scope")
    out = [
        "It's a theif company, fraud seller, they had done fraud selling on Amazon",
        "Sells fake products on Flipkart, customers cheated",
        "Counterfeit goods in their amazon listing",
    ]
    for text in out:
        check(f"refused: {text[:44]!r}", bool(H.customer_side_terms(text)))

    # And employment commentary must still pass, including where it is angry.
    keep = [
        "Appraisal delayed two quarters and manager unsupportive",
        "Good team but salary below market",
        "Full-and-final settlement pending for two months",
        "Toxic management, people quit within months",
    ]
    for text in keep:
        check(f"kept: {text[:44]!r}", not H.customer_side_terms(text),
              f"(flagged {H.customer_side_terms(text)})")


def test_weekly_effort_log() -> None:
    """The effort log must count the week the digest actually reported.

    docs/07-phase3-review.md decides at week 8 on hours-per-week and on how
    much of the digest was news, and neither is anywhere in the data. The
    first build of this counted a strict seven days, so week 1 - the sixty-day
    baseline - asked how many of nought mentions were new on the very week the
    digest carried the whole back-read. An effort log that disagrees with the
    digest it is logging is worse than no log.
    """
    print("weekly effort log")
    import log_week

    settings = H.load_yaml("settings")
    week_one = H.week_start_of(H.parse_date(settings["programme"]["trial_start"]))
    ordinary = week_one + dt.timedelta(days=7)

    def mention(mid, posted, **extra):
        return {f: "" for f in H.MENTION_FIELDS} | {
            "mention_id": mid, "entity": "rk_world", "platform": "ambitionbox",
            "post_date": posted.isoformat(), "sentiment": "negative",
            "one_line_summary": mid} | extra

    rows = [
        mention("M-old", week_one - dt.timedelta(days=40)),        # baseline only
        mention("M-week1", week_one + dt.timedelta(days=2)),       # baseline + week 1
        mention("M-week2", ordinary + dt.timedelta(days=1)),       # week 2 only
        mention("M-scope", week_one + dt.timedelta(days=3),
                status="out_of_scope", platform="glassdoor"),
        mention("M-ancient", week_one - dt.timedelta(days=400)),   # outside everything
    ]

    with tempfile.TemporaryDirectory() as tmp:
        mentions = os.path.join(tmp, "mentions.csv")
        log = os.path.join(tmp, "weekly_log.csv")
        import_sheet.write(mentions, H.MENTION_FIELDS, rows)
        saved = (H.MENTIONS_CSV, H.WEEKLY_LOG_CSV)
        H.MENTIONS_CSV, H.WEEKLY_LOG_CSV = mentions, log
        try:
            base = log_week.derived(week_one, settings)
            check("week 1 counts the sixty-day baseline, not seven days",
                  base["mentions"] == 2, f"(got {base['mentions']})")
            check("the out-of-scope review is counted apart",
                  base["out_of_scope"] == 1, f"(got {base['out_of_scope']})")
            check("a review older than the baseline is left out",
                  base["mentions"] + base["out_of_scope"] == 3)

            week2 = log_week.derived(ordinary, settings)
            check("an ordinary week counts its own seven days",
                  week2["mentions"] == 1, f"(got {week2['mentions']})")

            # What the log records must survive a read-back.
            H.append_csv(H.WEEKLY_LOG_CSV, H.WEEKLY_LOG_FIELDS, [{
                "week_of": week_one.isoformat(), "logged_at": "2026-09-25",
                "swept_by": "desk", "minutes_spent": "150",
                "new_to_recipients": "2", "acted_on_elsewhere": "",
                "notes": "back-read", **base}])
            back = H.read_csv(H.WEEKLY_LOG_CSV)
            check("the week reads back with every field",
                  len(back) == 1 and set(back[0]) == set(H.WEEKLY_LOG_FIELDS),
                  f"(got {sorted(set(H.WEEKLY_LOG_FIELDS) - set(back[0] if back else []))})")
            check("the minutes survive as a number",
                  H.to_int(back[0]["minutes_spent"]) == 150)
            check("the platforms swept are recorded",
                  "ambitionbox" in back[0]["platforms_swept"])
        finally:
            H.MENTIONS_CSV, H.WEEKLY_LOG_CSV = saved

    # "New to them" cannot exceed the mentions there were - the first run of
    # this recorded "1 of 0 new", which is not a number anyone can use.
    answers = iter(["9", "2"])
    real_input = __builtins__["input"] if isinstance(__builtins__, dict) \
        else __builtins__.input
    try:
        if isinstance(__builtins__, dict):
            __builtins__["input"] = lambda _prompt="": next(answers)
        else:
            __builtins__.input = lambda _prompt="": next(answers)
        got = log_week.ask("how many were new?", numeric=True, most=3)
    finally:
        if isinstance(__builtins__, dict):
            __builtins__["input"] = real_input
        else:
            __builtins__.input = real_input
    check("more new mentions than mentions is refused", got == "2", f"(got {got!r})")

    # The validator judged coverage on a strict week too, so week 1 - the week
    # of the back-read - came back "no mentions recorded at all".
    report = validate_data.Report()
    with tempfile.TemporaryDirectory() as tmp:
        mentions = os.path.join(tmp, "mentions.csv")
        import_sheet.write(mentions, H.MENTION_FIELDS, rows)
        validate_data.check_coverage(report, H.read_csv(mentions),
                                     H.read_csv(H.RATINGS_CSV), week_one)
    empty = [m for m in report.warnings if "no mentions recorded at all" in m]
    check("the validator does not call the baseline week empty", not empty, f"({empty})")

    # A week that was swept but never logged is unrecoverable by week 8.
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "weekly_log.csv")
        saved_log = H.WEEKLY_LOG_CSV
        H.WEEKLY_LOG_CSV = log
        try:
            ratings = [{"week_of": week_one.isoformat()}, {"week_of": ordinary.isoformat()}]
            report = validate_data.Report()
            validate_data.check_effort_log(report, ratings, ordinary)
            check("an earlier unlogged week is flagged",
                  any("effort log" in n for n in report.notes), f"({report.notes})")

            H.append_csv(H.WEEKLY_LOG_CSV, H.WEEKLY_LOG_FIELDS,
                         [{"week_of": week_one.isoformat(), "minutes_spent": "150"}])
            report = validate_data.Report()
            validate_data.check_effort_log(report, ratings, ordinary)
            check("once logged it stays quiet", not report.notes, f"({report.notes})")
        finally:
            H.WEEKLY_LOG_CSV = saved_log



def test_sweep_worksheet_covers_every_platform() -> None:
    """Every platform in the source map must reach the worksheet.

    The hand-search list was typed out rather than derived, and Indeed - named
    in the project scope and present in config/sources.yaml - had been left out
    of it. The paper checklist had it; the sheet the desk actually works from
    did not, so following the worksheet meant never sweeping Indeed at all.
    """
    print("sweep worksheet")
    import contextlib
    import io

    settings = H.load_yaml("settings")
    week_one = H.week_start_of(H.parse_date(settings["programme"]["trial_start"]))
    platforms = H.load_yaml("sources").get("platforms", [])

    def worksheet(week):
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["alert_queries.py", "--format", "sweep", "--week", week.isoformat()]
        try:
            with contextlib.redirect_stdout(out):
                alert_queries.main()
        finally:
            sys.argv = argv
        return out.getvalue()

    week1 = worksheet(week_one)
    missing = [p["name"] for p in platforms if p["name"] not in week1]
    check("every platform in sources.yaml appears in the worksheet",
          not missing, f"(missing {missing})")
    check("Indeed is named", "Indeed" in week1)
    check("the page with no profile says so, rather than going blank",
          "no page on this platform" in week1)

    # Fortnightly used to be "due this week? yes/no" for the desk to guess.
    fortnightly = [p["name"] for p in platforms
                   if str(p.get("cadence", "")).lower() == "fortnightly"]
    check("there are fortnightly channels to schedule", bool(fortnightly))
    week2 = worksheet(week_one + dt.timedelta(days=7))
    check("week 1 calls the rotation due", "DUE this week" in week1)
    check("week 2 calls it not due", "NOT due this week" in week2)
    check("a weekly channel is never skipped",
          "Quora" in week1 and "Quora" in week2)
    for name in fortnightly:
        check(f"{name} is scheduled, not guessed at",
              name in week1 and name in week2)

    check("week 1 of the trial is a due week",
          H.cadence_due("fortnightly", week_one, settings))
    check("week 2 is not",
          not H.cadence_due("fortnightly", week_one + dt.timedelta(days=7), settings))
    check("week 3 is",
          H.cadence_due("fortnightly", week_one + dt.timedelta(days=14), settings))
    check("weekly is always due",
          H.cadence_due("weekly", week_one + dt.timedelta(days=7), settings))


def test_absent_profile_is_disclosed() -> None:
    """Section 2 promises a line per entity per platform.

    Robust Kommerce has no AmbitionBox page, so its row was simply missing -
    and a missing row reads as a week with no movement, not as a platform that
    cannot see the company at all.
    """
    print("absent profile is disclosed")
    entities = {"robust_kommerce": "Robust Kommerce", "rk_group": "RK Group"}
    platforms = {"ambitionbox": "AmbitionBox", "glassdoor": "Glassdoor"}

    said = build_digest.missing_profiles(entities, platforms,
                                         absent=[("robust_kommerce", "ambitionbox")])
    check("the missing page is named with its platform",
          said == ["Robust Kommerce on AmbitionBox"], f"(got {said})")

    # An entity with no page anywhere already gets its own, stronger sentence.
    quiet = build_digest.missing_profiles(
        entities, platforms, absent=[("robust_kommerce", "ambitionbox")],
        unrated=["Robust Kommerce"])
    check("an entity with no page at all is not said twice", quiet == [], f"(got {quiet})")

    check("an entity with a page on both platforms is not named",
          build_digest.missing_profiles(entities, platforms, absent=[]) == [])

    # And it has to reach the reader, in both renderings.
    _subject, html, text, _stats = build_digest.build(WEEK, H.load_yaml("settings"))
    for name, body in (("html", html), ("text", text)):
        check(f"the {name} digest discloses it",
              "Robust Kommerce on AmbitionBox" in body)


def test_fields_reach_the_email() -> None:
    """Fields collected on every sweep that the digest was dropping.

    Star rating, author type and percent-recommend were all in the CSV and in
    the Google Sheet and none of them reached the email. Westbury's Glassdoor
    page reads 0% recommend on two reviews - arguably the sharpest number in
    the set - and it was visible only to somebody who opened the spreadsheet.
    """
    print("collected fields reach the email")

    check("a star rating renders", build_digest.stars_text({"rating_given": "2"}) == "2/5")
    check("a missing one does not invent a number",
          build_digest.stars_text({"rating_given": ""}) == "—")
    check("an out-of-range value is refused",
          build_digest.stars_text({"rating_given": "9"}) == "—")
    check("author type is spelled out",
          build_digest.author_text({"author_type": "ex_employee"}) == "Ex-employee")
    check("an untagged author is Unknown, not blank",
          build_digest.author_text({}) == "Unknown")

    check("percent-recommend shows on its own in week 1",
          build_digest.recommend_text(64, None) == "64%")
    check("and carries its movement once there is a week before it",
          build_digest.recommend_text(64, 61) == "64% (+3pp)")
    check("zero percent is a number, not a blank",
          build_digest.recommend_text(0, None) == "0%")
    check("a platform that does not publish it reads as a dash",
          build_digest.recommend_text(None, None) == "—")

    _subject, html, text, _stats = build_digest.build(WEEK, H.load_yaml("settings"))
    check("the html What's New has a Stars column", "<th" in html and "Stars" in html)
    check("the html What's New says who wrote it", "Who" in html)
    check("section 2 carries percent-recommend in html", "Recommend" in html)
    # The plain-text section 3 is a bullet list, so the values ride inline.
    check("the text digest shows the star rating", "/5" in text, f"({text[:0]})")
    check("the text digest names the author type",
          any(label in text for label in H.AUTHOR_LABELS.values()))
    check("section 2 carries percent-recommend in text", "Recommend" in text)


def test_absent_values_are_named() -> None:
    """A blank cell answered two different questions.

    "The platform does not publish this" and "the sweep did not pick it up"
    looked identical, and only the second is worth chasing. AmbitionBox prints
    neither a would-recommend figure nor CEO approval; a review site has no
    engagement count at all.
    """
    print("absent values are named")
    check("AmbitionBox never publishes CEO approval",
          H.absent_value("ambitionbox", "ceo_approval_pct") == "n/a")
    check("Glassdoor does, so a missing one is 'not shown'",
          H.absent_value("glassdoor", "ceo_approval_pct") == "not shown")
    check("AmbitionBox has no percent-recommend either",
          H.absent_value("ambitionbox", "recommend_pct") == "n/a")

    check("a review site carries no engagement count",
          not H.engagement_applies("ambitionbox") and not H.engagement_applies("glassdoor"))
    check("X, LinkedIn and Reddit do",
          all(H.engagement_applies(p) for p in ("x", "linkedin", "reddit")))

    # The review's own words: the one field in the row that is not an opinion.
    check("review sites must carry the verbatim line",
          {"ambitionbox", "glassdoor"} <= H.VERBATIM_REQUIRED)
    check("a post from a feed is not held to it", "reddit" not in H.VERBATIM_REQUIRED)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mentions.csv")
        import_sheet.write(path, H.MENTION_FIELDS, [])
        saved = H.MENTIONS_CSV
        H.MENTIONS_CSV = path
        try:
            def log(**over):
                args = dict(entity="rk_world", platform="ambitionbox", date="2026-09-10",
                            summary="A summary", sentiment="mixed", themes="culture",
                            author="unknown", url="", title="Good team, poor pay", role="",
                            rating="3", engagement=None, names_individual=False, flag=None,
                            notes="", mixed_post=False, by="desk")
                args.update(over)
                return log_mention.log_one(argparse.Namespace(**args))

            check("a review with no verbatim line is refused", log(title="") == 2)
            check("one that carries it is accepted", log() == 0)
            rows = H.read_csv(path)
            check("engagement reads n/a on a review site",
                  rows and rows[0]["engagement"] == "n/a", f"({rows})")
            check("the department is kept when the page shows one",
                  log(platform="glassdoor", role="Operations", url="") == 0
                  and H.read_csv(path)[-1]["role_or_dept"] == "Operations")
        finally:
            H.MENTIONS_CSV = saved


def test_unverified_channels_are_named() -> None:
    """A channel nobody reached must not read as a channel that was empty.

    The digest said "Swept this week: AmbitionBox, Glassdoor" and stayed silent
    about the rest - an inventory of what produced data, not a checklist of
    what was due. At month 2 the difference between an empty channel and an
    unchecked one is the whole question.

    A configured feed does not excuse a channel either. Three of four Reddit
    queries 403'd on the first real run and the digest still reported an empty
    week, so coverage has to come from a fetch that worked, not from a feed
    that exists in the config.
    """
    print("unverified channels are named")
    import log_sweep

    settings = H.load_yaml("settings")
    week_one = H.week_start_of(H.parse_date(settings["programme"]["trial_start"]))
    week_two = week_one + dt.timedelta(days=7)
    platforms = H.platform_names()

    expected = H.unverified_channels(week_one, settings)
    check("every channel without a review count must prove itself",
          set(expected) == {"linkedin", "x", "indeed", "quora", "youtube",
                            "google_reviews", "reddit", "news"},
          f"(got {expected})")
    check("a review site is exempt - its review count proves it",
          not {"ambitionbox", "glassdoor"} & set(expected))
    check("a feed-collected channel is NOT exempt",
          {"reddit", "news"} <= set(expected))
    check("week 2 drops the fortnightly ones, keeps the weekly ones",
          set(H.unverified_channels(week_two, settings))
          == {"linkedin", "x", "quora", "reddit", "news"},
          f"(got {H.unverified_channels(week_two, settings)})")

    with tempfile.TemporaryDirectory() as tmp:
        saved = H.SWEEPS_CSV
        H.SWEEPS_CSV = os.path.join(tmp, "sweeps.csv")
        try:
            _also, missing = build_digest.channel_coverage(
                week_one, settings, platforms, ["AmbitionBox", "Glassdoor"])
            check("with nothing recorded, every channel is named as not swept",
                  len(missing) == len(expected), f"(got {missing})")

            log_sweep.record(week_one, ["quora", "youtube"], "desk",
                             found={"quora": "0", "youtube": "0"})
            also, missing = build_digest.channel_coverage(
                week_one, settings, platforms, ["AmbitionBox", "Glassdoor"])
            check("a channel checked and empty counts as swept",
                  set(also) == {"Quora", "YouTube"}, f"(got {also})")
            check("and drops out of the not-swept list",
                  "Quora" not in missing and "YouTube" not in missing, f"(got {missing})")

            # What the collector writes when a fetch succeeds.
            log_sweep.record(week_one, ["reddit"], "collector", found={"reddit": "3"})
            _also, missing = build_digest.channel_coverage(
                week_one, settings, platforms, ["AmbitionBox", "Glassdoor"])
            check("a feed that answered covers its channel",
                  "Reddit" not in missing, f"(got {missing})")
            check("a feed that did not answer leaves its channel uncovered",
                  "News / web" in missing, f"(got {missing})")

            # Re-recording a week must not double the rows.
            log_sweep.record(week_one, ["quora"], "desk", found={"quora": "2"})
            rows = [r for r in H.read_csv(H.SWEEPS_CSV) if r["platform"] == "quora"]
            check("re-recording a channel replaces it", len(rows) == 1, f"(got {rows})")
            check("and keeps the new count", rows and rows[0]["found"] == "2")
        finally:
            H.SWEEPS_CSV = saved


def test_remove_mention() -> None:
    """A row logged by mistake must be removable without editing the CSV.

    A back-read is one long sitting and mistakes are noticed a few reviews
    later. Hand-editing the file is how a header gets mangled or a summary
    containing a comma gets split across columns.
    """
    print("removing a mis-logged mention")
    import log_mention

    with tempfile.TemporaryDirectory() as tmp:
        mentions = os.path.join(tmp, "mentions.csv")
        escalations = os.path.join(tmp, "escalations.csv")
        rows = [
            {f: "" for f in H.MENTION_FIELDS} | {
                "mention_id": "M-1", "entity": "rk_world", "platform": "ambitionbox",
                "post_date": "2026-08-14", "one_line_summary": "first"},
            {f: "" for f in H.MENTION_FIELDS} | {
                "mention_id": "M-2", "entity": "rk_group", "platform": "glassdoor",
                "post_date": "2026-08-15", "one_line_summary": "second"},
        ]
        import csv as _csv
        for path, fields, data in ((mentions, H.MENTION_FIELDS, rows),
                                   (escalations, H.ESCALATION_FIELDS, [])):
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = _csv.DictWriter(fh, fieldnames=fields)
                w.writeheader()
                w.writerows(data)

        real_m, real_e = H.MENTIONS_CSV, H.ESCALATIONS_CSV
        H.MENTIONS_CSV, H.ESCALATIONS_CSV = mentions, escalations
        try:
            check("removing an unknown id fails loudly", log_mention.remove("M-NOPE") == 2)
            check("removing a real one succeeds", log_mention.remove("M-1") == 0)
            left = [r["mention_id"] for r in H.read_csv(mentions)]
            check("only that row goes", left == ["M-2"], f"(left {left})")

            # An escalation pointing at a mention must block the delete, or the
            # restricted log ends up referring to a row that no longer exists.
            with open(escalations, "w", newline="", encoding="utf-8") as fh:
                w = _csv.DictWriter(fh, fieldnames=H.ESCALATION_FIELDS)
                w.writeheader()
                w.writerow({f: "" for f in H.ESCALATION_FIELDS} |
                           {"escalation_id": "E-2026-001", "mention_id": "M-2"})
            check("an escalated mention cannot be deleted", log_mention.remove("M-2") == 3)
            check("and it is still there", len(H.read_csv(mentions)) == 1)
        finally:
            H.MENTIONS_CSV, H.ESCALATIONS_CSV = real_m, real_e


def test_coverage_gate() -> None:
    """An incomplete sweep must not be sendable.

    The old behaviour printed "not everything was captured" in the email and
    sent it anyway. That told four people the digest under-reports the week
    without giving anyone a way to fix it. The sweep is finished when the
    logged rows account for every review the counts say arrived, so that is
    the gate - and the worklist says exactly what is left to read.
    """
    print("coverage gate")
    import send_digest

    entities = {"rk_world": "RK World Infocom"}
    platforms = {"ambitionbox": "AmbitionBox"}
    week = dt.date(2026, 9, 12)
    ratings = [
        {"week_of": "2026-09-05", "entity": "rk_world", "platform": "ambitionbox",
         "review_count": "51", "url": "https://ab.invalid/rkw"},
        {"week_of": "2026-09-12", "entity": "rk_world", "platform": "ambitionbox",
         "review_count": "54", "url": "https://ab.invalid/rkw"},
    ]
    logged_one = [{"entity": "rk_world", "platform": "ambitionbox"}]

    expect = [("rk_world", "ambitionbox")]

    def cover(mentions, rows=ratings, expected=expect):
        return build_digest.coverage_rows(
            mentions, rows, week, entities, platforms, expected=expected)[1]

    gaps = cover(logged_one)
    check("three new reviews with one logged is a gap", len(gaps) == 1, f"(got {gaps})")
    check("it is reported as unread, not as unswept", gaps[0]["kind"] == "unread")
    check("the worklist says how many are left", gaps[0]["missing"] == 2,
          f"(got {gaps[0]['missing']})")
    check("and where to read them", gaps[0]["url"] == "https://ab.invalid/rkw")

    check("logging all three closes the gap", cover(logged_one * 3) == [],
          f"(got {cover(logged_one * 3)})")

    # Logging more than the count moved is not a gap either: a LinkedIn post
    # and a review can both be real in a week the count only moved once.
    check("logging more than the count moved is not a gap", cover(logged_one * 5) == [])

    # The hole the first version had: with nothing to subtract, the pair was
    # skipped and the week passed as complete. "Could not check" is not
    # "checked and complete".
    baseline_only = [r for r in ratings if r["week_of"] == "2026-09-12"]
    only = cover(logged_one, rows=baseline_only)
    check("a single snapshot is not silently treated as verified", len(only) == 1,
          f"(got {only})")
    check("it says there is nothing to compare against",
          only and only[0]["kind"] == "no_baseline", f"(got {only})")

    # And a profile nobody swept at all must not read as a quiet week.
    nothing = cover([], rows=[])
    check("a profile nobody swept is reported", len(nothing) == 1, f"(got {nothing})")
    check("it is named as never checked",
          nothing and nothing[0]["kind"] == "not_swept", f"(got {nothing})")
    check("and it names which profile", nothing and nothing[0]["entity"] == "RK World Infocom")

    # A review count that falls is impossible, and is the signature of the page
    # having been read a different way - a location filter applied or cleared.
    # RK Group's baseline is Bengaluru-filtered on both platforms, so this is a
    # live risk from week 2 onward, and it used to pass as a clean week.
    dropped = [
        {"week_of": "2026-09-05", "entity": "rk_world", "platform": "ambitionbox",
         "review_count": "51", "url": "https://ab.invalid/rkw"},
        {"week_of": "2026-09-12", "entity": "rk_world", "platform": "ambitionbox",
         "review_count": "44", "url": "https://ab.invalid/rkw"},
    ]
    fell = cover(logged_one, rows=dropped)
    check("a falling review count is caught", len(fell) == 1, f"(got {fell})")
    check("and named as a reading problem, not unread reviews",
          fell and fell[0]["kind"] == "count_dropped", f"(got {fell})")
    check("the send refuses on it",
          bool(send_digest.coverage_refusal(
              {"coverage_gaps": 1, "coverage_detail": fell})))

    # A profile that does not exist is not a gap: Robust Kommerce has no
    # AmbitionBox page, and config records that as 'none'.
    check("a profile that does not exist is not expected",
          ("robust_kommerce", "ambitionbox") not in H.rated_profiles())

    # Week 1 has no previous snapshot by definition, so blocking on that would
    # mean the very first digest could only go out through the override.
    base = build_digest.coverage_rows(
        logged_one, baseline_only, week, entities, platforms,
        expected=expect, baseline=True)[1]
    check("the baseline week does not block on having no baseline", base == [],
          f"(got {base})")
    check("but an unswept profile still blocks in the baseline week",
          [g["kind"] for g in build_digest.coverage_rows(
              [], [], week, entities, platforms, expected=expect, baseline=True)[1]]
          == ["not_swept"])

    # The send must refuse on it, the way it refuses a missing address.
    refusals = send_digest.coverage_refusal({"coverage_gaps": 1, "coverage_detail": gaps})
    check("the send refuses while reviews are unread", bool(refusals))
    check("and the refusal names the outstanding count", "2 review(s)" in refusals[0],
          f"(got {refusals[0]!r})")
    unswept = send_digest.coverage_refusal(
        {"coverage_gaps": 1, "coverage_detail": nothing})
    check("the send also refuses a profile nobody swept", bool(unswept))
    check("and says so in those words", "not swept" in unswept[0].lower(),
          f"(got {unswept[0]!r})")
    check("no gap, no refusal",
          send_digest.coverage_refusal({"coverage_gaps": 0, "coverage_detail": []}) == [])


def test_red_flag_sla() -> None:
    """Section 5 has to evidence the *same-day* promise, not just the flag.

    Without the two dates a flag alerted three days late renders exactly like
    one alerted within the hour, which is the only thing deliverable 5 claims.
    """
    print("red flag SLA")
    entities = {"rk_world": "RK World Infocom"}
    platforms = {"ambitionbox": "AmbitionBox"}

    def mention(mid):
        return {"mention_id": mid, "entity": "rk_world", "platform": "ambitionbox",
                "post_date": "2026-09-14", "captured_at": "2026-09-16",
                "one_line_summary": "F&F pending two months", "red_flag": "yes",
                "red_flag_reason": "non_payment", "url": "https://example.invalid/1",
                "names_individual": "no", "status": "escalated"}

    same_day = [{"mention_id": "M-1", "raised_at": "2026-09-16",
                 "notified_at": "2026-09-16", "notified": "Mahendra, Sonal",
                 "severity": "high", "status": "acknowledged"}]
    late = [dict(same_day[0], notified_at="2026-09-19")]
    unsent = [dict(same_day[0], notified_at="", notified="")]

    on = build_digest.red_flag_rows([mention("M-1")], same_day, entities, platforms)[0]
    check("same-day escalation is marked on time", on["on_time"] and on["timing"] == "same day",
          f"(got {on['timing']})")
    check("the trigger reads as a label, not a field name", on["reason"] == "Non-payment",
          f"(got {on['reason']})")
    check("the row carries who was told", "Mahendra" in on["notified_to"])

    lt = build_digest.red_flag_rows([mention("M-1")], late, entities, platforms)[0]
    check("a late escalation is not marked on time", not lt["on_time"])
    check("the delay is stated in days", lt["timing"] == "3 day(s) late", f"(got {lt['timing']})")

    ns = build_digest.red_flag_rows([mention("M-1")], unsent, entities, platforms)[0]
    check("an unsent escalation says so loudly",
          ns["timing"] == "NOT YET SENT" and not ns["on_time"])

    # A flagged mention with no escalation row at all must not read as fine.
    none_logged = build_digest.red_flag_rows([mention("M-1")], [], entities, platforms)[0]
    check("a flag with no escalation logged is not silently on time",
          not none_logged["on_time"] and none_logged["raised"] == "2026-09-16",
          f"(got {none_logged['raised']}/{none_logged['on_time']})")

    # And the rendering has to surface it, not just the data.
    for rows, expected in ((same_day, "same day"), (late, "3 day(s) late"), (unsent, "NOT YET SENT")):
        flags = build_digest.red_flag_rows([mention("M-1")], rows, entities, platforms)
        cell = build_digest.alert_cell(flags[0])
        check(f"the alert cell shows {expected!r}", expected in cell, f"(got {cell})")
    check("a missed window is red", "#a12622" in build_digest.alert_cell(
        build_digest.red_flag_rows([mention("M-1")], late, entities, platforms)[0]))
    check("a kept window is green", "#1e7a3c" in build_digest.alert_cell(
        build_digest.red_flag_rows([mention("M-1")], same_day, entities, platforms)[0]))


def main() -> int:
    for test in (test_matching, test_scope_guardrail, test_weeks, test_urls, test_collector, test_x_collection,
                 test_sheet_covers_schema, test_carry_forward, test_workbook_round_trip, test_rate_limit_backoff, test_red_flag_wording_has_context, test_unrated_entity_is_named, test_no_platform_specific_date_formats, test_interactive_saves_as_it_goes, test_prompt_accepts_real_typing, test_week_one_reports_the_baseline, test_weekly_effort_log, test_sweep_worksheet_covers_every_platform, test_absent_profile_is_disclosed, test_fields_reach_the_email, test_absent_values_are_named, test_unverified_channels_are_named, test_source_link_falls_back_to_the_page, test_marketplace_complaints_are_out_of_scope, test_remove_mention, test_coverage_gate, test_red_flag_sla, test_config_consistency, test_sheet_import, test_sheet_import_v2, test_digest,
                 test_send_guards, test_red_flags):
        test()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
