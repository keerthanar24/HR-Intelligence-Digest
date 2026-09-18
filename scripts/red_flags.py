#!/usr/bin/env python3
"""Find red-flag mentions and draft the same-day escalation alert.

A red flag is not a bad review. It is one of five pre-agreed triggers
(docs/04-red-flag-protocol.md):

    names_individual        a named person is accused of something
    harassment_or_safety    harassment, assault, discrimination, unsafe conditions
    non_payment             unpaid salary, withheld FnF, PF/statutory dues
    legal_or_regulatory     labour complaint, legal notice, regulator involved
    public_escalation_risk  traction, media pickup, or a thread gaining momentum

    python3 scripts/red_flags.py                     # open flags, all weeks
    python3 scripts/red_flags.py --week 2026-09-07
    python3 scripts/red_flags.py --scan              # suggest flags from wording
    python3 scripts/red_flags.py --alert M-20260907-002   # draft the alert email
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

# Wording that suggests a trigger. Used only to prompt a human — never to raise
# an escalation on its own. False positives here are cheap; misses are not.
SCAN_PATTERNS = {
    "harassment_or_safety": [
        "harass", "harassment", "posh", "molest", "abuse", "abusive", "assault",
        "discriminat", "casteist", "racist", "sexist", "unsafe", "injury",
        "accident", "threaten", "intimidat", "retaliat",
    ],
    "non_payment": [
        "unpaid", "not paid", "salary not", "salary delayed", "delayed salary",
        "withheld", "full and final", "fnf", "f&f", "pf not", "provident fund",
        "gratuity", "no salary", "pending salary", "cheque bounce", "esic",
    ],
    "legal_or_regulatory": [
        "labour court", "labor court", "legal notice", "lawsuit", "fir ",
        "police complaint", "labour commissioner", "tribunal", "court case",
        "ministry of labour",
    ],
    "public_escalation_risk": [
        "viral", "trending", "journalist", "reporter", "news channel",
        "exposing", "thread", "boycott",
    ],
}


def matches_pattern(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [reason for reason, words in SCAN_PATTERNS.items()
            if any(word in lowered for word in words)]


def mention_text(row: dict) -> str:
    return " ".join([
        row.get("title_or_snippet", ""),
        row.get("one_line_summary", ""),
        row.get("notes", ""),
    ])


def open_flags(mentions: list[dict], escalations: list[dict]) -> list[tuple[dict, dict]]:
    by_mention = {e.get("mention_id"): e for e in escalations if e.get("mention_id")}
    out = []
    for m in mentions:
        if not H.is_yes(m.get("red_flag")):
            continue
        esc = by_mention.get(m.get("mention_id"), {})
        if (esc.get("status") or "").lower() in {"closed", "resolved"}:
            continue
        out.append((m, esc))
    return out


def draft_alert(row: dict, settings: dict, recipients: dict) -> str:
    entities = H.entity_names()
    platforms = H.platform_names()
    sla = settings.get("red_flags", {}).get("sla_hours", 8)
    to = ", ".join(r.get("name", "") for r in recipients.get("red_flag", []))
    reason = (row.get("red_flag_reason") or "unspecified").replace("_", " ")
    entity = entities.get(row.get("entity"), row.get("entity", ""))
    platform = platforms.get(row.get("platform"), row.get("platform", ""))

    lines = [
        f"To: {to}",
        f"Subject: [RED FLAG] {entity} — {reason} — {row.get('post_date') or row.get('captured_at','')}",
        "",
        "Flagging for awareness under the HR Intelligence trial. This is a same-day",
        f"notification, not an assessment — please acknowledge within {sla} hours.",
        "",
        f"Entity      : {entity}",
        f"Platform    : {platform}",
        f"Posted      : {row.get('post_date') or 'unknown'}",
        f"Trigger     : {reason}",
        f"Author type : {row.get('author_type') or 'unknown'}",
        f"Reference   : {row.get('mention_id','')}",
        f"Source      : {row.get('url','')}",
        "",
        "What was posted",
        f"  {row.get('one_line_summary') or row.get('title_or_snippet','')}",
        "",
    ]

    if H.is_yes(row.get("names_individual")):
        lines += [
            "This post names an individual. The name is recorded in the restricted",
            "escalation log and is deliberately not reproduced here. Please open the",
            "source link directly if you need it.",
            "",
        ]

    lines += [
        "What we are asking for",
        "  Acknowledgement only. The trial does not assign investigation or response",
        "  actions; route anything further through the normal HR/IC channel.",
        "",
        "Boundary reminder: this is public, employment-related commentary. We have not",
        "accessed private accounts and we make no finding about whether the claim is true.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="restrict to one week_of Monday (YYYY-MM-DD)")
    parser.add_argument("--scan", action="store_true",
                        help="suggest rows whose wording looks like a trigger")
    parser.add_argument("--alert", metavar="MENTION_ID", help="draft the alert email for one mention")
    parser.add_argument("--out-dir", default=H.OUT_DIR)
    args = parser.parse_args()

    settings = H.load_yaml("settings")
    recipients = H.load_yaml("recipients")
    mentions = H.read_csv(H.MENTIONS_CSV)
    escalations = H.read_csv(H.ESCALATIONS_CSV)

    if args.week:
        week_of = H.parse_date(args.week)
        if week_of is None:
            print(f"Could not read --week {args.week!r}", file=sys.stderr)
            return 2
        mentions = H.mentions_for_week(mentions, H.monday_of(week_of))

    if args.alert:
        row = next((m for m in mentions if m.get("mention_id") == args.alert), None)
        if row is None:
            print(f"No mention with id {args.alert!r} in data/mentions.csv", file=sys.stderr)
            return 2
        body = draft_alert(row, settings, recipients)
        os.makedirs(args.out_dir, exist_ok=True)
        path = os.path.join(args.out_dir, f"red-flag-{args.alert}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
        print(body)
        print(f"\nSaved to {path}")
        missing = [r["name"] for r in recipients.get("red_flag", []) if H.is_todo(r.get("email", ""))]
        if missing:
            print(f"Warning: no email address set for {', '.join(missing)} in config/recipients.yaml")
        return 0

    if args.scan:
        suggestions = []
        for m in mentions:
            if H.is_yes(m.get("red_flag")):
                continue
            reasons = matches_pattern(mention_text(m))
            threshold = int(settings.get("red_flags", {}).get("virality_engagement_threshold", 100))
            if H.to_int(m.get("engagement"), 0) >= threshold:
                reasons.append("public_escalation_risk")
            if reasons:
                suggestions.append((m, sorted(set(reasons))))
        if not suggestions:
            print("Scan found nothing that looks like a trigger.")
            return 0
        print(f"{len(suggestions)} row(s) worth a second look — a human decides, not the script:\n")
        for m, reasons in suggestions:
            print(f"  {m.get('mention_id','?')} [{m.get('entity')}/{m.get('platform')}] "
                  f"-> {', '.join(reasons)}")
            print(f"      {(m.get('one_line_summary') or m.get('title_or_snippet',''))[:110]}")
            print(f"      {m.get('url','')}")
        print("\nIf a suggestion is right, set red_flag=yes and red_flag_reason, then run:")
        print("  python3 scripts/red_flags.py --alert <MENTION_ID>")
        return 0

    flags = open_flags(mentions, escalations)
    if not flags:
        print("No open red flags.")
        return 0

    sla = int(settings.get("red_flags", {}).get("sla_hours", 8))
    today = dt.date.today()
    print(f"{len(flags)} open red flag(s):\n")
    for m, esc in flags:
        raised = H.parse_date(esc.get("raised_at", "")) or H.parse_date(m.get("captured_at", ""))
        age = f"{(today - raised).days}d old" if raised else "age unknown"
        notified = esc.get("notified") or "NOT YET NOTIFIED"
        print(f"  {m.get('mention_id','?')} [{m.get('entity')}/{m.get('platform')}] "
              f"{(m.get('red_flag_reason') or 'unspecified').replace('_',' ')} · {age}")
        print(f"      status: {esc.get('status') or 'open'} · notified: {notified}")
        print(f"      {m.get('url','')}")
    print(f"\nSLA is same-day ({sla}h) acknowledgement. Draft an alert with --alert <MENTION_ID>.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
