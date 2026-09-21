#!/usr/bin/env python3
"""Send the weekly digest to the distribution list over SMTP.

The brief says the digest goes in the body of the email with no attachments,
so this sends multipart/alternative: the HTML body plus a plain-text fallback.

Credentials come from the environment, never from this repo:

    SMTP_HOST      smtp.zeptomail.in, smtp.gmail.com, ...
    SMTP_PORT      587 for STARTTLS (default), 465 for implicit TLS
    SMTP_USER
    SMTP_PASSWORD
    SMTP_FROM      "HR Intelligence <hr-intel@example.com>"

    python3 scripts/send_digest.py                  # dry run - prints, sends nothing
    python3 scripts/send_digest.py --send
    python3 scripts/send_digest.py --send --week 2026-09-19

Nothing is sent without --send. The refusals below are deliberate: an email to
four executives cannot be unsent.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_digest  # noqa: E402
import hrintel as H  # noqa: E402


def recipients(group: str = "digest") -> tuple[list[str], list[str]]:
    """(usable addresses, names still without one)."""
    people = H.load_yaml("recipients").get(group, [])
    ready, missing = [], []
    for person in people:
        email = str(person.get("email", "")).strip()
        if not email or H.is_todo(email):
            missing.append(person.get("name", "?"))
        else:
            ready.append(f"{person.get('name', '')} <{email}>".strip())
    return ready, missing


def build_message(subject: str, body_html: str, body_text: str,
                  to: list[str], sender: str, reply_to: str = "") -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    if reply_to and not H.is_todo(reply_to):
        message["Reply-To"] = reply_to
    message.set_content(body_text)
    message.add_alternative(body_html, subtype="html")
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", help="week_of start day; default = the reporting week")
    parser.add_argument("--send", action="store_true",
                        help="actually send; without it this only prints")
    parser.add_argument("--force", action="store_true",
                        help="send even if the week is still running")
    parser.add_argument("--subject-prefix", default="",
                        help='e.g. "[SAMPLE] " when circulating for format feedback')
    args = parser.parse_args()

    week = H.parse_date(args.week) if args.week else H.last_complete_week()
    if week is None:
        print(f"Could not read --week {args.week!r}", file=sys.stderr)
        return 2
    week = H.week_start_of(week)

    settings = H.load_yaml("settings")
    subject, body_html, body_text, stats = build_digest.build(week, settings)
    subject = args.subject_prefix + subject

    to, missing = recipients("digest")
    sender = str(settings.get("programme", {}).get("reply_to", "")).strip()
    sender_env = os.environ.get("SMTP_FROM", "").strip()
    from_addr = sender_env or (sender if sender and not H.is_todo(sender) else "")

    print(f"Week      : {H.fmt_week(week)}")
    print(f"Subject   : {subject}")
    print(f"To        : {', '.join(to) if to else '(none)'}")
    print(f"From      : {from_addr or '(not set - SMTP_FROM or programme.reply_to)'}")
    print(f"Content   : {stats['total']} mention(s), {stats['red_flags']} red flag(s), "
          f"{stats['untagged']} untagged")

    refusals = []
    if not to:
        refusals.append("no usable recipient addresses in config/recipients.yaml")
    if missing:
        refusals.append(f"no address yet for {', '.join(missing)}")
    if stats["partial"] and not args.force:
        refusals.append(f"the week is still running ({stats['days_elapsed']} of 7 days) - "
                        "a partial week reads as a full one; use --force if that is intended")
    if not from_addr:
        refusals.append("no From address (set SMTP_FROM, or programme.reply_to in settings)")

    if refusals:
        print("\nNot sending:")
        for r in refusals:
            print(f"  - {r}")
        return 1

    if stats["untagged"]:
        print(f"\nWarning: {stats['untagged']} mention(s) are untagged. They are counted but "
              "excluded from net sentiment, and the digest says so.")

    if not args.send:
        print("\nDRY RUN - nothing sent. Re-run with --send.")
        print("-" * 68)
        print(body_text)
        return 0

    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    if not (host and user and password):
        print("\nSMTP_HOST, SMTP_USER and SMTP_PASSWORD must all be set.", file=sys.stderr)
        return 2

    message = build_message(subject, body_html, body_text, to, from_addr,
                            settings.get("programme", {}).get("reply_to", ""))
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls(context=context)
                smtp.login(user, password)
                smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"\nSend failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nSent to {len(to)} recipient(s).")
    print("Record it: git add data/ && git commit && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
