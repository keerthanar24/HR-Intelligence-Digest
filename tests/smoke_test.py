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

    Robust Kommerce has neither a Glassdoor nor an AmbitionBox profile, so it
    can never appear in section 2. Simply missing from the table, it reads as a
    quiet week - when the truth is that the two platforms carrying almost all
    the evidence cannot see it at all.
    """
    print("unrated entity is named")
    entities = H.entity_names()
    unrated = build_digest.unrated_entities(entities)
    check("Robust Kommerce is known to have no review-site page",
          "Robust Kommerce" in unrated, f"(got {unrated})")
    check("the other three are not listed",
          all(n not in unrated for n in
              ("RK Group", "RK World Infocom", "Westbury Kommerce")), f"(got {unrated})")

    settings = H.load_yaml("settings")
    _, body_html, body_text, _ = build_digest.build(WEEK, settings)
    for label, body in (("text", body_text), ("html", body_html)):
        check(f"the {label} body names it",
              "Robust Kommerce" in body and "no Glassdoor or AmbitionBox page" in body)
        check(f"the {label} body says absence is not evidence",
              "not evidence of a quiet week" in body)


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
                 test_sheet_covers_schema, test_carry_forward, test_workbook_round_trip, test_rate_limit_backoff, test_red_flag_wording_has_context, test_unrated_entity_is_named, test_coverage_gate, test_red_flag_sla, test_config_consistency, test_sheet_import, test_sheet_import_v2, test_digest,
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
