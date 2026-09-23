#!/usr/bin/env python3
"""Check the tracking data and config before a digest goes out.

Catches the things that would otherwise reach four executives' inboxes: a
placeholder URL, an invalid sentiment tag, a duplicate row, a red flag with no
escalation logged, a week that was never swept.

    python3 scripts/validate_data.py
    python3 scripts/validate_data.py --week 2026-09-07

Exit code 0 = clean or warnings only, 1 = errors found.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402


# Domain a platform's company URL should live on. A URL filed under the wrong
# platform sends the sweeper to the wrong site every week and mislabels every
# row it produces.
PLATFORM_DOMAINS = {
    "ambitionbox": ["ambitionbox.com"],
    "glassdoor": ["glassdoor.com", "glassdoor.co.in", "glassdoor.co.uk", "glassdoor.ca"],
    "linkedin": ["linkedin.com"],
    "indeed": ["indeed.com", "indeed.co.in"],
    "quora": ["quora.com"],
    "reddit": ["reddit.com"],
    "youtube": ["youtube.com"],
    "x": ["x.com", "twitter.com"],
    "google_reviews": ["google.com", "google.co.in", "maps.app.goo.gl"],
}

# Fragments that mean the link shows a filtered subset. A location-scoped
# reviews page hides reviews from every other office, and nothing in the digest
# reveals the gap.
SCOPED_URL_MARKERS = ["/locations/", "-location", "/departments/", "-department"]


class Report:
    """Three levels, because two were not enough.

    A warning nobody can act on is worse than silence: it trains people to
    skim past the list, and the one that mattered goes with it. Notes are for
    things that are working as intended and worth stating once.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def emit(self) -> int:
        for message in self.errors:
            print(f"ERROR   {message}")
        for message in self.warnings:
            print(f"WARNING {message}")
        for message in self.notes:
            print(f"note    {message}")
        if not self.errors and not self.warnings:
            print("All checks passed." if not self.notes
                  else f"All checks passed, with {len(self.notes)} note(s).")
        else:
            print(f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
                  + (f", {len(self.notes)} note(s)." if self.notes else "."))
        return 1 if self.errors else 0


def check_config(report: Report) -> None:
    settings = H.load_yaml("settings")
    recipients = H.load_yaml("recipients")
    sources = H.load_yaml("sources")
    entities = H.load_yaml("entities")

    if H.is_todo(settings.get("digest", {}).get("data_link", "")):
        report.error("config/settings.yaml: digest.data_link is still a TODO — "
                     "section 6 of the digest needs the tracking-sheet URL.")
    if H.is_todo(settings.get("programme", {}).get("trial_start", "")):
        report.warn("config/settings.yaml: programme.trial_start not set — "
                    "the Phase 3 review date cannot be derived.")

    # Missing addresses are a warning, not an error: every part of Phase 1 -
    # the baseline sweep, tagging, and building a digest to review - works
    # without them. Only the send needs them, and build_digest.py says so on
    # every run. Blocking setup on an address nobody has yet would just train
    # people to ignore the validator.
    for group in ("digest", "red_flag"):
        people = recipients.get(group, [])
        if len(people) != 4 and group == "digest":
            report.warn(f"config/recipients.yaml: {group} has {len(people)} recipients; "
                        "the brief specifies four.")
        unset = [p.get("name", "?") for p in people if H.is_todo(p.get("email", ""))
                 or not str(p.get("email", "")).strip()]
        if unset:
            report.warn(f"config/recipients.yaml: no email yet for {', '.join(unset)} in "
                        f"{group} - the digest can be built and reviewed, but not sent.")

    entity_ids = {e["id"] for e in entities.get("entities", [])}
    for ent in entities.get("entities", []):
        if ent.get("needs_confirmation"):
            report.warn(f"config/entities.yaml: {ent['name']} has unconfirmed former name(s): "
                        f"{', '.join(ent['needs_confirmation'])} — confirm with HR before relying on them.")

    todo_urls = 0
    for platform in sources.get("platforms", []):
        expected = PLATFORM_DOMAINS.get(platform["id"], [])
        for entity_id, url in (platform.get("urls") or {}).items():
            if entity_id not in entity_ids:
                report.error(f"config/sources.yaml: {platform['id']} references unknown entity "
                             f"{entity_id!r}.")
            if H.is_todo(url):
                todo_urls += 1
                continue
            if not url or url.strip().lower() == "none":
                continue

            host = H.canonical_url(url).split("/")[0]
            if expected and not any(host == d or host.endswith("." + d) for d in expected):
                report.error(
                    f"config/sources.yaml: the {platform['id']} URL for {entity_id} points at "
                    f"{host!r}, not {' or '.join(expected)}. It is filed under the wrong "
                    "platform."
                )
            if any(marker in url.lower() for marker in SCOPED_URL_MARKERS):
                report.warn(
                    f"config/sources.yaml: the {platform['id']} URL for {entity_id} is scoped to "
                    "a location or department, so the sweep would never see reviews from "
                    "elsewhere. Use the company-level page."
                )
    if todo_urls:
        report.warn(f"config/sources.yaml: {todo_urls} platform URL(s) still TODO — "
                    "the manual sweep cannot be run consistently until these are filled in.")

    for feed in sources.get("feeds", []):
        if feed.get("enabled") and H.is_todo(feed.get("url", "")):
            report.error(f"config/sources.yaml: feed {feed['id']} is enabled but has no URL.")
        if feed.get("entity") and feed["entity"] not in entity_ids:
            report.error(f"config/sources.yaml: feed {feed['id']} references unknown entity "
                         f"{feed['entity']!r}.")


