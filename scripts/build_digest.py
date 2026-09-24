#!/usr/bin/env python3
"""Build the weekly HR Intelligence Digest email body from the tracking data.

Produces the six sections agreed in the brief, as HTML for pasting into the
email body (no attachments) and as plain text for the record.

    python3 scripts/build_digest.py                      # last complete week
    python3 scripts/build_digest.py --week 2026-09-07
    python3 scripts/build_digest.py --stdout             # print text to console
    python3 scripts/build_digest.py --strict             # fail on untagged rows
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

BOUNDARY_NOTE = (
    "Scope: public, employment-related commentary only — culture, management, pay, "
    "appraisals, exits, layoffs, hours, interviews, onboarding, and harassment or "
    "safety allegations. Customer and product complaints are out of scope, and we do "
    "not monitor any individual's personal social media accounts."
)

# The five triggers, as the brief names them, in the form the digest prints.
TRIGGER_LABELS = {
    "names_individual": "Names an individual",
    "harassment_or_safety": "Harassment / safety",
    "non_payment": "Non-payment",
    "legal_or_regulatory": "Legal / regulatory",
    "public_escalation_risk": "Public escalation risk",
}

TRIAL_NOTE = (
    "This is a 60-day awareness trial. No action items or HR process changes follow "
    "from this digest; only Red Flags are escalated. Review sites lag by 2–3 months, "
    "so treat this as a trailing indicator."
)


# --- aggregation -------------------------------------------------------------


def delta_text(current, previous, digits=0, suffix="") -> str:
    """Week-on-week change, or 'n/a' when there is nothing to compare against."""
    if current is None or previous is None:
        return "n/a"
    diff = current - previous
    # Anything that would round to zero at the displayed precision is "no change".
    if abs(diff) < 0.5 * (10 ** -digits):
        return "no change"
    sign = "+" if diff > 0 else "-"
    return f"{sign}{abs(diff):.{digits}f}{suffix}"


def sentiment_text(value) -> str:
    """Net sentiment on the -2..+2 scale; blank when nothing is tagged."""
    if value is None:
        return "—"
    if abs(value) < 0.005:
        return "0.00"
    return f"{value:+.2f}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def headline_rows(mentions_now, mentions_prev, entities, comparable=True):
    """Per-entity counts and sentiment, with a group total row at the end.

    RK Group is the parent and the other four are its subsidiaries, so the four
    executives read this as one group first and a breakdown second. The parent
    keeps its own row - it is an employer in its own right - and the total
    spans every entity including it.

    comparable=False for the week 1 baseline: nothing precedes it, so a delta
    against an empty previous period would read "+3" as though three reviews
    had arrived in a week, when they arrived across sixty days.
    """
    rows = []
    for entity_id, name in entities.items():
        now = [m for m in mentions_now if m.get("entity") == entity_id]
        prev = [m for m in mentions_prev if m.get("entity") == entity_id]
        net_now = H.net_sentiment(now)
        net_prev = H.net_sentiment(prev)
        rows.append(
            {
                "entity": name,
                "count": len(now),
                "count_prev": len(prev),
                "count_delta": delta_text(len(now), len(prev)) if comparable else "n/a",
                "net": sentiment_text(net_now),
                "net_prev": sentiment_text(net_prev),
                "net_delta": delta_text(net_now, net_prev, digits=2) if comparable else "n/a",
                "untagged": len(H.untagged_rows(now)),
                "is_total": False,
            }
        )

    net_now, net_prev = H.net_sentiment(mentions_now), H.net_sentiment(mentions_prev)
    rows.append(
        {
            "entity": "Group total",
            "count": len(mentions_now),
            "count_prev": len(mentions_prev),
            "count_delta": (delta_text(len(mentions_now), len(mentions_prev))
                            if comparable else "n/a"),
            "net": sentiment_text(net_now),
            "net_prev": sentiment_text(net_prev),
            "net_delta": (delta_text(net_now, net_prev, digits=2)
                          if comparable else "n/a"),
            "untagged": len(H.untagged_rows(mentions_now)),
            "is_total": True,
        }
    )
    return rows


def stars_text(mention) -> str:
    """'2/5' for a review that carried a star rating, else an em dash.

    Every review logged in the back-read had one and none of them reached the
    email. A one-line summary without the star rating hides the gap between a
    grumble filed at 4 stars and the same words filed at 1.
    """
    value = H.to_int(str(mention.get("rating_given") or "").strip(), 0)
    return f"{value}/5" if 1 <= value <= 5 else "—"


def sentiment_label(mention) -> str:
    """The sentiment column. A company post is unscored by design, not by neglect.

    "Untagged" on a company row reads as work outstanding, and the reader who
    goes looking for the missing tag will not find one - the row is never
    getting scored. "Not scored" says the same absence and the right reason.
    """
    key = (mention.get("sentiment") or "").strip().lower()
    if not key and H.is_company_voice(mention):
        return "Not scored"
    return H.SENTIMENT_LABELS.get(key, "Untagged")


def author_text(mention) -> str:
    """'Ex-employee', 'Candidate', 'Anonymous' - who the line came from."""
    key = (mention.get("author_type") or "").strip().lower()
    return H.AUTHOR_LABELS.get(key, "Unknown")


def recommend_text(current, previous) -> str:
    """'64%', or '64% (+3pp)' once there is a week to compare against."""
    if current is None:
        return "—"
    shown = f"{current:.0f}%"
    if previous is None:
        return shown
    move = delta_text(current, previous, suffix="pp")
    return shown if move in ("n/a", "no change") else f"{shown} ({move})"


def rating_rows(ratings, week_of, entities, platforms):
    """Latest snapshot in the week, compared with the most recent earlier one."""
    target = week_of.isoformat()
    rows = []
    by_key = collections.defaultdict(list)
    for r in ratings:
        by_key[(r.get("entity"), r.get("platform"))].append(r)

    for (entity_id, platform), snaps in sorted(by_key.items()):
        snaps.sort(key=lambda r: r.get("week_of", ""))
        current = [s for s in snaps if s.get("week_of") == target]
        earlier = [s for s in snaps if s.get("week_of", "") < target]
        if not current:
            continue
        now, prev = current[-1], (earlier[-1] if earlier else None)
        score_now = H.to_float(now.get("overall_rating"))
        score_prev = H.to_float(prev.get("overall_rating")) if prev else None
        count_now = H.to_int(now.get("review_count"), 0)
        count_prev = H.to_int(prev.get("review_count"), 0) if prev else None
        # Percent-recommend is collected on every Glassdoor sweep and was never
        # shown. Westbury reads 0% on two reviews - the sharpest number in the
        # set, and it was sitting in the sheet only.
        rec_now = H.to_float(now.get("recommend_pct"))
        rec_prev = H.to_float(prev.get("recommend_pct")) if prev else None
        rows.append(
            {
                "entity": entities.get(entity_id, entity_id),
                "platform": platforms.get(platform, platform.replace("_", " ").title()),
                "rating": f"{score_now:.2f}" if score_now is not None else "—",
                "rating_delta": delta_text(score_now, score_prev, digits=2),
                "reviews": count_now,
                "reviews_delta": delta_text(count_now, count_prev),
                # The change rides in the same cell: an eighth column does not
                # fit an email table, and the figure is useless without it.
                "recommend": recommend_text(rec_now, rec_prev),
                "recommend_delta": delta_text(rec_now, rec_prev, suffix="pp"),
                "since": prev.get("week_of") if prev else "first snapshot",
            }
        )
    return rows


def coverage_rows(mentions_now, all_ratings, week_of, entities, platforms,
                  expected=None, baseline=False):
    """What the sweep covered, and every reason the week is not yet verified.

    "Every new review" cannot be guaranteed while three platforms are read by
    hand. But the rating snapshot carries the review COUNT, so the change in
    that count is the number of reviews a platform genuinely gained, and
    comparing it with how many were logged turns an unverifiable claim into
    arithmetic.

    The arithmetic only works with two snapshots to subtract, and the first
    version simply skipped a pair that did not have them - so a platform nobody
    swept produced no rows and read exactly like a quiet week. "Could not
    check" is not "checked and complete", so every profile the sweep is
    expected to cover is enumerated up front and each one has to come back
    accounted for:

      not_swept     - no snapshot this week; nobody looked
      no_baseline   - snapshot this week but none last week; nothing to subtract
      unread        - the count moved further than the logged rows explain
      count_dropped - fewer reviews than last week, which cannot happen; the
                      page was read a different way

    Week 1 is the exception: a baseline week has no previous snapshot by
    definition, so no_baseline is not raised there. not_swept still is - a
    profile nobody opened is a failure in any week.
    """
    prev_week = (week_of - dt.timedelta(days=7)).isoformat()
    this_week = week_of.isoformat()
    counts = {}
    for row in all_ratings:
        key = (row.get("entity"), row.get("platform"))
        if row.get("week_of") == this_week:
            counts.setdefault(key, {})["now"] = H.to_int(row.get("review_count"), -1)
            counts[key]["url"] = row.get("url", "")
        elif row.get("week_of") == prev_week:
            counts.setdefault(key, {})["prev"] = H.to_int(row.get("review_count"), -1)

    # Only reviews. An interview experience or a LinkedIn post is a mention
    # but does not move a page's review count, so counting it here made the
    # sum reach the target while a real review sat unread.
    logged = collections.Counter(
        (m.get("entity"), m.get("platform")) for m in mentions_now if H.is_review(m))

    if expected is None:
        expected = H.rated_profiles()

    gaps, swept = [], set()

    def note(kind, entity_id, platform, **extra):
        gaps.append({
            "kind": kind,
            "entity": entities.get(entity_id, entity_id),
            "platform": platforms.get(platform, platform),
            "url": counts.get((entity_id, platform), {}).get("url", ""),
            "new": 0, "logged": logged.get((entity_id, platform), 0), "missing": 0,
            **extra,
        })

    for key in sorted(set(expected) | set(counts)):
        entity_id, platform = key
        seen = counts.get(key, {})
        now, before = seen.get("now", -1), seen.get("prev", -1)

        if now < 0:
            if key in expected:
                note("not_swept", entity_id, platform)
            continue

        swept.add(platform)
        if before < 0:
            if not baseline:
                note("no_baseline", entity_id, platform)
            continue

        new_reviews = now - before
        already = logged.get(key, 0)
        if new_reviews < 0:
            # Review counts do not go down. A drop means the page was read a
            # different way from last week - a location filter applied or
            # cleared, or the wrong profile opened - and every comparison in
            # section 2 is then measuring two different populations.
            note("count_dropped", entity_id, platform, new=new_reviews)
        elif new_reviews > already:
            note("unread", entity_id, platform,
                 new=new_reviews, missing=new_reviews - already)

    swept |= {m.get("platform") for m in mentions_now if m.get("platform")}
    return sorted(platforms.get(p, p) for p in swept if p), gaps


def rolling_theme_rows(all_mentions, week_of, weeks, limit):
    """Themes recurring across several weeks, not just within one.

    A complaint appearing once a week for four weeks is a pattern, and a
    seven-day window cannot see it - each week reports a lone mention and calls
    it "not yet a pattern". This looks back over `weeks` to catch it.
    """
    start = week_of - dt.timedelta(days=7 * (weeks - 1))
    window = []
    for offset in range(weeks):
        window += H.mentions_for_week(all_mentions, start + dt.timedelta(days=7 * offset))
    window = [m for m in window if (m.get("status") or "") != "out_of_scope"]

    weeks_seen = collections.defaultdict(set)
    for m in window:
        for theme in H.split_themes(m.get("themes", "")):
            weeks_seen[theme].add(m.get("week_of"))

    rows = []
    for row in theme_rows(window, limit):
        theme_key = row["theme"].lower().replace(" ", "_")
        row["weeks"] = len(weeks_seen.get(theme_key, ()))
        rows.append(row)
    # A theme is only "recurring" if it appeared in more than one week.
    return [r for r in rows if r["weeks"] > 1], len(window)


def theme_rows(mentions, limit):
    counter = collections.Counter()
    scores = collections.defaultdict(list)
    examples = collections.defaultdict(list)
    for m in mentions:
        # A company post still names its theme - a hiring push IS a hiring
        # theme, and the count is the honest thing to show. Its score is left
        # out for the reason in H.scored_rows: the employer does not get a
        # vote on how the employer reads.
        score = None if H.is_company_voice(m) else H.sentiment_score(m)
        for theme in H.split_themes(m.get("themes", "")):
            counter[theme] += 1
            if score is not None:
                scores[theme].append(score)
            if m.get("one_line_summary"):
                examples[theme].append(m["one_line_summary"])

    rows = []
    for theme, count in counter.most_common(limit):
        vals = scores[theme]
        mean = sum(vals) / len(vals) if vals else None
        if mean is None:
            lean = "untagged"
        elif mean <= -0.5:
            lean = "complaint"
        elif mean >= 0.5:
            lean = "praise"
        else:
            lean = "mixed"
        rows.append(
            {
                "theme": theme.replace("_", " ").title(),
                "count": count,
                "recurring": count >= 2,
                "lean": lean,
                "net": sentiment_text(mean),
                "example": examples[theme][0] if examples[theme] else "",
            }
        )
    return rows


def red_flag_rows(mentions, escalations, entities, platforms):
    """Red flags raised this week, with the evidence that they went out on time.

    The deliverable promises *same-day* escalation, so the section has to show
    when each was found and when the four were told. Without those two dates a
    flag alerted three days late reads exactly like one alerted within the
    hour, and the one number that matters is invisible.
    """
    by_mention = {e.get("mention_id"): e for e in escalations if e.get("mention_id")}
    rows = []
    for m in mentions:
        if not H.is_yes(m.get("red_flag")):
            continue
        esc = by_mention.get(m.get("mention_id"), {})
        trigger = m.get("red_flag_reason") or esc.get("reason") or ""
        raised = H.parse_date(esc.get("raised_at", "")) or H.parse_date(m.get("captured_at", ""))
        notified = H.parse_date(esc.get("notified_at", ""))

        if notified is None:
            timing, on_time = "NOT YET SENT", False
        elif raised is None:
            timing, on_time = notified.isoformat(), True
        else:
            delay = (notified - raised).days
            on_time = delay <= 0
            timing = "same day" if on_time else f"{delay} day(s) late"

        rows.append(
            {
                "mention_id": m.get("mention_id", ""),
                "entity": entities.get(m.get("entity"), m.get("entity", "")),
                "platform": platforms.get(m.get("platform"), m.get("platform", "")),
                "date": m.get("post_date") or m.get("captured_at", ""),
                "reason": TRIGGER_LABELS.get(trigger, trigger.replace("_", " ") or "unspecified"),
                "severity": (esc.get("severity") or "high").title(),
                "raised": raised.isoformat() if raised else "?",
                "notified": notified.isoformat() if notified else "",
                "timing": timing,
                "on_time": on_time,
                # The digest never carries a named individual; the restricted
                # escalation log does. See docs/00-brief.md section 10.
                "summary": m.get("one_line_summary", ""),
                "url": m.get("url", ""),
                "status": esc.get("status") or m.get("status") or "open",
                "notified_to": esc.get("notified", ""),
                "names_individual": H.is_yes(m.get("names_individual")),
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# --- rendering ---------------------------------------------------------------

E = html.escape


def alert_cell(r):
    """The escalation timing, coloured so a miss cannot be skimmed past.

    Deliverable 5 promises *same-day* escalation. A date on its own does not
    show whether that promise was kept, so the cell carries the verdict too.
    """
    if not r["notified"]:
        return ('<strong style="color:#a12622;">NOT YET SENT</strong><br>'
                '<span style="font-size:11px;color:#a12622;">escalate now</span>')
    colour = "#1e7a3c" if r["on_time"] else "#a12622"
    who = ""
    if r["notified_to"]:
        who = ('<br><span style="font-size:11px;color:#52606d;">to '
               f'{E(truncate(r["notified_to"], 44))}</span>')
    return (f'{E(r["notified"])}<br><strong style="color:{colour};font-size:11px;">'
            f'{E(r["timing"])}</strong>{who}')


def h_table(headers, rows, aligns=None, widths=None):
    """An email-safe table that cannot overflow its container.

    Without table-layout:fixed a long summary widens its column until the table
    runs past the viewport, and mail clients clip the overflow rather than
    scrolling - the rightmost columns simply vanish. Fixed layout plus explicit
    percentage widths and word-break keeps every column on screen and wraps the
    text instead.
    """
    aligns = aligns or ["left"] * len(headers)
    if not widths:
        share = round(100 / len(headers), 2)
        widths = [f"{share}%"] * len(headers)
    out = ['<table role="presentation" cellpadding="8" cellspacing="0" border="0" '
           'style="border-collapse:collapse;width:100%;max-width:100%;table-layout:fixed;'
           'font-size:14px;margin:0 0 8px;">']
    out.append("<tr>")
    for header, align, width in zip(headers, aligns, widths):
        out.append(
            f'<th width="{width}" align="{align}" style="width:{width};background:#f2f4f7;'
            f'border:1px solid #d7dbe0;font-weight:600;color:#1f2933;'
            f'word-break:break-word;">{E(str(header))}</th>'
        )
    out.append("</tr>")
    for index, row in enumerate(rows):
        bg = "#ffffff" if index % 2 == 0 else "#fafbfc"
        out.append("<tr>")
        for cell, align in zip(row, aligns):
            out.append(
                f'<td align="{align}" style="background:{bg};border:1px solid #e3e6ea;'
                f'color:#1f2933;vertical-align:top;word-break:break-word;'
                f'overflow-wrap:anywhere;">{cell}</td>'
            )
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def t_table(headers, rows):
    all_rows = [list(map(str, headers))] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(all_rows[0])).rstrip()]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in all_rows[1:]:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def sheet_contents(mentions, ratings, escalations, week_of):
    """What a recipient will actually find when they open the data link.

    Section 6 used to promise "the full week's raw entries" whether or not the
    sheet held any. Saying the counts turns the link into something checkable,
    and an empty week reads as an empty week rather than as a broken link.
    """
    week = week_of.isoformat()
    counts = [
        (len(mentions), "mention"),
        (sum(1 for r in ratings if r.get("week_of") == week), "rating snapshot"),
        (len(escalations), "escalation"),
    ]
    listed = [f"{n} {word}{'' if n == 1 else 's'}" for n, word in counts if n]
    if not listed:
        return ("Nothing has been logged for this week yet; the sheet still holds "
                "every earlier week.")
    held = ", ".join(listed[:-1]) + (" and " if len(listed) > 1 else "") + listed[-1]
    return f"For this week it holds {held}. Every earlier week is in the same tabs."


def unrated_entities(entities, profiles=None):
    """Entities with no review-site page at all.

    Robust Kommerce has neither a Glassdoor nor an AmbitionBox profile, so it
    can never appear in section 2. An entity that is simply absent from the
    table reads as a quiet week; the truth is that the two platforms carrying
    almost all the evidence cannot see it, and only LinkedIn, Reddit, news and
    X cover it at all. That has to be said, not inferred from a gap.
    """
    covered = {entity_id for entity_id, _ in
               (H.rated_profiles() if profiles is None else profiles)}
    return [name for entity_id, name in entities.items() if entity_id not in covered]


TRIGGER_WORDS = {
    "names_individual": "names an individual",
    "harassment_or_safety": "alleges harassment or a safety issue",
    "non_payment": "alleges non-payment",
    "legal_or_regulatory": "involves a legal or regulatory body",
    "public_escalation_risk": "is gathering public traction",
}


def quiet_week_note(checked):
    """What section 5 says when nothing tripped a trigger.

    "None this week" plus a paragraph on what the escalation does NOT cover
    was the whole of section 5 on a quiet week: a limitation with nothing to
    limit. The sentence explaining that escalation is immediate and separate
    from this digest only appeared when a flag existed - so the protocol was
    invisible in precisely the weeks when nothing else stood in for it, and a
    reader could reasonably conclude nothing was watching.
    """
    triggers = "; ".join(TRIGGER_WORDS[r] for r in H.RED_FLAG_REASONS
                         if r in TRIGGER_WORDS)
    return (f"{plural(checked, 'mention')} checked against the triggers - "
            f"anything that {triggers}. None tripped one. A scan also runs daily "
            "between sweeps, so a flag does not wait for a Friday. When one is "
            "confirmed it is escalated the same day, directly to the four, and "
            "does not wait for this digest either; the names of individuals are "
            "held in the restricted escalation log, never in here.")


def same_day_note(platforms):
    """The channels where a red flag cannot surface until the weekly sweep.

    Section 5 promises immediate, same-day escalation, and the SLA columns
    measure it from the moment a flag is FOUND. Nothing measured how long it
    took to be found - and on the channels a person only opens on Friday, a
    complaint posted on Saturday waits six days before the clock even starts.
    The promise is real for the rest; saying which is which is the difference
    between a safeguard and an assurance.
    """
    names = [platforms.get(p, p.replace("_", " ").title()) for p in H.no_same_day_cover()]
    return sorted(names)


def channel_coverage(week_of, settings, platforms, swept):
    """(also_swept, not_swept) for the channels that carry no review count.

    "Swept this week: AmbitionBox, Glassdoor" is an inventory of what produced
    data, not a checklist of what was due. So a week where nobody opened
    YouTube read exactly like a week where it was checked and was empty - and
    at month 2 that difference is the whole question, because an empty channel
    is a finding and an unchecked one is not.
    """
    expected = H.unverified_channels(week_of, settings)
    checked = H.channels_checked(week_of)
    name = lambda p: platforms.get(p, p.replace("_", " ").title())  # noqa: E731
    also = [name(p) for p in expected if p in checked and name(p) not in swept]
    missing = [name(p) for p in expected if p not in checked and name(p) not in swept]
    return also, sorted(missing)


def missing_profiles(entities, platforms, absent=None, unrated=()):
    """'Robust Kommerce on AmbitionBox' for each page confirmed not to exist.

    Section 2 promises a rating line per entity per platform. Robust Kommerce
    has no AmbitionBox page, so its row is simply absent - and an absent row
    looks like a week with no movement, not like a platform that cannot see the
    company at all. Entities with no review page anywhere are left out here:
    they already get their own, stronger sentence.
    """
    named = set(unrated)
    pairs = H.absent_profiles() if absent is None else absent
    out = []
    for entity_id, platform_id in pairs:
        name = entities.get(entity_id)
        if not name or name in named:
            continue
        out.append(f"{name} on {platforms.get(platform_id, platform_id.title())}")
    return out


def source_link(mention):
    """(url, label) for a mention: its own link, or the page it came from.

    Most AmbitionBox reviews have no permalink, so the row carries no URL and
    the reader is handed a summary with nothing to check it against. Falling
    back to the review page is honest as long as the label says so - "page"
    rather than "link", because it lands on the listing, not the review.
    """
    own = (mention.get("url") or "").strip()
    if own:
        return own, "link"
    page = H.profile_url(mention.get("entity", ""), mention.get("platform", ""))
    return (page, "page") if page else ("", "")


# Week 1 is a sixty-day baseline, not seven days. It lives in hrintel because
# the digest is not the only thing that has to agree with it: the validator and
# the effort log each got this wrong independently before it was shared.
baseline_window = H.baseline_window
mentions_in = H.mentions_in


# --- broadsheet style -------------------------------------------------------
# A second HTML skin, modelled on the Westbury Intelligence house format:
# 600px shell (the email standard - Outlook handles it where 900px wraps
# badly), Georgia throughout, a numbered Brief above the sections, and news
# cards in place of a wide table for What's New.
#
# The six deliverables in docs/00-brief.md are unchanged and in the same
# order. This is a skin, not a restructure - the test that asserts all six
# appear, in order, in both bodies runs against this style too.

BS = {
    "paper": "#f2efe9", "card": "#ffffff", "ink": "#191714",
    "accent": "#8a2f2a", "muted": "#6b635a", "rule": "#d9d2c5",
    "faint": "#a89f92", "warn": "#8a6d3b",
}
SERIF = "Georgia,'Times New Roman',Times,serif"

def X(value) -> str:
    """Escape for HTML, stringifying first.

    E is html.escape, which wants a str; several row values are ints (counts,
    weeks). The plain style passes those through unescaped, which works but
    means the two styles disagree about which values are escaped. This makes
    it one rule.
    """
    return E("" if value is None else str(value))




def bs_kicker(text: str) -> str:
    return (f'<div style="font:400 10px/1 {SERIF};letter-spacing:.28em;'
            f'text-transform:uppercase;color:{BS["muted"]};">{text}</div>')


def bs_rule_head(text: str) -> str:
    """A section heading: small caps, accent colour, hard rule beneath."""
    return (f'<tr><td class="pad" style="background:{BS["card"]};padding:26px 40px 0 40px;">'
            f'<div style="font:400 11px/1 {SERIF};letter-spacing:.24em;'
            f'text-transform:uppercase;color:{BS["accent"]};'
            f'border-bottom:1px solid {BS["ink"]};padding-bottom:7px;">{text}</div>'
            '</td></tr>')


def bs_row(inner: str, pad: str = "18px 40px 4px 40px") -> str:
    return (f'<tr><td class="pad" style="background:{BS["card"]};padding:{pad};">'
            f'{inner}</td></tr>')


def bs_table(headers, rows, aligns, widths) -> str:
    """The same grid as the plain style, set in the broadsheet's type."""
    out = ['<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           'border="0" style="margin-top:6px;table-layout:fixed;border-collapse:collapse;">']
    out.append("<tr>")
    for head, align, width in zip(headers, aligns, widths):
        out.append(
            f'<th width="{width.rstrip("%")}" align="{align}" style="width:{width};'
            f'padding:7px 8px 7px 0;font:700 10px/1.3 {SERIF};letter-spacing:.1em;'
            f'text-transform:uppercase;color:{BS["muted"]};'
            f'border-bottom:1px solid {BS["ink"]};">{head}</th>')
    out.append("</tr>")
    for row in rows:
        out.append("<tr>")
        for cell, align in zip(row, aligns):
            out.append(
                f'<td align="{align}" style="padding:8px 8px 8px 0;'
                f'font:400 14px/1.5 {SERIF};color:{BS["ink"]};vertical-align:top;'
                f'border-bottom:1px solid {BS["rule"]};word-break:break-word;'
                f'overflow-wrap:anywhere;">{cell}</td>')
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def bs_note(text: str, *, warn: bool = False) -> str:
    colour = BS["warn"] if warn else BS["muted"]
    return (f'<div style="font:400 12px/1.6 {SERIF};color:{colour};'
            f'padding-top:8px;">{text}</div>')


def bs_card(title: str, url: str, detail: str, meta: str) -> str:
    """One mention, as a news card rather than a table row.

    Four items read far better as cards than as a seven-column table; forty
    would not, which is why the plain style keeps the grid.
    """
    head = (f'<a href="{url}" style="font:400 19px/1.32 {SERIF};'
            f'color:{BS["ink"]};">{title}</a>' if url else
            f'<div style="font:400 19px/1.32 {SERIF};color:{BS["ink"]};">{title}</div>')
    more = (f'<a href="{url}" style="font:400 11px/1 {SERIF};letter-spacing:.14em;'
            f'text-transform:uppercase;color:{BS["accent"]};display:inline-block;'
            'padding-top:8px;">Read more &rarr;</a>') if url else ""
    return (f'<div style="padding:0 0 16px 0;">'
            f'<div style="font:700 11px/1 {SERIF};letter-spacing:.12em;'
            f'text-transform:uppercase;color:{BS["muted"]};padding-bottom:8px;">{meta}</div>'
            f'{head}'
            f'<div style="font:400 14px/1.62 {SERIF};color:{BS["muted"]};'
            f'padding-top:6px;">{detail}</div>{more}</div>')


def bs_quiet(rows) -> str:
    """'Quiet this week — last known', the pattern worth borrowing.

    An entity with nothing this week still appears, with the last thing
    recorded about it and when. A blank row says 'nothing found'; this says
    'nothing found, and here is how long that has been true' - which for a
    group averaging one mention every three weeks is the more useful fact,
    and the one a reader would otherwise mistake for a gap in the sweep.
    """
    if not rows:
        return ""
    out = [f'<div style="border-top:1px solid {BS["rule"]};padding-top:10px;'
           f'font:400 10px/1 {SERIF};letter-spacing:.22em;text-transform:uppercase;'
           f'color:{BS["muted"]};">Quiet this week &mdash; last known</div>',
           '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           'border="0" style="margin-top:4px;table-layout:fixed;">']
    for name, text, when in rows:
        dated = (f'<span style="font-style:normal;font-size:10px;letter-spacing:.1em;'
                 f'color:{BS["faint"]};">&nbsp;{when}</span>') if when else ""
        out.append(
            f'<tr><td width="146" valign="top" style="width:146px;padding:6px 12px 6px 0;'
            f'font:700 11px/1.4 {SERIF};letter-spacing:.06em;text-transform:uppercase;'
            f'color:{BS["muted"]};">{name}</td>'
            f'<td valign="top" style="padding:6px 0;font:italic 400 13px/1.5 {SERIF};'
            f'color:{BS["muted"]};">{text}{dated}</td></tr>')
    out.append("</table>")
    return "".join(out)


def last_known(entity_id, entity_name, all_mentions, week_of):
    """(name, summary, '12 Aug') for an entity's most recent mention before this week."""
    earlier = [m for m in all_mentions
               if m.get("entity") == entity_id
               and (m.get("status") or "") != "out_of_scope"
               and (m.get("post_date") or "") < week_of.isoformat()]
    if not earlier:
        return (entity_name, "Nothing on record.", "")
    latest = max(earlier, key=lambda m: m.get("post_date", ""))
    said = (latest.get("one_line_summary") or latest.get("title_or_snippet") or "").strip()
    when = H.parse_date(latest.get("post_date", ""))
    return (entity_name, said or "Recorded, no summary.",
            H.day_month(when) if when else "")


def brief_lines(stats, heads, ratings, flags, market_note):
    """The numbered Brief: what a reader needs before any table.

    Three facts, in the order they would change a decision: whether anything
    was said, whether any rating moved, whether anything escalated. Derived,
    never written by hand, so it cannot drift from the sections below it.
    """
    lines = []
    total = stats["total"]
    group = next((r for r in heads if r.get("is_total")), None)
    net = group.get("net", "—") if group else "—"
    lines.append(f"{plural(total, 'mention')} across the four entities"
                 + (f", group net sentiment {net}" if total else
                    " — a quiet week, not an unswept one"))

    moved = [r for r in ratings
             if r.get("rating_delta") not in (None, "", "n/a", "—", "no change")]
    lines.append(f"{plural(len(moved), 'rating')} moved on Glassdoor or AmbitionBox"
                 if moved else
                 "No Glassdoor or AmbitionBox rating moved this week")

    lines.append(f"{plural(len(flags), 'red flag')} raised — see section 5"
                 if flags else
                 "No red flags: nothing named an individual, alleged harassment or "
                 "non-payment, or gathered public traction")
    return lines


def broadsheet_html(*, week_label, baseline, partial_notice, stats, heads, ratings,
                    now, themes, rolling, rolling_total, rolling_weeks, flags,
                    entities, all_mentions, week_of, swept_line, no_page_note,
                    unrated_note, company_note, untagged_note, quiet_note,
                    same_day, data_link, holdings_note, scope_note, trial_note,
                    date_band) -> str:
    """The six deliverables, set as a broadsheet. Structure is unchanged."""
    p = []
    p.append(
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,'
        'initial-scale=1"><style>a{text-decoration:none;}'
        '@media only screen and (max-width:620px){.shell{width:100%!important;}'
        '.pad{padding-left:18px!important;padding-right:18px!important;}'
        '.h1{font-size:24px!important;}}</style>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:0;padding:0;background:{BS["paper"]};">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" class="shell" width="600" cellpadding="0" '
        'cellspacing="0" border="0" style="width:600px;max-width:100%;">'
    )

    # Masthead
    p.append(
        f'<tr><td class="pad" align="center" style="background:{BS["card"]};'
        f'padding:34px 40px 18px 40px;border-top:3px solid {BS["ink"]};">'
        f'<div style="font:400 10px/1 {SERIF};letter-spacing:.34em;'
        f'text-transform:uppercase;color:{BS["accent"]};">'
        'Employer reputation &middot; four entities &middot; public sources</div>'
        f'<div class="h1" style="font:400 33px/1.12 {SERIF};color:{BS["ink"]};'
        'padding:12px 0 10px 0;letter-spacing:-.01em;">HR Intelligence Digest</div>'
        f'<div style="border-top:1px solid {BS["rule"]};border-bottom:3px double '
        f'{BS["rule"]};padding:8px 0;font:400 11px/1 {SERIF};letter-spacing:.16em;'
        f'text-transform:uppercase;color:{BS["muted"]};">{date_band}</div>'
        '</td></tr>'
    )

    if partial_notice:
        p.append(bs_row(
            f'<div style="font:400 13px/1.6 {SERIF};color:{BS["warn"]};'
            f'border-left:3px solid {BS["warn"]};padding-left:12px;">{partial_notice}</div>',
            pad="18px 40px 0 40px"))

    # The Brief
    brief = brief_lines(stats, heads, ratings, flags, None)
    rows = "".join(
        f'<tr><td width="34" valign="top" style="padding:9px 0;font:400 15px/1.4 '
        f'{SERIF};color:{BS["accent"]};">{i:02d}</td>'
        f'<td valign="top" style="padding:9px 0;font:400 15px/1.55 {SERIF};'
        f'color:{BS["ink"]};border-bottom:1px solid {BS["rule"]};">{X(line)}</td></tr>'
        for i, line in enumerate(brief, 1))
    p.append(bs_row(bs_kicker("The Brief") +
                    f'<table role="presentation" width="100%" cellpadding="0" '
                    f'cellspacing="0" border="0" style="margin-top:4px;">{rows}</table>',
                    pad="20px 40px 8px 40px"))

    # 1 Headline
    p.append(bs_rule_head("1 &middot; Headline"))
    p.append(bs_row(bs_table(
        ["Entity", "Mentions", "vs last wk", "Net sentiment", "vs last wk"],
        [[(f'<strong>{X(r["entity"])}</strong>' if r["is_total"] else X(r["entity"])),
          (f'<strong>{r["count"]}</strong>' if r["is_total"] else r["count"]),
          X(r["count_delta"]), X(r["net"]), X(r["net_delta"])] for r in heads],
        ["left", "right", "right", "right", "right"],
        ["32%", "15%", "18%", "18%", "17%"])
        + (bs_note(company_note) if company_note else "")
        + (bs_note(untagged_note, warn=True) if untagged_note else "")))

    # 2 Rating Movement
    p.append(bs_rule_head("2 &middot; Rating Movement"))
    p.append(bs_row(bs_table(
        ["Entity", "Platform", "Rating", "Change", "Reviews", "New", "Recommend"],
        [[X(r["entity"]), X(r["platform"]), X(r["rating"]), X(r["rating_delta"]),
          X(r["reviews"]), X(r["reviews_delta"]), X(r["recommend"])] for r in ratings],
        ["left", "left", "right", "right", "right", "right", "right"],
        ["23%", "15%", "11%", "14%", "11%", "12%", "14%"])
        + (bs_note(no_page_note) if no_page_note else "")
        + (bs_note(unrated_note) if unrated_note else "")))

    # 3 What's New
    p.append(bs_rule_head("3 &middot; What&#x27;s New"))
    if now:
        cards = "".join(
            bs_card(
                X((m.get("one_line_summary") or m.get("title_or_snippet")
                   or "(no summary)").strip()),
                source_link(m),
                " &middot; ".join(filter(None, [
                    f'{stars_text(m)} stars' if stars_text(m) != "—" else "",
                    author_text(m), sentiment_label(m)])),
                f'{X(entities.get(m.get("entity"), m.get("entity")))} '
                f'&middot; {X(H.platform_names().get(m.get("platform"), m.get("platform")))} '
                f'&middot; {X(m.get("post_date", ""))}')
            for m in now)
        p.append(bs_row(cards))
    else:
        p.append(bs_row(f'<div style="font:400 15px/1.6 {SERIF};color:{BS["ink"]};">'
                        'Nothing new on any channel this week.</div>'))

    # Quiet this week - last known
    silent = [last_known(eid, name, all_mentions, week_of)
              for eid, name in entities.items()
              if not any(m.get("entity") == eid for m in now)]
    if silent:
        p.append(bs_row(bs_quiet(silent), pad="8px 40px 4px 40px"))
    p.append(bs_row(bs_note(swept_line), pad="4px 40px 8px 40px"))

    # 4 Themes
    p.append(bs_rule_head("4 &middot; Themes"))
    if themes:
        items = "".join(
            f'<div style="padding:0 0 10px 0;">'
            f'<span style="font:700 12px/1.4 {SERIF};letter-spacing:.08em;'
            f'text-transform:uppercase;color:{BS["ink"]};">{X(r["theme"])}</span>'
            f'<span style="font:400 13px/1.5 {SERIF};color:{BS["muted"]};"> &mdash; '
            f'{X(plural(r["count"], "mention"))}, {X(r["lean"])}, net {X(r["net"])}'
            f'{"" if r["recurring"] else ", single mention &mdash; not yet a pattern"}'
            f'</span>'
            f'<div style="font:italic 400 13px/1.55 {SERIF};color:{BS["muted"]};'
            f'padding-top:3px;">{X(r.get("example", ""))}</div></div>'
            for r in themes)
        p.append(bs_row(items))
    else:
        p.append(bs_row(f'<div style="font:400 15px/1.6 {SERIF};color:{BS["ink"]};">'
                        'No themes yet — too few mentions to show a pattern.</div>'))
    if rolling:
        roll = "".join(
            f'<div style="font:400 13px/1.6 {SERIF};color:{BS["muted"]};">'
            f'{X(r["theme"])} &mdash; {X(plural(r["count"], "mention"))} across '
            f'{X(plural(r["weeks"], "week"))}, {X(r["lean"])}, net {X(r["net"])}</div>'
            for r in rolling)
        p.append(bs_row(
            f'<div style="border-top:1px solid {BS["rule"]};padding-top:10px;'
            f'font:400 10px/1 {SERIF};letter-spacing:.22em;text-transform:uppercase;'
            f'color:{BS["muted"]};">Recurring across the last '
            f'{rolling_weeks} weeks ({plural(rolling_total, "mention")})</div>' + roll,
            pad="4px 40px 8px 40px"))

    # 5 Red Flags
    p.append(bs_rule_head("5 &middot; Red Flags"))
    if flags:
        rows5 = "".join(
            f'<div style="padding:0 0 12px 0;border-left:3px solid {BS["accent"]};'
            f'padding-left:12px;">'
            f'<div style="font:700 11px/1.4 {SERIF};letter-spacing:.1em;'
            f'text-transform:uppercase;color:{BS["accent"]};">{X(r["reason"])}</div>'
            f'<div style="font:400 15px/1.5 {SERIF};color:{BS["ink"]};padding-top:4px;">'
            f'{X(r["summary"])}</div>'
            f'<div style="font:400 12px/1.5 {SERIF};color:{BS["muted"]};padding-top:3px;">'
            f'{X(r["entity"])} &middot; {X(r["platform"])} &middot; {X(r["raised"])} '
            f'&middot; {X(r["status"])}</div></div>'
            for r in flags)
        p.append(bs_row(rows5))
    else:
        p.append(bs_row(
            f'<div style="font:400 15px/1.5 {SERIF};color:{BS["ink"]};">'
            '<strong>None this week.</strong></div>' + bs_note(quiet_note)))
    if same_day:
        p.append(bs_row(bs_note(same_day, warn=True), pad="0 40px 8px 40px"))

    # 6 Data Link
    p.append(bs_rule_head("6 &middot; Data Link"))
    p.append(bs_row(
        f'<div style="font:400 15px/1.6 {SERIF};color:{BS["ink"]};">'
        f'<a href="{data_link}" style="color:{BS["accent"]};border-bottom:1px solid '
        f'{BS["rule"]};">Open the tracking sheet</a></div>' + bs_note(holdings_note),
        pad="18px 40px 8px 40px"))

    # Colophon
    p.append(
        f'<tr><td class="pad" align="center" style="background:{BS["card"]};'
        f'padding:26px 40px 34px 40px;border-bottom:3px solid {BS["ink"]};">'
        f'<div style="border-top:1px solid {BS["rule"]};padding-top:16px;'
        f'font:400 11px/1.7 {SERIF};color:{BS["muted"]};text-align:left;">{scope_note}'
        f'<br><br>{trial_note}</div>'
        f'<div style="padding-top:14px;font:400 10px/1.7 {SERIF};letter-spacing:.16em;'
        f'text-transform:uppercase;color:{BS["muted"]};">'
        f'HR Intelligence Digest | {date_band} | Confidential</div></td></tr>'
    )
    p.append("</table></td></tr></table>")
    return "".join(p)


def build(week_of: dt.date, settings: dict, style: str = "") -> tuple[str, str, str, dict]:
    digest_cfg = settings.get("digest", {})
    entities = H.entity_names()
    platforms = H.platform_names()
    max_themes = int(digest_cfg.get("max_themes", 4))
    summary_max = int(digest_cfg.get("summary_max_chars", 160))

    all_mentions = H.read_csv(H.MENTIONS_CSV)
    all_ratings = H.read_csv(H.RATINGS_CSV)
    escalations = H.read_csv(H.ESCALATIONS_CSV)

    prev_week = week_of - dt.timedelta(days=7)
    baseline = baseline_window(week_of, settings)
    if baseline:
        first, last, baseline_days = baseline
        now = [m for m in mentions_in(all_mentions, first, last)
               if (m.get("status") or "") != "out_of_scope"]
        # Nothing precedes a baseline, so there is no previous period to
        # compare against and every "vs last week" column reads n/a.
        prev = []
    else:
        baseline_days = 0
        now = [m for m in H.mentions_for_week(all_mentions, week_of)
               if (m.get("status") or "") != "out_of_scope"]
        prev = [m for m in H.mentions_for_week(all_mentions, prev_week)
                if (m.get("status") or "") != "out_of_scope"]

    heads = headline_rows(now, prev, entities, comparable=not baseline)
    ratings = rating_rows(all_ratings, week_of, entities, platforms)
    themes = theme_rows(now, max_themes)
    flags = red_flag_rows(now, escalations, entities, platforms)
    unrated = unrated_entities(entities)
    no_page = missing_profiles(entities, platforms, unrated=unrated)
    trial_start = H.parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    is_baseline = bool(trial_start) and H.week_start_of(trial_start) == week_of
    swept, gaps = coverage_rows(now, all_ratings, week_of, entities, platforms,
                                baseline=is_baseline)
    also_swept, not_swept = channel_coverage(week_of, settings, platforms, swept)
    lagging = same_day_note(platforms)
    swept = sorted(set(swept) | set(also_swept))
    rolling_weeks = int(digest_cfg.get("rolling_theme_weeks", 4))
    rolling, rolling_total = rolling_theme_rows(all_mentions, week_of, rolling_weeks, max_themes)

    total = len(now)
    total_prev = len(prev)
    net_now = H.net_sentiment(now)
    net_prev = H.net_sentiment(prev)
    untagged = len(H.untagged_rows(now))
    company_posts = sum(1 for m in now if H.is_company_voice(m))
    data_link = digest_cfg.get("data_link", "")
    holdings = sheet_contents(now, all_ratings, flags, week_of)
    compare = "n/a" if baseline else None

    def vs_previous(value, previous, digits=0):
        """The 'vs previous week' figure, or n/a when nothing precedes it."""
        return compare or delta_text(value, previous, digits=digits)

    week_label = H.fmt_week(week_of)
    if baseline:
        # Say what the period actually is. "Week of 19-25 Sep" over sixty days
        # of findings would misdate every row in section 3.
        week_label = (f"{baseline_days}-day baseline, {H.day_month(baseline[0])} to "
                      f"{H.day_month(baseline[1], year=True)}")

    # A week built before it has ended covers fewer than seven days. Say so:
    # three days read as seven would understate the week and distort every
    # week-on-week comparison drawn from it.
    today = dt.date.today()
    week_end = week_of + dt.timedelta(days=6)
    days_elapsed = min(7, max(0, (today - week_of).days + 1)) if today <= week_end else 7
    partial = days_elapsed < 7

    stats = {
        "partial": partial,
        "days_elapsed": days_elapsed,
        "total": total,
        "total_prev": total_prev,
        "untagged": untagged,
        "company_posts": company_posts,
        "red_flags": len(flags),
        "week_label": week_label,
        "baseline": bool(baseline),
        "week_end": week_end,
        "coverage_gaps": len(gaps),
        "coverage_detail": gaps,
        "rolling_themes": len(rolling),
    }

    # ---------- HTML ----------
    h: list[str] = []
    h.append(
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'color:#1f2933;max-width:900px;line-height:1.5;">'
    )
    h.append('<h2 style="margin:0 0 4px;font-size:20px;">HR Intelligence Digest</h2>')
    h.append(
        f'<p style="margin:0 0 16px;color:#52606d;font-size:13px;">{"" if baseline else "Week of "}{E(week_label)} '
        f'· {E(plural(total, "mention"))} '
        f'({vs_previous(total, total_prev)} vs previous week) '
        f'· net sentiment {E(sentiment_text(net_now))} '
        f'({E(delta_text(net_now, net_prev, digits=2))})</p>'
    )

    if partial:
        notice = (
            (f'<strong>Baseline still open</strong> \u2014 complete to '
             f'{H.day_month(today)}. It closes {H.day_month(week_end)}; anything posted '
             'between now and then is not in here yet.')
            if baseline else
            (f'<strong>Partial week</strong> \u2014 covers {days_elapsed} of 7 days, to '
             f'{H.day_month(today)}. The week closes {H.day_month(week_end)}; counts and '
             'comparisons here are incomplete.')
        )
        h.append(
            '<p style="margin:0 0 16px;padding:8px 10px;background:#FBF0D9;border-radius:4px;'
            f'font-size:13px;color:#8a6d3b;">{notice}</p>'
        )

    # 1. Headline
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">1 · Headline</h3>')
    if total == 0 and total_prev == 0:
        h.append('<p style="margin:0 0 8px;">No mentions recorded this week or last. '
                 'Low volume is expected for the smaller entities.</p>')
    h.append(h_table(
        ["Entity", "Mentions", "vs last week", "Net sentiment", "vs last week"],
        [[(f"<strong>{E(r['entity'])}</strong>" if r["is_total"] else E(r["entity"])),
          (f"<strong>{r['count']}</strong>" if r["is_total"] else r["count"]),
          E(r["count_delta"]), E(r["net"]), E(r["net_delta"])]
         for r in heads],
        ["left", "right", "right", "right", "right"],
        ["32%", "15%", "18%", "18%", "17%"],
    ))
    if untagged:
        h.append(
            f'<p style="margin:0 0 8px;color:#8a6d3b;font-size:13px;">{plural(untagged, "mention")} '
            'not yet sentiment-tagged, excluded from the net sentiment figures.</p>'
        )
    if company_posts:
        # Without this line a company post is invisible twice over: it moves no
        # sentiment figure, and the mention count it does move looks like
        # somebody talking about the group. Saying which is which is the point.
        h.append(
            f'<p style="margin:0 0 8px;color:#666;font-size:13px;">'
            f'{plural(company_posts, "item")} above {"is" if company_posts == 1 else "are"} '
            'company page activity — the employer posting about itself. Counted as coverage, '
            'excluded from net sentiment: the group does not score itself.</p>'
        )

    # 2. Rating movement
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">2 · Rating Movement</h3>')
    if ratings:
        h.append(h_table(
            ["Entity", "Platform", "Rating", "Change", "Reviews", "New", "Recommend"],
            [[E(r["entity"]), E(r["platform"]), E(r["rating"]), E(r["rating_delta"]),
              r["reviews"], E(r["reviews_delta"]), E(r["recommend"])] for r in ratings],
            ["left", "left", "right", "right", "right", "right", "right"],
            ["23%", "15%", "11%", "14%", "11%", "12%", "14%"],
        ))
    else:
        h.append('<p style="margin:0 0 8px;">No rating snapshot recorded for this week. '
                 'Glassdoor and AmbitionBox scores are captured on the manual sweep.</p>')
    if no_page:
        h.append('<p style="margin:0 0 8px;font-size:12px;color:#52606d;">'
                 f'No page exists for <strong>{E("; ".join(no_page))}</strong>, so '
                 f'{"that line" if len(no_page) == 1 else "those lines"} can never appear '
                 'above. The other review site is the only one covering '
                 f'{"it" if len(no_page) == 1 else "them"}.</p>')
    if unrated:
        h.append('<p style="margin:0 0 8px;font-size:12px;color:#52606d;">'
                 f'<strong>{E(", ".join(unrated))}</strong> '
                 f'{"has" if len(unrated) == 1 else "have"} no Glassdoor or AmbitionBox page, '
                 f'so {"it" if len(unrated) == 1 else "they"} cannot appear above. '
                 f'{"It is" if len(unrated) == 1 else "They are"} covered by LinkedIn, Reddit, '
                 'news and X only — absence here is not evidence of a quiet week.</p>')

    # 3. What's new
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">3 · What\'s New</h3>')
    if now:
        rows = []
        for m in sorted(now, key=lambda x: (x.get("post_date") or "", x.get("entity") or "")):
            link, label = source_link(m)
            summary = truncate(m.get("one_line_summary") or m.get("title_or_snippet", ""), summary_max)
            cell = E(summary)
            if link:
                cell += f' <a href="{E(link)}" style="color:#2b6cb0;">{label}</a>'
            rows.append([
                E(entities.get(m.get("entity"), m.get("entity", ""))),
                E(platforms.get(m.get("platform"), m.get("platform", ""))),
                E(m.get("post_date") or m.get("captured_at", "")),
                E(stars_text(m)),
                E(author_text(m)),
                E(sentiment_label(m)),
                cell,
            ])
        # The summary is still the column people read; the rest is context for it.
        h.append(h_table(
            ["Entity", "Platform", "Date", "Stars", "Who", "Sentiment", "Summary"], rows,
            ["left", "left", "left", "right", "left", "left", "left"],
            ["14%", "10%", "9%", "6%", "13%", "11%", "37%"]))
    else:
        h.append('<p style="margin:0 0 8px;">No new reviews or posts this week.</p>')

    if swept:
        h.append(f'<p style="margin:0 0 4px;font-size:12px;color:#52606d;">Swept this week: '
                 f'{E(", ".join(swept))}.</p>')
    if not_swept:
        h.append('<p style="margin:0 0 8px;font-size:12px;color:#8a6d3b;">'
                 f'<strong>Not swept this week: {E(", ".join(not_swept))}.</strong> '
                 'Nothing was found there because nobody looked — not because '
                 'there was nothing to find.</p>')

    # 4. Themes
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">4 · Themes</h3>')
    if themes:
        h.append("<ul style='margin:0 0 8px;padding-left:20px;'>")
        for r in themes:
            example = f' <span style="color:#52606d;">— {E(truncate(r["example"], 120))}</span>' if r["example"] else ""
            note = "" if r["recurring"] else ", single mention — not yet a pattern"
            h.append(
                f'<li style="margin:0 0 6px;"><strong>{E(r["theme"])}</strong> '
                f'({E(plural(r["count"], "mention"))}, {E(r["lean"])}, '
                f'net {E(r["net"])}{E(note)}){example}</li>'
            )
        h.append("</ul>")
    else:
        h.append('<p style="margin:0 0 8px;">Not enough tagged mentions this week to identify '
                 'recurring themes.</p>')

    if rolling:
        h.append(f'<p style="margin:10px 0 4px;font-size:13px;"><strong>Recurring across the '
                 f'last {rolling_weeks} weeks</strong> ({rolling_total} mentions):</p>')
        h.append("<ul style='margin:0 0 8px;padding-left:20px;font-size:13px;'>")
        for r in rolling:
            h.append(f'<li style="margin:0 0 4px;">{E(r["theme"])} \u2014 '
                     f'{E(plural(r["count"], "mention"))} across {r["weeks"]} weeks, '
                     f'{E(r["lean"])}, net {E(r["net"])}</li>')
        h.append("</ul>")
    elif rolling_total:
        h.append(f'<p style="margin:0 0 8px;font-size:12px;color:#52606d;">No theme has '
                 f'appeared in more than one of the last {rolling_weeks} weeks yet.</p>')

    # 5. Red flags
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">5 · Red Flags</h3>')
    if flags:
        late = [r for r in flags if not r["on_time"]]
        if late:
            banner = "background:#fdecea;border-left:4px solid #a12622;"
            verdict = (f'<strong style="color:#a12622;">{plural(len(late), "item")} did not go '
                       'out the same day it was found.</strong>')
        else:
            banner = "background:#eaf5ec;border-left:4px solid #1e7a3c;"
            verdict = ('<strong style="color:#1e7a3c;">All escalated the same day they were '
                       'found.</strong>')
        h.append(
            f'<div style="{banner}padding:8px 10px;margin:0 0 8px;font-size:13px;">'
            f'<strong>{plural(len(flags), "item")} escalated this week.</strong> {verdict}<br>'
            '<span style="font-size:12px;color:#52606d;">Escalation is immediate and does not '
            'wait for this digest; the rows below are the record of what was already sent. '
            'Names of individuals are held in the restricted escalation log, not in this '
            'email.</span></div>'
        )
        h.append(h_table(
            ["ID", "Entity", "Platform", "Found", "Trigger", "Alerted", "Detail"],
            [[E(r["mention_id"]), E(r["entity"]), E(r["platform"]),
              (f'{E(r["raised"])}<br><span style="font-size:11px;color:#52606d;">'
               f'posted {E(r["date"])}</span>'),
              (f'{E(r["reason"])}<br><span style="font-size:11px;color:#52606d;">'
               f'{E(r["severity"])} · {E(r["status"])}</span>'),
              alert_cell(r),
              (E(truncate(r["summary"], 110)) +
               (f' <a href="{E(r["url"])}" style="color:#2b6cb0;">link</a>' if r["url"] else ""))]
             for r in flags],
            widths=["12%", "13%", "10%", "10%", "14%", "16%", "25%"],
        ))
    else:
        h.append('<p style="margin:0 0 4px;"><strong>None this week.</strong></p>')
        h.append('<p style="margin:0 0 8px;font-size:12px;color:#52606d;">'
                 f'{E(quiet_week_note(len(now)))}</p>')
    if lagging:
        h.append('<p style="margin:0 0 8px;font-size:12px;color:#8a6d3b;">'
                 'Same-day escalation covers the channels checked daily. '
                 f'<strong>{E(", ".join(lagging))}</strong> '
                 f'{"is" if len(lagging) == 1 else "are"} only read on the weekly sweep, '
                 'so something posted there can be up to a week old before it is seen. '
                 'The platforms block automated checking, so this is a limit of the '
                 'sources, not of the process.</p>')

    # 6. Data link
    # The brief names this deliverable "Data Link", not "Data". A reader
    # checking the email against the six deliverables should find the same
    # six words.
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">6 · Data Link</h3>')
    if data_link and not H.is_todo(data_link):
        h.append(f'<p style="margin:0 0 8px;"><a href="{E(data_link)}" style="color:#2b6cb0;">'
                 f'Open the tracking sheet</a> — {E(holdings)}</p>')
    else:
        h.append('<p style="margin:0 0 8px;color:#a12622;">Tracking sheet link not set — '
                 'add <code>digest.data_link</code> in config/settings.yaml.</p>')

    h.append('<hr style="border:none;border-top:1px solid #e3e6ea;margin:20px 0 12px;">')
    h.append(f'<p style="font-size:12px;color:#52606d;margin:0 0 6px;">{E(BOUNDARY_NOTE)}</p>')
    h.append(f'<p style="font-size:12px;color:#52606d;margin:0;">{E(TRIAL_NOTE)}</p>')
    h.append("</div>")

    # ---------- plain text ----------
    t: list[str] = []
    t.append("HR INTELLIGENCE DIGEST")
    t.append(week_label if baseline else f"Week of {week_label}")
    t.append(
        f"{plural(total, 'mention')} ({vs_previous(total, total_prev)} vs previous week) · "
        f"net sentiment {sentiment_text(net_now)} "
        f"({vs_previous(net_now, net_prev, digits=2)} vs previous week)"
    )
    if partial and baseline:
        t.append(f"BASELINE STILL OPEN - complete to {H.day_month(today)}. It closes "
                 f"{H.day_month(week_end)}; anything posted between now and then is "
                 "not in here yet.")
    elif partial:
        t.append(f"PARTIAL WEEK - covers {days_elapsed} of 7 days, to "
                 f"{H.day_month(today)}. The week closes {H.day_month(week_end)}; "
                 "counts and comparisons here are incomplete.")
    t.append("")
    t.append("1. HEADLINE")
    head_rows = [[r["entity"], r["count"], r["count_delta"], r["net"], r["net_delta"]]
                 for r in heads]
    table = t_table(
        ["Entity", "Mentions", "vs last wk", "Net sentiment", "vs last wk"], head_rows
    ).splitlines()
    # Separator before the total line.
    table.insert(len(table) - 1, table[1])
    t.append("\n".join(table))
    if untagged:
        t.append(f"Note: {plural(untagged, 'mention')} untagged; excluded from net sentiment.")
    if company_posts:
        t.append(f"Note: {plural(company_posts, 'item')} company page activity "
                 "(the employer posting about itself); counted as coverage, "
                 "excluded from net sentiment.")
    t.append("")
    t.append("2. RATING MOVEMENT")
    t.append(t_table(
        ["Entity", "Platform", "Rating", "Change", "Reviews", "New", "Recommend"],
        [[r["entity"], r["platform"], r["rating"], r["rating_delta"], r["reviews"],
          r["reviews_delta"], r["recommend"]] for r in ratings],
    ) if ratings else "No rating snapshot recorded for this week.")
    if no_page:
        t.append("")
        t.append(f"No page exists for {'; '.join(no_page)}, so "
                 f"{'that line' if len(no_page) == 1 else 'those lines'} can never appear "
                 "above. The other review site is the only one covering "
                 f"{'it' if len(no_page) == 1 else 'them'}.")
    if unrated:
        t.append("")
        t.append(f"{', '.join(unrated)} {'has' if len(unrated) == 1 else 'have'} no Glassdoor "
                 f"or AmbitionBox page, so {'it' if len(unrated) == 1 else 'they'} cannot "
                 f"appear above. {'It is' if len(unrated) == 1 else 'They are'} covered by "
                 "LinkedIn, Reddit, news and X only - absence here is not evidence of a "
                 "quiet week.")
    t.append("")
    t.append("3. WHAT'S NEW")
    if now:
        for m in sorted(now, key=lambda x: (x.get("post_date") or "", x.get("entity") or "")):
            t.append(
                f"- [{entities.get(m.get('entity'), m.get('entity',''))} / "
                f"{platforms.get(m.get('platform'), m.get('platform',''))} / "
                f"{m.get('post_date') or m.get('captured_at','')} / "
                f"{stars_text(m)} / {author_text(m)} / "
                f"{sentiment_label(m)}] "
                f"{truncate(m.get('one_line_summary') or m.get('title_or_snippet',''), summary_max)}"
            )
            link, label = source_link(m)
            if link:
                t.append(f"  {link}" + ("   (page, not the review itself)"
                                        if label == "page" else ""))
    else:
        t.append("No new reviews or posts this week.")
    if swept:
        t.append("")
        t.append(f"Swept this week: {', '.join(swept)}.")
    if not_swept:
        t.append("")
        t.append(f"NOT swept this week: {', '.join(not_swept)}. Nothing was found there "
                 "because nobody looked - not because there was nothing to find.")
    t.append("")
    t.append("4. THEMES")
    if themes:
        for r in themes:
            note = "" if r["recurring"] else ", single mention - not yet a pattern"
            line = (f"- {r['theme']} ({plural(r['count'], 'mention')}, {r['lean']}, "
                    f"net {r['net']}{note})")
            if r["example"]:
                line += f" — {truncate(r['example'], 120)}"
            t.append(line)
    else:
        t.append("Not enough tagged mentions this week to identify recurring themes.")
    if rolling:
        t.append("")
        t.append(f"Recurring across the last {rolling_weeks} weeks ({rolling_total} mentions):")
        for r in rolling:
            t.append(f"- {r['theme']} \u2014 {plural(r['count'], 'mention')} across "
                     f"{r['weeks']} weeks, {r['lean']}, net {r['net']}")
    elif rolling_total:
        t.append(f"No theme has appeared in more than one of the last {rolling_weeks} weeks yet.")
    t.append("")
    t.append("5. RED FLAGS")
    if flags:
        late = [r for r in flags if not r["on_time"]]
        verdict = (f"{plural(len(late), 'item')} did not go out the same day it was found."
                   if late else "All escalated the same day they were found.")
        t.append(f"{plural(len(flags), 'item')} escalated this week. {verdict}")
        t.append("Escalation is immediate and does not wait for this digest; the rows below are "
                 "the record of what was already sent. Names of individuals are held in the "
                 "restricted escalation log, not here.")
        for r in flags:
            t.append(f"- {r['mention_id']} [{r['entity']} / {r['platform']} / "
                     f"posted {r['date']}]")
            t.append(f"  {r['reason']} · {r['severity']} · status {r['status']}")
            if r["notified"]:
                line = f"  Found {r['raised']} → alerted {r['notified']} ({r['timing']})"
                if r["notified_to"]:
                    line += f" to {truncate(r['notified_to'], 60)}"
            else:
                line = f"  Found {r['raised']} → NOT YET SENT - escalate now"
            t.append(line)
            t.append(f"  {truncate(r['summary'], 120)}")
            if r["url"]:
                t.append(f"  {r['url']}")
    else:
        t.append("None this week.")
        t.append(quiet_week_note(len(now)))
    if lagging:
        t.append("")
        t.append(f"Same-day escalation covers the channels checked daily. "
                 f"{', '.join(lagging)} {'is' if len(lagging) == 1 else 'are'} only read on "
                 "the weekly sweep, so something posted there can be up to a week old "
                 "before it is seen. The platforms block automated checking, so this is a "
                 "limit of the sources, not of the process.")
    t.append("")
    t.append("6. DATA LINK")
    if data_link and not H.is_todo(data_link):
        t.append(data_link)
        t.append(holdings)
    else:
        t.append("Tracking sheet link not set — add digest.data_link in config/settings.yaml.")
    t.append("")
    t.append("-" * 72)
    t.append(BOUNDARY_NOTE)
    t.append("")
    t.append(TRIAL_NOTE)

    subject_template = digest_cfg.get(
        "subject_template", "HR Intelligence Digest — week of {week_of} ({mention_count} mentions)"
    )
    if baseline:
        # The template says "week of {week_of}", which over a sixty-day
        # baseline reads "week of 60-day baseline, 28 Jul to 25 Sep".
        subject = (f"HR Intelligence Digest \u2014 {week_label} "
                   f"({plural(total, 'mention')})")
    else:
        subject = subject_template.format(
            week_of=week_label, mention_count=total, red_flags=len(flags),
        )
    if partial:
        subject += (f" \u00b7 IN PROGRESS, closes {H.day_month(week_end)}" if baseline
                    else f" \u00b7 PARTIAL ({days_elapsed}/7 days)")
    if flags:
        subject += f" · {len(flags)} red flag{'s' if len(flags) != 1 else ''}"

    if style == "broadsheet":
        # The same computed rows, set as a broadsheet. Notes are rebuilt as
        # plain sentences here rather than reusing the plain style's inline
        # markup, which carries its own colours and margins.
        swept_line = ("Swept this week: "
                      + ", ".join(H.platform_names().get(p, p) for p in swept) + ".")
        if not_swept:
            swept_line += (" NOT swept: "
                           + ", ".join(H.platform_names().get(p, p) for p in not_swept)
                           + ". Nothing was found there because nobody looked.")
        broadsheet = broadsheet_html(
            week_label=week_label,
            baseline=bool(baseline),
            partial_notice=(notice if partial else ""),
            stats=stats, heads=heads, ratings=ratings, now=now,
            themes=themes, rolling=rolling, rolling_total=rolling_total,
            rolling_weeks=rolling_weeks, flags=flags, entities=entities,
            all_mentions=all_mentions, week_of=week_of,
            swept_line=swept_line,
            no_page_note=(
                f"No page exists for {', '.join(no_page)}, so "
                f"{'that line' if len(no_page) == 1 else 'those lines'} can never "
                "appear above. The other review site is the only one covering "
                f"{'it' if len(no_page) == 1 else 'them'}." if no_page else ""),
            unrated_note=(
                f"{', '.join(unrated)} {'has' if len(unrated) == 1 else 'have'} no "
                "Glassdoor or AmbitionBox page, so absence here is not evidence of a "
                "quiet week." if unrated else ""),
            company_note=(
                f"{plural(company_posts, 'item')} above "
                f"{'is' if company_posts == 1 else 'are'} company page activity — the "
                "employer posting about itself. Counted as coverage, excluded from net "
                "sentiment: the group does not score itself." if company_posts else ""),
            untagged_note=(
                f"{plural(untagged, 'mention')} not yet sentiment-tagged, excluded from "
                "the net sentiment figures." if untagged else ""),
            quiet_note=quiet_week_note(len(now)),
            same_day=(
                "Same-day escalation covers the channels checked daily. "
                + ", ".join(lagging)
                + (" is" if len(lagging) == 1 else " are")
                + " only read on the weekly sweep, so something posted there can be "
                "up to a week old before it is seen. The platforms block automated "
                "checking, so this is a limit of the sources, not of the process."
                if lagging else ""),
            data_link=data_link,
            holdings_note=holdings,
            scope_note=BOUNDARY_NOTE, trial_note=TRIAL_NOTE,
            date_band=week_label)
        return subject, broadsheet, "\n".join(t), stats

    return subject, "".join(h), "\n".join(t), stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="week_of Monday (YYYY-MM-DD); default = last complete week")
    parser.add_argument("--stdout", action="store_true", help="print the plain-text body")
    parser.add_argument("--allow-gaps", action="store_true",
                        help="build even when reviews are still unread; the email "
                             "does not disclose the shortfall, so only for a mid-sweep look")
    parser.add_argument("--style", choices=["plain", "broadsheet"], default="plain",
                        help="broadsheet: the serif, 600px house format "
                             "(same six deliverables, different skin)")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any mention in the week is untagged")
    parser.add_argument("--out-dir", default=H.OUT_DIR)
    args = parser.parse_args()

    week_of = H.parse_date(args.week) if args.week else H.last_complete_week()
    if week_of is None:
        print(f"Could not read --week {args.week!r}; expected YYYY-MM-DD", file=sys.stderr)
        return 2
    week_of = H.monday_of(week_of)

    settings = H.load_yaml("settings")
    subject, body_html, body_text, stats = build(week_of, settings, args.style)

    os.makedirs(args.out_dir, exist_ok=True)
    stem = f"digest-{week_of.isoformat()}"
    html_path = os.path.join(args.out_dir, stem + ".html")
    text_path = os.path.join(args.out_dir, stem + ".txt")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(f"<!doctype html><html><head><meta charset=\"utf-8\">"
                 f"<title>{html.escape(subject)}</title></head><body>{body_html}</body></html>")
    with open(text_path, "w", encoding="utf-8") as fh:
        fh.write(body_text + "\n")

    if args.stdout:
        print(body_text)
        print()

    print(f"Subject: {subject}")
    print(f"HTML body : {html_path}")
    print(f"Text body : {text_path}")
    print(f"Mentions {stats['total']} · red flags {stats['red_flags']} · untagged {stats['untagged']}")
    if stats["partial"]:
        # The console said "PARTIAL WEEK - 4 of 7 days" while the email above
        # it said the baseline was still open. Two frames for one state is how
        # an operator stops believing either.
        print(f"BASELINE STILL OPEN — it closes {H.day_month(stats['week_end'])}. "
              "Fine to review now; send it once the baseline closes."
              if stats.get("baseline") else
              f"PARTIAL WEEK — {stats['days_elapsed']} of 7 days. Fine for a mid-week look; "
              "do not send it as the weekly digest.")

    recipients = H.load_yaml("recipients").get("digest", [])
    ready = [r for r in recipients if str(r.get("email", "")).strip() and not H.is_todo(r.get("email", ""))]
    if ready:
        print(f"To: {', '.join(r['email'] for r in ready)}")
    if len(ready) < len(recipients):
        pending = [r.get("name", "?") for r in recipients if r not in ready]
        print(f"NOT SENDABLE YET — no address for {', '.join(pending)} "
              "(config/recipients.yaml). The body above is complete and reviewable.")
    print("Paste the HTML body into the email — the brief says body only, no attachments.")

    # A shortfall used to be a caption in the email. Telling four people the
    # table is incomplete does not make it complete - it just moves the problem
    # to their inbox. The sweep is finished when the logged rows account for
    # every review the counts say arrived, so that is now a gate, and the
    # worklist below says exactly what is left to read.
    if stats["coverage_gaps"] and not args.allow_gaps:
        print(f"\nNOT SENDABLE — {stats['coverage_gaps']} profile(s) are not accounted for.",
              file=sys.stderr)
        labels = {
            "unread": "reviews still to read",
            "not_swept": "NOT SWEPT — no snapshot this week",
            "no_baseline": "no previous snapshot to compare against",
            "count_dropped": "REVIEW COUNT FELL — the page was read differently",
        }
        for g in stats["coverage_detail"]:
            kind = g.get("kind", "unread")
            if kind == "unread":
                detail = (f"{g['new']} new, {g['logged']} logged, {g['missing']} TO READ")
            elif kind == "count_dropped":
                detail = (f"{labels[kind]} ({g['new']} vs last week). Check the location "
                          "filter and re-read the page the same way as last week.")
            else:
                detail = labels[kind]
            print(f"  {g['entity']} / {g['platform']}: {detail}", file=sys.stderr)
            if g["url"]:
                print(f"    {g['url']}", file=sys.stderr)
        print("\nLog the ratings and the reviews, then build again. To look at the digest "
              "before the sweep is finished, add --allow-gaps.", file=sys.stderr)
        return 1

    if args.strict and stats["untagged"]:
        print(f"STRICT: {stats['untagged']} untagged mention(s) in the week.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
