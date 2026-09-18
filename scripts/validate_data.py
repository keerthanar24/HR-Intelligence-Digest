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
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def emit(self) -> int:
        for message in self.errors:
            print(f"ERROR   {message}")
        for message in self.warnings:
            print(f"WARNING {message}")
        if not self.errors and not self.warnings:
            print("All checks passed.")
        else:
            print(f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s).")
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

    for group in ("digest", "red_flag"):
        people = recipients.get(group, [])
        if len(people) != 4 and group == "digest":
            report.warn(f"config/recipients.yaml: {group} has {len(people)} recipients; "
                        "the brief specifies four.")
        for person in people:
            if H.is_todo(person.get("email", "")):
                report.error(f"config/recipients.yaml: no email for {person.get('name','?')} in {group}.")

    entity_ids = {e["id"] for e in entities.get("entities", [])}
    for ent in entities.get("entities", []):
        if ent.get("needs_confirmation"):
            report.warn(f"config/entities.yaml: {ent['name']} has unconfirmed former name(s): "
                        f"{', '.join(ent['needs_confirmation'])} — confirm with HR before relying on them.")

    todo_urls = 0
    for platform in sources.get("platforms", []):
        for entity_id, url in (platform.get("urls") or {}).items():
            if entity_id not in entity_ids:
                report.error(f"config/sources.yaml: {platform['id']} references unknown entity "
                             f"{entity_id!r}.")
            if H.is_todo(url):
                todo_urls += 1
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

        canonical = H.canonical_url(row.get("url", ""))
        if canonical:
            if canonical in seen_urls:
                report.error(f"{where}: same URL already logged as {seen_urls[canonical]}.")
            else:
                seen_urls[canonical] = row.get("mention_id", "?")
        else:
            report.warn(f"{where}: no source URL — the digest cannot link to it.")

        status = (row.get("status") or "").strip()
        if status and status not in H.STATUSES:
            report.error(f"{where}: unknown status {status!r}; expected one of {', '.join(H.STATUSES)}.")

        sentiment = (row.get("sentiment") or "").strip().lower()
        if sentiment and sentiment not in H.SENTIMENT_SCORES:
            report.error(f"{where}: unknown sentiment {sentiment!r}; expected one of "
                         f"{', '.join(H.SENTIMENT_SCORES)}.")
        elif not sentiment and status not in {"needs_review", "out_of_scope", ""}:
            report.warn(f"{where}: status is {status!r} but sentiment is blank.")

        author = (row.get("author_type") or "").strip()
        if author and author not in H.AUTHOR_TYPES:
            report.warn(f"{where}: unusual author_type {author!r}.")

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
        if recorded_week and recorded_week != H.monday_of(recorded_week):
            report.error(f"{where}: week_of {row['week_of']} is not a Monday.")
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


def check_coverage(report: Report, mentions: list[dict], ratings: list[dict],
                   week_of: dt.date | None) -> None:
    if week_of is None:
        return
    entities = H.entity_names()
    week_mentions = H.mentions_for_week(mentions, week_of)
    week_ratings = [r for r in ratings if r.get("week_of") == week_of.isoformat()]

    untagged = [m for m in week_mentions if not (m.get("sentiment") or "").strip()
                and (m.get("status") or "") != "out_of_scope"]
    if untagged:
        report.warn(f"week {week_of}: {len(untagged)} mention(s) still untagged; "
                    "they will be excluded from net sentiment.")

    for platform in ("glassdoor", "ambitionbox"):
        covered = {r.get("entity") for r in week_ratings if r.get("platform") == platform}
        missing = [name for eid, name in entities.items() if eid not in covered]
        if missing:
            report.warn(f"week {week_of}: no {platform} rating snapshot for "
                        f"{', '.join(missing)} — section 2 will be incomplete.")

    if not week_mentions:
        report.warn(f"week {week_of}: no mentions recorded at all. If the sweep ran and found "
                    "nothing, that is a valid empty week — say so in the digest.")


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
    check_config(report)
    check_mentions(report, mentions, week_of)
    check_escalations(report, mentions, escalations)
    check_coverage(report, mentions, ratings, week_of)

    print(f"Checked {len(mentions)} mention(s), {len(ratings)} rating snapshot(s), "
          f"{len(escalations)} escalation(s).\n")
    return report.emit()


if __name__ == "__main__":
    raise SystemExit(main())