def check_mentions(report: Report, rows: list[dict], week_of: dt.date | None) -> None:
    entity_ids = set(H.entity_names())
    platform_ids = set(H.platform_names())
    seen_ids: set[str] = set()
    seen_urls: dict[str, str] = {}

    for index, row in enumerate(rows, start=2):  # +2: header row, 1-indexed
        where = f"data/mentions.csv line {index} ({row.get('mention_id') or 'no id'})"

        if not row.get("mention_id"):
            report.error(f"{where}: missing mention_id.")
        elif row["mention_id"] in seen_ids:
            report.error(f"{where}: duplicate mention_id.")
        else:
            seen_ids.add(row["mention_id"])

        if row.get("entity") not in entity_ids:
            report.error(f"{where}: unknown entity {row.get('entity')!r}.")
        if row.get("platform") not in platform_ids:
            report.error(f"{where}: unknown platform {row.get('platform')!r}.")

        profile = H.personal_profile_reason(row.get("url", ""))
        if profile:
            report.error(f"{where}: the URL is {profile}. Surveillance of individuals' "
                         "personal social media is out of scope - link to the company page "
                         "or the specific post instead.")
        if (row.get("status") or "") != "out_of_scope":
            customer_words = H.customer_side_terms(
                f"{row.get('one_line_summary','')} {row.get('title_or_snippet','')}")
            if customer_words and "mixed post" not in (row.get("notes") or "").lower():
                report.warn(f"{where}: reads as customer-side ({', '.join(customer_words)}). "
                            "Customer complaints and product reviews are out of scope - mark "
                            "it out_of_scope, or note it as a mixed post.")

        canonical = H.canonical_url(row.get("url", ""))
        if canonical:
            if canonical in seen_urls:
                report.error(f"{where}: same URL already logged as {seen_urls[canonical]}.")
            else:
                seen_urls[canonical] = row.get("mention_id", "?")
        else:
            page = H.profile_url(row.get("entity", ""), row.get("platform", ""))
            if page:
                # Not worth a warning on its own: most AmbitionBox reviews have
                # no permalink, so this would fire on nearly every row forever
                # and train people to ignore the validator.
                report.note(f"{where}: no permalink; the digest will link to the "
                            f"{H.platform_names().get(row.get('platform',''), 'platform')} "
                            "page instead.")
            else:
                report.warn(f"{where}: no source URL and no page for this "
                            "entity/platform — the digest cannot link to it at all.")

        status = (row.get("status") or "").strip()
        if status and status not in H.STATUSES:
            report.error(f"{where}: unknown status {status!r}; expected one of {', '.join(H.STATUSES)}.")

        sentiment = (row.get("sentiment") or "").strip().lower()
        if sentiment and sentiment not in H.SENTIMENT_SCORES:
            report.error(f"{where}: unknown sentiment {sentiment!r}; expected one of "
                         f"{', '.join(H.SENTIMENT_SCORES)}.")
        elif not sentiment and status not in {"needs_review", "out_of_scope", ""} \
                and not H.is_company_voice(row):
            report.warn(f"{where}: status is {status!r} but sentiment is blank.")

        author = (row.get("author_type") or "").strip()
        if author and author not in H.AUTHOR_TYPES:
            report.warn(f"{where}: unusual author_type {author!r}.")
        # A tagged company post is the failure mode this author type exists to
        # prevent: it reads as an ordinary mention everywhere downstream except
        # the net figure, so the row looks scored and quietly is not.
        if H.is_company_voice(row) and sentiment:
            report.error(f"{where}: company page activity carries sentiment {sentiment!r}. "
                         "The employer's own post is not a sentiment signal - clear the "
                         "sentiment cell and leave it as coverage.")

        for theme in H.split_themes(row.get("themes", "")):
            if theme not in H.THEMES:
                report.error(f"{where}: unknown theme {theme!r}; see docs/05-sentiment-and-themes.md.")

        if status == "reviewed" and not (row.get("one_line_summary") or "").strip():
            report.warn(f"{where}: reviewed but has no one-line summary; "
                        "the What's New table will fall back to the raw snippet.")

        if H.is_yes(row.get("red_flag")):
            reason = (row.get("red_flag_reason") or "").strip()
            if not reason:
                report.error(f"{where}: red_flag=yes with no red_flag_reason.")
            elif reason not in H.RED_FLAG_REASONS:
                report.error(f"{where}: unknown red_flag_reason {reason!r}; expected one of "
                             f"{', '.join(H.RED_FLAG_REASONS)}.")

        posted = H.parse_date(row.get("post_date", ""))
        recorded_week = H.parse_date(row.get("week_of", ""))
        if posted and recorded_week and H.monday_of(posted) != recorded_week:
            report.warn(f"{where}: post_date {row['post_date']} falls in week "
                        f"{H.monday_of(posted)}, but week_of says {row['week_of']}.")
        if recorded_week and recorded_week != H.week_start_of(recorded_week):
            start_name = [k for k, v in H.WEEKDAY_INDEX.items()
                          if v == H.week_start_day()][0].title()
            report.error(f"{where}: week_of {row['week_of']} is not a {start_name}; "
                         f"the reporting week starts on {start_name}.")
        if posted and posted > dt.date.today():
            report.error(f"{where}: post_date {row['post_date']} is in the future.")


