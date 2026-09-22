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
import csv
import datetime as dt
import os
import smtplib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402
import mailer  # noqa: E402

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
    """Which triggers the wording suggests.

    Matching is done on normalised text: punctuation becomes spaces, so
    "full-and-final", "full and final" and "full & final" all match the same
    pattern. Without this the commonest Indian non-payment phrasing - written
    hyphenated as often as not - slipped straight past the scan.
    """
    normalised = H.normalise(text)
    return [reason for reason, words in SCAN_PATTERNS.items()
            if any(H.normalise(word) in normalised for word in words)]


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


def suggestions(mentions: list[dict], settings: dict) -> list[tuple[dict, list[str]]]:
    """Rows that look like a trigger. A person decides; this only points.

    Two kinds: wording that matches a trigger pattern, and reach. Reach is the
    only one the text cannot show - settings.yaml treats engagement at or above
    virality_engagement_threshold as public_escalation_risk, which is how a
    complaint that is spreading gets caught before the words themselves look
    alarming.
    """
    threshold = int(settings.get("red_flags", {}).get("virality_engagement_threshold", 100))
    found = []
    for mention in mentions:
        if H.is_yes(mention.get("red_flag")):
            continue
        reasons = matches_pattern(mention_text(mention))
        if H.to_int(mention.get("engagement"), 0) >= threshold:
            reasons.append("public_escalation_risk")
        if reasons:
            found.append((mention, sorted(set(reasons))))
    return found


def next_escalation_id(existing: list[dict]) -> str:
    year = dt.date.today().year
    prefix = f"E-{year}-"
    used = [H.to_int(r["escalation_id"][len(prefix):], 0) for r in existing
            if (r.get("escalation_id") or "").startswith(prefix)]
    return f"{prefix}{(max(used) + 1) if used else 1:03d}"


def raise_flag(args, settings, recipients) -> int:
    """Confirm a flag, record it, and get the alert out the same day.

    Doing this by hand meant editing two files and copying a draft into a mail
    client - four steps between deciding something is urgent and anyone hearing
    about it. Each one is a place a Friday-afternoon escalation stalls.
    """
    if not args.reason:
        print(f"--reason is required; one of: {', '.join(H.RED_FLAG_REASONS)}", file=sys.stderr)
        return 2
    if args.reason not in H.RED_FLAG_REASONS:
        print(f"Unknown reason {args.reason!r}; one of: {', '.join(H.RED_FLAG_REASONS)}",
              file=sys.stderr)
        return 2

    rows = H.read_csv(H.MENTIONS_CSV)
    row = next((r for r in rows if r.get("mention_id") == args.raise_id), None)
    if row is None:
        print(f"No mention {args.raise_id!r} in data/mentions.csv", file=sys.stderr)
        return 2

    row["red_flag"] = "yes"
    row["red_flag_reason"] = args.reason
    row["status"] = "escalated"
    with open(H.MENTIONS_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=H.MENTION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in H.MENTION_FIELDS})

    escalations = H.read_csv(H.ESCALATIONS_CSV)
    if any(e.get("mention_id") == args.raise_id for e in escalations):
        print(f"{args.raise_id} already has an escalation logged.")
    else:
        names = ", ".join(p.get("name", "") for p in recipients.get("red_flag", []))
        H.append_csv(H.ESCALATIONS_CSV, H.ESCALATION_FIELDS, [{
            "escalation_id": next_escalation_id(escalations),
            "raised_at": dt.date.today().isoformat(),
            "week_of": row.get("week_of", ""),
            "mention_id": args.raise_id,
            "entity": row.get("entity", ""),
            "platform": row.get("platform", ""),
            "url": row.get("url", ""),
            "severity": args.severity,
            "reason": args.reason,
            "notified": names,
            "notified_at": dt.date.today().isoformat() if args.send else "",
            "owner": args.owner,
            "action_taken": "Alert sent" if args.send else "Alert drafted, not yet sent",
            "status": "open",
            "closed_at": "",
        }])
        print(f"Logged escalation for {args.raise_id} ({args.severity}, {args.reason}).")

    body = draft_alert(row, settings, recipients)
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"red-flag-{args.raise_id}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    print(f"Alert drafted: {path}\n")

    to, missing = [], []
    for person in recipients.get("red_flag", []):
        email = str(person.get("email", "")).strip()
        if not email or H.is_todo(email):
            missing.append(person.get("name", "?"))
        else:
            to.append(f"{person.get('name','')} <{email}>".strip())

    if not args.send:
        print(body)
        print("\nNot sent. Add --send to email it now.")
        return 0

    cfg, missing_env = mailer.smtp_settings()
    blockers = []
    if missing:
        blockers.append(f"no address for {', '.join(missing)}")
    if not to:
        blockers.append("no recipient addresses at all")
    if missing_env:
        blockers.append(f"{', '.join(missing_env)} not set")
    if not cfg["sender"]:
        blockers.append("SMTP_FROM not set")
    if blockers:
        print("Not sent:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        print(f"\nThe alert is at {path} - send it by hand rather than letting it wait.",
              file=sys.stderr)
        return 1

    entities = H.entity_names()
    subject = (f"[RED FLAG] {entities.get(row.get('entity'), row.get('entity',''))} - "
               f"{args.reason.replace('_', ' ')} - "
               f"{row.get('post_date') or dt.date.today().isoformat()}")
    message = mailer.build_message(
        subject, to, cfg["sender"], body,
        reply_to=str(settings.get("programme", {}).get("reply_to", "")).strip()
        if not H.is_todo(settings.get("programme", {}).get("reply_to", "")) else "")
    try:
        mailer.send(message, cfg)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"Send failed: {exc}\nThe alert is at {path} - send it by hand.", file=sys.stderr)
        return 1
    print(f"Alert sent to {len(to)} recipient(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="restrict to one week_of Monday (YYYY-MM-DD)")
    parser.add_argument("--scan", action="store_true",
                        help="suggest rows whose wording looks like a trigger")
    parser.add_argument("--alert", metavar="MENTION_ID", help="draft the alert email for one mention")
    parser.add_argument("--out-dir", default=H.OUT_DIR)
    parser.add_argument("--raise", dest="raise_id", metavar="MENTION_ID",
                        help="confirm a red flag: set it on the row, log the escalation, "
                             "and draft the alert")
    parser.add_argument("--reason", help=f"required with --raise: {', '.join(H.RED_FLAG_REASONS)}")
    parser.add_argument("--severity", default="high", choices=["high", "critical"])
    parser.add_argument("--owner", default="desk")
    parser.add_argument("--send", action="store_true",
                        help="with --raise, actually email the alert now")
    parser.add_argument("--exit-code", action="store_true",
                        help="exit 1 if the scan finds candidates, so a scheduled run "
                             "can raise them instead of passing quietly")
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

    if args.raise_id:
        return raise_flag(args, settings, recipients)

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
        found = suggestions(mentions, settings)
        if not found:
            print("Scan found nothing that looks like a trigger.")
            return 0
        print(f"{len(found)} row(s) worth a second look — a human decides, not the script:\n")
        for m, reasons in found:
            print(f"  {m.get('mention_id','?')} [{m.get('entity')}/{m.get('platform')}] "
                  f"-> {', '.join(reasons)}")
            print(f"      {(m.get('one_line_summary') or m.get('title_or_snippet',''))[:110]}")
            print(f"      {m.get('url','')}")
        print("\nIf a suggestion is right, set red_flag=yes and red_flag_reason, then run:")
        print("  python3 scripts/red_flags.py --alert <MENTION_ID>")
        return 1 if args.exit_code else 0

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
