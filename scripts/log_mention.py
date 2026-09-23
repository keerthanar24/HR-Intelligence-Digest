#!/usr/bin/env python3
"""Log one review or post as a mention, validated against the vocabularies.

A rating snapshot is one number for a whole company. A mention is one row per
review or post, and that is what sections 1, 3 and 4 of the digest are built
from - so capturing ratings alone leaves those sections empty.

    python3 scripts/log_mention.py \\
        -e rk_world -p ambitionbox -d 2026-09-20 \\
        -s "Ex-employee says FnF pending two months, HR not replying" \\
        --sentiment very_negative --themes payroll_delay,exits \\
        --author ex_employee --url https://... --flag non_payment

    python3 scripts/log_mention.py --vocab      # list the allowed values
    python3 scripts/log_mention.py --week 2026-09-19 --list
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402


def show_vocab() -> int:
    print("sentiment  :", ", ".join(H.SENTIMENT_SCORES))
    print("themes     :", ", ".join(H.THEMES))
    print("author     :", ", ".join(H.AUTHOR_TYPES))
    print("status     :", ", ".join(H.STATUSES))
    print("flag reason:", ", ".join(H.RED_FLAG_REASONS))
    print("entities   :", ", ".join(H.entity_names()))
    print("platforms  :", ", ".join(H.platform_names()))
    return 0


def show_all() -> int:
    """Everything logged, grouped by page.

    A back-read covers sixty days, which is nine reporting weeks, so listing
    one week at a time cannot answer the only question that matters while
    doing it: which pages have I finished? Grouping by entity and platform
    does.
    """
    rows = H.read_csv(H.MENTIONS_CSV)
    entities, platforms = H.entity_names(), H.platform_names()
    if not rows:
        print("Nothing logged yet.")
        return 0
    by_page: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        by_page.setdefault((row.get("entity", ""), row.get("platform", "")), []).append(row)
    print(f"{len(rows)} mention(s) logged, across {len(by_page)} page(s)\n")
    for (entity, platform), group in sorted(by_page.items()):
        dates = sorted(r.get("post_date", "") for r in group if r.get("post_date"))
        span = f"{dates[0]} to {dates[-1]}" if dates else "no dates"
        flags = sum(1 for r in group if H.is_yes(r.get("red_flag")))
        print(f"  {entities.get(entity, entity):<18} {platforms.get(platform, platform):<13} "
              f"{len(group):>3} review(s)   {span}"
              f"{f'   {flags} RED FLAG' if flags else ''}")
        # The summary is the line that reaches the email, so this is where it
        # gets checked. Counts alone cannot tell a rewritten row from the one
        # it replaced.
        for row in sorted(group, key=lambda r: r.get("post_date", "")):
            tag = row.get("sentiment") or "UNTAGGED"
            print(f"      {row['mention_id']}  {row.get('post_date',''):<11} {tag:<14} "
                  f"{(row.get('themes') or '').replace('|', ', ')}")
            print(f"        {(row.get('one_line_summary') or '')[:96]}")
    untagged = [r for r in rows if not (r.get("sentiment") or "").strip()]
    if untagged:
        print(f"\n{len(untagged)} still untagged - excluded from net sentiment until tagged.")
    return 0


def show_week(week: dt.date) -> int:
    rows = H.mentions_for_week(H.read_csv(H.MENTIONS_CSV), week)
    print(f"{len(rows)} mention(s) logged for {H.fmt_week(week)}\n")
    for r in sorted(rows, key=lambda x: x.get("post_date", "")):
        tag = r.get("sentiment") or "UNTAGGED"
        flag = "  [RED FLAG]" if H.is_yes(r.get("red_flag")) else ""
        print(f"  {r['mention_id']}  {r.get('post_date',''):<11} "
              f"{r.get('entity',''):<18} {r.get('platform',''):<12} {tag}{flag}")
        print(f"      {(r.get('one_line_summary') or '')[:92]}")
    untagged = [r for r in rows if not (r.get("sentiment") or "").strip()]
    if untagged:
        print(f"\n{len(untagged)} still untagged - excluded from net sentiment until tagged.")
    return 0


def ask(prompt, *, allowed=None, default="", required=False, multi=False):
    """One prompt, re-asked until the answer is inside the vocabulary.

    A back-read is thirty to sixty reviews. Composing a long command line for
    each is where typos and invented theme names come from, so this asks field
    by field and rejects a bad value on the spot rather than at validation
    time, when the reviewer has closed the page and cannot check.
    """
    hint = ""
    if allowed:
        hint = "\n    " + " | ".join(allowed)
    while True:
        shown = f" [{default}]" if default else ""
        raw = input(f"  {prompt}{shown}{hint}\n  > ").strip()
        if not raw:
            raw = default
        if not raw and required:
            print("    needed.")
            continue
        if allowed and raw:
            values = [v.strip() for v in raw.replace(",", "|").split("|") if v.strip()] \
                if multi else [raw]
            # Accept any capitalisation and a space where the value has an
            # underscore. "Current_employee" and "current employee" both
            # plainly mean current_employee, and bouncing them teaches nothing
            # except that the tool is fussy.
            lookup = {a.lower(): a for a in allowed}
            lookup.update({a.lower().replace("_", " "): a for a in allowed})
            lookup.update({a.lower().replace("_", "-"): a for a in allowed})
            fixed, bad = [], []
            for value in values:
                match = lookup.get(value.lower())
                (fixed if match else bad).append(match or value)
            if bad:
                print(f"    not on the list: {', '.join(bad)}")
                continue
            return "|".join(fixed) if multi else fixed[0]
        return raw


def interactive(defaults) -> list[argparse.Namespace]:
    """Walk one review at a time. Entity, platform and date carry over.

    Reading a page means logging several reviews from the same page in a row,
    so the fields that do not change between them are remembered and offered
    as the default.
    """
    entities, platforms = H.entity_names(), H.platform_names()
    print("\nLogging reviews one at a time. Blank answer = the value in [brackets].")
    print("Each review is saved as you finish it, so Ctrl-C is safe.\n")
    collected, last = [], dict(entity=defaults.entity or "", platform=defaults.platform or "")
    while True:
        print("-" * 68)
        entity = ask("entity", allowed=list(entities), default=last["entity"], required=True)
        platform = ask("platform", allowed=list(platforms), default=last["platform"],
                       required=True)
        date = ask("date the review was posted (YYYY-MM-DD)", required=True)
        # An interview experience does not move a page's review count, so the
        # completeness gate has to tell them apart.
        item = ask("what kind of item", allowed=H.ITEM_TYPES,
                   default="review" if platform in H.VERBATIM_REQUIRED else "post")
        title = ask("the post's own words - its title, or its first line",
                    required=platform in H.VERBATIM_REQUIRED)
        summary = ask("one factual sentence - no names, no interpretation", required=True)
        sentiment = ask("sentiment", allowed=list(H.SENTIMENT_SCORES), required=True)
        themes = ask("theme(s), comma separated", allowed=H.THEMES, multi=True, required=True)
        author = ask("who wrote it", allowed=H.AUTHOR_TYPES, default="unknown")
        role = ask("department or role, if the page shows one (optional)")
        stars = ask("stars the reviewer gave, 1-5 (optional)")
        # Only where the platform publishes one. settings.yaml treats
        # engagement >= virality_engagement_threshold as public_escalation_risk,
        # and this prompt never asked for it - so on LinkedIn and X, the two
        # places a complaint can actually gather momentum, the trigger could
        # not fire. A red flag that cannot be raised is not a safeguard.
        reach = ""
        if H.engagement_applies(platform):
            reach = ask("reactions + comments + reposts, roughly (optional)")
        url = ask("link to the review (optional)")
        flag = ask("red-flag trigger, blank if none", allowed=H.RED_FLAG_REASONS)
        names = ask("does it name an individual? y/N", default="n").lower().startswith("y")

        one = argparse.Namespace(
            entity=entity, platform=platform, date=date, summary=summary,
            item_type=item,
            sentiment=sentiment, themes=themes, author=author, url=url, title=title,
            role=role, rating=stars,
            engagement=int(reach) if reach.isdigit() else None,
            names_individual=names,
            flag=flag or None, notes="", mixed_post=False, by=defaults.by,
            vocab=False, list=False, week=None, all=False, remove=None,
            interactive=False)
        # Written now, not at the end of the session. Queuing until the loop
        # closed meant one Ctrl-C - to check the list, or by accident - threw
        # away everything logged so far, which on a sixty-day back-read is an
        # hour of reading.
        if log_one(one) == 0:
            collected.append(one)
        last = {"entity": entity, "platform": platform}
        print(f"  {len(collected)} logged this session")
        if not ask("another from this page? Y/n", default="y").lower().startswith("y"):
            return collected


def remove(mention_id: str) -> int:
    """Delete one logged mention.

    A back-read is done in one long sitting, and a mis-tagged row noticed three
    reviews later had no way out except editing the CSV by hand - which is how
    a header gets mangled or a comma-bearing summary gets split. Refuses when
    an escalation points at the row, because deleting it would leave the
    restricted log referring to a mention that no longer exists.
    """
    rows = H.read_csv(H.MENTIONS_CSV)
    target = [r for r in rows if r.get("mention_id") == mention_id]
    if not target:
        print(f"No mention {mention_id!r}. "
              f"List them with: python3 scripts/log_mention.py --list", file=sys.stderr)
        return 2

    linked = [e for e in H.read_csv(H.ESCALATIONS_CSV)
              if e.get("mention_id") == mention_id]
    if linked:
        print(f"{mention_id} is referenced by escalation "
              f"{linked[0].get('escalation_id')}. Close or correct the escalation first - "
              "deleting the mention would leave the restricted log pointing at nothing.",
              file=sys.stderr)
        return 3

    row = target[0]
    keep = [r for r in rows if r.get("mention_id") != mention_id]
    with open(H.MENTIONS_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=H.MENTION_FIELDS)
        writer.writeheader()
        writer.writerows(keep)
    print(f"Removed {mention_id}  {row.get('entity')} / {row.get('platform')} / "
          f"{row.get('post_date')}")
    print(f"  {row.get('one_line_summary', '')[:90]}")
    print(f"  {len(keep)} mention(s) left.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-e", "--entity")
    p.add_argument("-p", "--platform")
    p.add_argument("-d", "--date", help="date the review or post was published (YYYY-MM-DD)")
    p.add_argument("-s", "--summary", help="one factual sentence, no names, no interpretation")
    p.add_argument("--sentiment", help="very_negative | negative | neutral | mixed | positive | very_positive")
    p.add_argument("--themes", help="comma or pipe separated, from the fixed list")
    p.add_argument("--author", default="unknown")
    p.add_argument("--url", default="")
    p.add_argument("--title", default="", help="review title or first line, as published")
    p.add_argument("--item-type", dest="item_type", default="review",
                   choices=H.ITEM_TYPES,
                   help="review (default), interview, post, comment or article - "
                        "only 'review' counts against a page's review count")
    p.add_argument("--role", default="",
                   help="department or role, when the review page shows one")
    p.add_argument("--rating", help="stars the reviewer gave, 1-5")
    p.add_argument("--engagement", type=int, help="likes + reposts + comments")
    p.add_argument("--names-individual", action="store_true",
                   help="the post names a person (a red-flag trigger)")
    p.add_argument("--flag", help=f"red-flag reason: {', '.join(H.RED_FLAG_REASONS)}")
    p.add_argument("--notes", default="")
    p.add_argument("--mixed-post", action="store_true",
                   help="the post mixes a customer complaint with an employment one; "
                        "log only the employment half")
    p.add_argument("--by", default="desk")
    p.add_argument("--vocab", action="store_true", help="print the allowed values")
    p.add_argument("--list", action="store_true", help="show what is logged for a week")
    p.add_argument("--remove", metavar="MENTION_ID",
                   help="delete a mention logged by mistake")
    p.add_argument("--week", help="with --list, the week to show")
    p.add_argument("--all", action="store_true",
                   help="with --list, every week grouped by page - the back-read view")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="prompt for each field instead of composing a command line; "
                        "the way to do a back-read")
    args = p.parse_args()

    if args.vocab:
        return show_vocab()
    if args.remove:
        return remove(args.remove)
    if args.list:
        if args.all:
            return show_all()
        week = H.parse_date(args.week) if args.week else H.last_complete_week()
        return show_week(H.week_start_of(week))
    if args.interactive:
        try:
            done = interactive(args)
        except (KeyboardInterrupt, EOFError):
            print("\n  stopped. Everything logged before this point is saved.")
            return 0
        print(f"\n{len(done)} logged this session.")
        return 0

    return log_one(args)


def log_one(args) -> int:

    entities, platforms = H.entity_names(), H.platform_names()
    problems = []
    if args.entity not in entities:
        problems.append(f"entity {args.entity!r}; one of: {', '.join(entities)}")
    if args.platform not in platforms:
        problems.append(f"platform {args.platform!r}; one of: {', '.join(platforms)}")
    posted = H.parse_date(args.date or "")
    if posted is None:
        problems.append(f"date {args.date!r}; expected YYYY-MM-DD")
    elif posted > dt.date.today():
        problems.append(f"date {args.date} is in the future")
    if not (args.summary or "").strip():
        problems.append("a one-line summary is required - it is what the four actually read")

    sentiment = (args.sentiment or "").strip().lower()
    if sentiment and sentiment not in H.SENTIMENT_SCORES:
        problems.append(f"sentiment {sentiment!r}; one of: {', '.join(H.SENTIMENT_SCORES)}")
    themes = [t.strip() for t in (args.themes or "").replace(",", "|").split("|") if t.strip()]
    for theme in themes:
        if theme not in H.THEMES:
            problems.append(f"theme {theme!r}; see --vocab")
    if args.author not in H.AUTHOR_TYPES:
        problems.append(f"author {args.author!r}; one of: {', '.join(H.AUTHOR_TYPES)}")
    if args.flag and args.flag not in H.RED_FLAG_REASONS:
        problems.append(f"flag {args.flag!r}; one of: {', '.join(H.RED_FLAG_REASONS)}")

    # The out-of-scope list in the brief is a guardrail, enforced here rather
    # than left to whoever is logging at 5pm on a Friday.
    profile = H.personal_profile_reason(args.url)
    if profile:
        print(f"REFUSED: that URL is {profile}.", file=sys.stderr)
        print("Surveillance of individuals' personal social media accounts is out of scope "
              "(docs/00-brief.md section 4).", file=sys.stderr)
        print("A company page, or one specific public post about the employer, is in scope - "
              "link to that instead.", file=sys.stderr)
        return 3

    if problems:
        for problem in problems:
            print(f"  invalid {problem}", file=sys.stderr)
        return 2

    # The review's own words are the only thing in the row that is not an
    # interpretation. Optional meant nobody typed one, so a summary written in
    # August has nothing behind it when someone asks in November what the
    # review actually said.
    if not args.title.strip() and args.platform in H.VERBATIM_REQUIRED:
        print(f"REFUSED: this {platforms.get(args.platform, args.platform)} review needs its "
              "own words as well as your summary.", file=sys.stderr)
        print("Pass --title with the review title, or its first line if it has no title. "
              "It is the only verbatim text the row keeps.", file=sys.stderr)
        return 2

    customer_words = H.customer_side_terms(f"{args.summary} {args.title} {args.notes}")
    if customer_words and not args.mixed_post:
        print(f"REFUSED: this reads as customer-side - found {', '.join(customer_words)}.",
              file=sys.stderr)
        print("Customer or seller complaints and product reviews are out of scope.",
              file=sys.stderr)
        print("If the post mixes a customer complaint with an employment one, summarise only "
              "the employment half and re-run with --mixed-post.", file=sys.stderr)
        return 3

    existing = H.read_csv(H.MENTIONS_CSV)
    canonical = H.canonical_url(args.url)
    if canonical:
        clash = [r for r in existing if H.canonical_url(r.get("url", "")) == canonical]
        if clash:
            print(f"Already logged as {clash[0]['mention_id']} - same URL.", file=sys.stderr)
            return 1

    week = H.week_start_of(posted)
    row = {f: "" for f in H.MENTION_FIELDS}
    row.update({
        "mention_id": H.next_mention_id(existing, week),
        "week_of": week.isoformat(),
        "captured_at": dt.date.today().isoformat(),
        "captured_by": args.by,
        "entity": args.entity,
        "platform": args.platform,
        "source_name": platforms.get(args.platform, args.platform),
        "url": args.url,
        "post_date": posted.isoformat(),
        "item_type": getattr(args, "item_type", "") or "review",
        "author_type": args.author,
        "role_or_dept": args.role,
        "title_or_snippet": args.title[:300],
        "one_line_summary": args.summary.strip(),
        "sentiment": sentiment,
        "themes": "|".join(themes),
        "rating_given": args.rating or "",
        # Blank meant two different things: "this platform has no engagement
        # count" and "nobody recorded one". On X the second is a gap in the
        # evidence for the public_escalation_risk trigger, so they have to look
        # different.
        "engagement": (str(args.engagement) if args.engagement is not None
                       else ("" if H.engagement_applies(args.platform) else "n/a")),
        "names_individual": "yes" if args.names_individual else "no",
        "red_flag": "yes" if (args.flag or args.names_individual) else "no",
        "red_flag_reason": args.flag or ("names_individual" if args.names_individual else ""),
        "status": "escalated" if args.flag or args.names_individual else
                  ("reviewed" if sentiment else "needs_review"),
        "notes": (args.notes + ("; mixed post - only the employment half logged"
                                if args.mixed_post else "")).strip("; "),
    })

    H.append_csv(H.MENTIONS_CSV, H.MENTION_FIELDS, [row])
    print(f"Logged {row['mention_id']}  {entities[args.entity]} / "
          f"{platforms[args.platform]} / {row['post_date']} / {sentiment or 'UNTAGGED'}")
    print(f"  week of {H.fmt_week(week)}")
    if not sentiment:
        print("  No sentiment given - it will be counted but excluded from the average, "
              "and the digest will report it as untagged.")
    if row["red_flag"] == "yes":
        print(f"  RED FLAG ({row['red_flag_reason']}). This does not wait for Friday:")
        print(f"    python3 scripts/red_flags.py --alert {row['mention_id']}")
        print("    then log the escalation in data/escalations.csv")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except H.FileInUse as locked:
        # A locked file is somebody's Excel window, not a bug. Say so once,
        # without a traceback that buries the one sentence that matters.
        print(f"\n{locked}", file=sys.stderr)
        raise SystemExit(4)