def check_escalations(report: Report, mentions: list[dict], escalations: list[dict]) -> None:
    by_id = {m.get("mention_id"): m for m in mentions}
    logged = {e.get("mention_id") for e in escalations}

    for row in mentions:
        if H.is_yes(row.get("red_flag")) and row.get("mention_id") not in logged:
            report.error(f"{row.get('mention_id')}: flagged red but has no row in "
                         "data/escalations.csv — the same-day notification is unrecorded.")

    for index, esc in enumerate(escalations, start=2):
        where = f"data/escalations.csv line {index} ({esc.get('escalation_id') or 'no id'})"
        if esc.get("mention_id") and esc["mention_id"] not in by_id:
            report.error(f"{where}: refers to unknown mention {esc['mention_id']!r}.")
        if not (esc.get("notified") or "").strip():
            report.error(f"{where}: no record of who was notified.")
        if (esc.get("status") or "").lower() not in {"open", "acknowledged", "closed", "resolved", ""}:
            report.warn(f"{where}: unusual status {esc.get('status')!r}.")


def check_rating_continuity(report: Report, ratings: list[dict]) -> None:
    """Catch a snapshot read from a different page than last week's.

    A location filter, the Overview tab instead of Reviews, or a wrong employer
    id all produce a perfectly plausible number. The tell is discontinuity: a
    review count that jumps or drops far more than a week of reviews could, or
    a rating that moves further than a real week's reviews would move it. Both
    would otherwise be reported as genuine movement in section 2.
    """
    series = collections.defaultdict(list)
    for row in ratings:
        week = H.parse_date(row.get("week_of", ""))
        if week:
            series[(row.get("entity"), row.get("platform"))].append((week, row))

    entities = H.entity_names()
    for (entity_id, platform), rows in sorted(series.items()):
        rows.sort(key=lambda pair: pair[0])
        label = f"{entities.get(entity_id, entity_id)}/{platform}"
        for (prev_week, prev), (week, now) in zip(rows, rows[1:]):
            gap_weeks = max(1, (week - prev_week).days // 7)

            before = H.to_int(prev.get("review_count"), -1)
            after = H.to_int(now.get("review_count"), -1)
            if before > 0 and after >= 0:
                if after < before:
                    report.warn(
                        f"{label}: review count fell from {before} to {after} in week "
                        f"{week}. Reviews are rarely removed - more likely this snapshot "
                        "came from a filtered or different page than last week's.")
                elif after > before * 1.5 and after - before > 10:
                    report.warn(
                        f"{label}: review count jumped from {before} to {after} in week "
                        f"{week}. Check it is the same page and scope as last week "
                        "before reading the rating change as real.")

            was = H.to_float(prev.get("overall_rating"))
            is_now = H.to_float(now.get("overall_rating"))
            if was is not None and is_now is not None:
                move = abs(is_now - was) / gap_weeks
                if move >= 0.5 and before > 20:
                    report.warn(
                        f"{label}: rating moved {is_now - was:+.2f} in week {week} on a base "
                        f"of {before} reviews. That is a large move for the volume - "
                        "confirm it is the same page before reporting it.")


def check_coverage(report: Report, mentions: list[dict], ratings: list[dict],
                   week_of: dt.date | None) -> None:
    if week_of is None:
        return
    entities = H.entity_names()
    settings = H.load_yaml("settings")
    window = H.baseline_window(week_of, settings)
    if window:
        # Week 1 reports sixty days. Judging its coverage on seven would call
        # the week of the back-read an empty week.
        first, last, days = window
        week_mentions = H.mentions_in(mentions, first, last)
        span = f"the {days}-day baseline to {last}"
    else:
        week_mentions = H.mentions_for_week(mentions, week_of)
        span = f"week {week_of}"
    week_ratings = [r for r in ratings if r.get("week_of") == week_of.isoformat()]

    untagged = [m for m in week_mentions if not (m.get("sentiment") or "").strip()
                and (m.get("status") or "") != "out_of_scope"
                and not H.is_company_voice(m)]
    if untagged:
        report.warn(f"{span}: {len(untagged)} mention(s) still untagged; "
                    "they will be excluded from net sentiment.")

    sources = H.load_yaml("sources")
    urls = {p["id"]: (p.get("urls") or {}) for p in sources.get("platforms", [])}
    for platform in ("glassdoor", "ambitionbox"):
        covered = {r.get("entity") for r in week_ratings if r.get("platform") == platform}
        # An entity with no page on a platform can never have a snapshot there.
        absent = {eid for eid, url in urls.get(platform, {}).items()
                  if str(url).strip().lower() == "none"}
        missing = [name for eid, name in entities.items()
                   if eid not in covered and eid not in absent]
        if missing:
            report.warn(f"week {week_of}: no {platform} rating snapshot for "
                        f"{', '.join(missing)} — section 2 will be incomplete.")

    if not week_mentions:
        report.warn(f"{span}: no mentions recorded at all. If the sweep ran and found "
                    "nothing, that is a valid empty week — say so in the digest.")


CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def check_conflict_markers(report: Report) -> None:
    """A data file that still holds a merge conflict.

    GitHub Desktop stashes local edits to pull, and restoring the stash can
    leave <<<<<<< / ======= / >>>>>>> in the file. Committed as-is, the CSV
    still parses: csv.DictReader reads each marker as a row with a nonsense
    week_of and every other column blank. So the file looks fine, the digest
    builds, and the rows either side of the markers may or may not be the ones
    anybody intended. Loud is the only safe setting.
    """
    for path in (H.MENTIONS_CSV, H.RATINGS_CSV, H.ESCALATIONS_CSV,
                 H.SWEEPS_CSV, H.WEEKLY_LOG_CSV):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            hits = [n for n, line in enumerate(handle, start=1)
                    if line.startswith(CONFLICT_MARKERS)]
        if hits:
            report.error(
                f"{os.path.relpath(path, H.ROOT)}: unresolved merge conflict on "
                f"line(s) {', '.join(map(str, hits))}. The file still parses, so "
                "nothing else will tell you. Open it in Notepad, delete the "
                "<<<<<<< / ======= / >>>>>>> lines, and keep the rows you meant.")


def check_row_shape(report: Report) -> None:
    """Lines whose field count does not match the header.

    read_csv() normalises them so nothing crashes, but a short line means
    columns silently became blank and a long one means a value was dropped -
    both from hand-editing, which these files get. Quiet repair is the wrong
    default for a data file somebody will make a decision from.
    """
    for path, fields in ((H.MENTIONS_CSV, H.MENTION_FIELDS),
                         (H.RATINGS_CSV, H.RATING_FIELDS),
                         (H.ESCALATIONS_CSV, H.ESCALATION_FIELDS),
                         (H.SWEEPS_CSV, H.SWEEP_FIELDS),
                         (H.MARKET_CSV, H.MARKET_FIELDS),
                         (H.WEEKLY_LOG_CSV, H.WEEKLY_LOG_FIELDS)):
        bad = H.malformed_rows(path, fields)
        if bad:
            report.warn(
                f"{os.path.relpath(path, H.ROOT)}: line(s) {', '.join(map(str, bad))} have "
                f"the wrong number of columns ({len(fields)} expected). They still load - "
                "short lines read as blanks, long ones lose a value - so check them in "
                "Notepad rather than trusting what the digest shows.")


def check_verbatim(report: Report, mentions: list[dict]) -> None:
    """Review rows holding only somebody's paraphrase.

    title_or_snippet is the one field in a mention that is not an
    interpretation. It was optional, so none of the back-read rows carry one,
    and a summary written in August has nothing behind it when somebody asks in
    November what the review actually said. New rows are refused without it;
    the ones already logged can only be fixed from the page.
    """
    missing = [m for m in mentions
               if m.get("platform") in H.VERBATIM_REQUIRED
               and not str(m.get("title_or_snippet") or "").strip()
               and (m.get("status") or "") != "out_of_scope"]
    if missing:
        report.note(f"{len(missing)} review row(s) hold no verbatim text "
                    f"({', '.join(m['mention_id'] for m in missing[:5])}"
                    f"{', ...' if len(missing) > 5 else ''}). They were logged before it was "
                    "required. Re-open the page and add the review's own title or first line "
                    "if you want the summary to be checkable at the month-2 review.")


def check_effort_log(report: Report, ratings: list[dict], week_of: dt.date | None) -> None:
    """Earlier weeks that were swept but never recorded.

    Hours-per-week and how much was genuinely new are the two Phase 3 questions
    (docs/07-phase3-review.md) that cannot be counted from the data afterwards.
    A week that goes unlogged is not recoverable - by week 8 it is whatever the
    person answering already believes - so say so while the week is still
    recent enough to reconstruct.
    """
    if week_of is None:
        return
    swept = {r.get("week_of") for r in ratings if r.get("week_of")}
    logged = {r.get("week_of") for r in H.read_csv(H.WEEKLY_LOG_CSV)}
    missing = sorted(w for w in swept - logged if w and w < week_of.isoformat())
    if missing:
        report.note(f"{len(missing)} earlier week(s) swept but never recorded in the effort "
                    f"log ({', '.join(missing)}). Catch up with "
                    f"`python3 scripts/log_week.py --week {missing[0]}` - the hours and what "
                    "was new to the four cannot be counted from the data later.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="also run week-coverage checks for this week_of Monday")
    parser.add_argument("--mentions", default=H.MENTIONS_CSV)
    args = parser.parse_args()

    week_of = None
    if args.week:
        parsed = H.parse_date(args.week)
        if parsed is None:
            print(f"Could not read --week {args.week!r}", file=sys.stderr)
            return 2
        week_of = H.monday_of(parsed)

    mentions = H.read_csv(args.mentions)
    ratings = H.read_csv(H.RATINGS_CSV)
    escalations = H.read_csv(H.ESCALATIONS_CSV)

    report = Report()
    check_conflict_markers(report)
    check_row_shape(report)
    check_config(report)
    check_mentions(report, mentions, week_of)
    check_escalations(report, mentions, escalations)
    check_rating_continuity(report, ratings)
    check_coverage(report, mentions, ratings, week_of)
    check_verbatim(report, mentions)
    check_effort_log(report, ratings, week_of)

    print(f"Checked {len(mentions)} mention(s), {len(ratings)} rating snapshot(s), "
          f"{len(escalations)} escalation(s).\n")
    return report.emit()


if __name__ == "__main__":
    raise SystemExit(main())
