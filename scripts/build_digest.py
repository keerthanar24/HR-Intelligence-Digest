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


def headline_rows(mentions_now, mentions_prev, entities):
    """Per-entity counts and sentiment, with a group total row at the end.

    RK Group is the parent and the other four are its subsidiaries, so the four
    executives read this as one group first and a breakdown second. The parent
    keeps its own row - it is an employer in its own right - and the total
    spans every entity including it.
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
                "count_delta": delta_text(len(now), len(prev)),
                "net": sentiment_text(net_now),
                "net_prev": sentiment_text(net_prev),
                "net_delta": delta_text(net_now, net_prev, digits=2),
                "untagged": sum(1 for m in now if H.sentiment_score(m) is None),
                "is_total": False,
            }
        )

    net_now, net_prev = H.net_sentiment(mentions_now), H.net_sentiment(mentions_prev)
    rows.append(
        {
            "entity": "Group total",
            "count": len(mentions_now),
            "count_prev": len(mentions_prev),
            "count_delta": delta_text(len(mentions_now), len(mentions_prev)),
            "net": sentiment_text(net_now),
            "net_prev": sentiment_text(net_prev),
            "net_delta": delta_text(net_now, net_prev, digits=2),
            "untagged": sum(1 for m in mentions_now if H.sentiment_score(m) is None),
            "is_total": True,
        }
    )
    return rows


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
        rows.append(
            {
                "entity": entities.get(entity_id, entity_id),
                "platform": platforms.get(platform, platform.replace("_", " ").title()),
                "rating": f"{score_now:.2f}" if score_now is not None else "—",
                "rating_delta": delta_text(score_now, score_prev, digits=2),
                "reviews": count_now,
                "reviews_delta": delta_text(count_now, count_prev),
                "since": prev.get("week_of") if prev else "first snapshot",
            }
        )
    return rows


def coverage_rows(mentions_now, all_ratings, week_of, entities, platforms):
    """What the sweep actually covered, and where reviews were probably missed.

    "Every new review" cannot be guaranteed while three platforms are swept by
    hand. But the rating snapshot carries the review COUNT, so the change in
    that count is the number of reviews a platform genuinely gained. Comparing
    it with how many were logged turns an unverifiable claim into an arithmetic
    check: if AmbitionBox gained three reviews and one was logged, two were
    missed, and the digest says so rather than implying completeness.
    """
    prev_week = (week_of - dt.timedelta(days=7)).isoformat()
    this_week = week_of.isoformat()
    counts = {}
    for row in all_ratings:
        key = (row.get("entity"), row.get("platform"))
        if row.get("week_of") == this_week:
            counts.setdefault(key, {})["now"] = H.to_int(row.get("review_count"), -1)
        elif row.get("week_of") == prev_week:
            counts.setdefault(key, {})["prev"] = H.to_int(row.get("review_count"), -1)

    logged = collections.Counter(
        (m.get("entity"), m.get("platform")) for m in mentions_now)

    gaps, swept = [], set()
    for (entity_id, platform), seen in sorted(counts.items()):
        if "now" in seen:
            swept.add(platform)
        now, before = seen.get("now", -1), seen.get("prev", -1)
        if now < 0 or before < 0:
            continue                      # no pair of snapshots, nothing to compare
        new_reviews = now - before
        if new_reviews > 0 and new_reviews > logged.get((entity_id, platform), 0):
            gaps.append({
                "entity": entities.get(entity_id, entity_id),
                "platform": platforms.get(platform, platform),
                "new": new_reviews,
                "logged": logged.get((entity_id, platform), 0),
            })
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
        score = H.sentiment_score(m)
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
    by_mention = {e.get("mention_id"): e for e in escalations if e.get("mention_id")}
    rows = []
    for m in mentions:
        if not H.is_yes(m.get("red_flag")):
            continue
        esc = by_mention.get(m.get("mention_id"), {})
        rows.append(
            {
                "mention_id": m.get("mention_id", ""),
                "entity": entities.get(m.get("entity"), m.get("entity", "")),
                "platform": platforms.get(m.get("platform"), m.get("platform", "")),
                "date": m.get("post_date") or m.get("captured_at", ""),
                "reason": (m.get("red_flag_reason") or esc.get("reason") or "unspecified").replace("_", " "),
                # The digest never carries a named individual; the restricted
                # escalation log does. See docs/00-brief.md section 10.
                "summary": m.get("one_line_summary", ""),
                "url": m.get("url", ""),
                "status": esc.get("status") or m.get("status") or "open",
                "notified": esc.get("notified", ""),
                "names_individual": H.is_yes(m.get("names_individual")),
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# --- rendering ---------------------------------------------------------------

E = html.escape


def h_table(headers, rows, aligns=None):
    aligns = aligns or ["left"] * len(headers)
    out = ['<table role="presentation" cellpadding="8" cellspacing="0" border="0" '
           'style="border-collapse:collapse;width:100%;font-size:14px;margin:0 0 8px;">']
    out.append("<tr>")
    for header, align in zip(headers, aligns):
        out.append(
            f'<th align="{align}" style="background:#f2f4f7;border:1px solid #d7dbe0;'
            f'font-weight:600;color:#1f2933;">{E(str(header))}</th>'
        )
    out.append("</tr>")
    for index, row in enumerate(rows):
        bg = "#ffffff" if index % 2 == 0 else "#fafbfc"
        out.append("<tr>")
        for cell, align in zip(row, aligns):
            out.append(
                f'<td align="{align}" style="background:{bg};border:1px solid #e3e6ea;'
                f'color:#1f2933;vertical-align:top;">{cell}</td>'
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


def build(week_of: dt.date, settings: dict) -> tuple[str, str, str, dict]:
    digest_cfg = settings.get("digest", {})
    entities = H.entity_names()
    platforms = H.platform_names()
    max_themes = int(digest_cfg.get("max_themes", 4))
    summary_max = int(digest_cfg.get("summary_max_chars", 160))

    all_mentions = H.read_csv(H.MENTIONS_CSV)
    all_ratings = H.read_csv(H.RATINGS_CSV)
    escalations = H.read_csv(H.ESCALATIONS_CSV)

    prev_week = week_of - dt.timedelta(days=7)
    now = [m for m in H.mentions_for_week(all_mentions, week_of)
           if (m.get("status") or "") != "out_of_scope"]
    prev = [m for m in H.mentions_for_week(all_mentions, prev_week)
            if (m.get("status") or "") != "out_of_scope"]

    heads = headline_rows(now, prev, entities)
    ratings = rating_rows(all_ratings, week_of, entities, platforms)
    themes = theme_rows(now, max_themes)
    flags = red_flag_rows(now, escalations, entities, platforms)
    swept, gaps = coverage_rows(now, all_ratings, week_of, entities, platforms)
    rolling_weeks = int(digest_cfg.get("rolling_theme_weeks", 4))
    rolling, rolling_total = rolling_theme_rows(all_mentions, week_of, rolling_weeks, max_themes)

    total = len(now)
    total_prev = len(prev)
    net_now = H.net_sentiment(now)
    net_prev = H.net_sentiment(prev)
    untagged = sum(1 for m in now if H.sentiment_score(m) is None)
    data_link = digest_cfg.get("data_link", "")
    week_label = H.fmt_week(week_of)

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
        "red_flags": len(flags),
        "week_label": week_label,
        "coverage_gaps": len(gaps),
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
        f'<p style="margin:0 0 16px;color:#52606d;font-size:13px;">Week of {E(week_label)} '
        f'· {E(plural(total, "mention"))} '
        f'({delta_text(total, total_prev)} vs previous week) '
        f'· net sentiment {E(sentiment_text(net_now))} '
        f'({E(delta_text(net_now, net_prev, digits=2))})</p>'
    )

    if partial:
        h.append(
            '<p style="margin:0 0 16px;padding:8px 10px;background:#FBF0D9;border-radius:4px;'
            f'font-size:13px;color:#8a6d3b;"><strong>Partial week</strong> \u2014 covers '
            f'{days_elapsed} of 7 days, to {today.strftime("%-d %b")}. The week closes '
            f'{week_end.strftime("%-d %b")}; counts and comparisons here are incomplete.</p>'
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
    ))
    if untagged:
        h.append(
            f'<p style="margin:0 0 8px;color:#8a6d3b;font-size:13px;">{plural(untagged, "mention")} '
            'not yet sentiment-tagged, excluded from the net sentiment figures.</p>'
        )

    # 2. Rating movement
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">2 · Rating Movement</h3>')
    if ratings:
        h.append(h_table(
            ["Entity", "Platform", "Rating", "Change", "Reviews", "New"],
            [[E(r["entity"]), E(r["platform"]), E(r["rating"]), E(r["rating_delta"]),
              r["reviews"], E(r["reviews_delta"])] for r in ratings],
            ["left", "left", "right", "right", "right", "right"],
        ))
    else:
        h.append('<p style="margin:0 0 8px;">No rating snapshot recorded for this week. '
                 'Glassdoor and AmbitionBox scores are captured on the manual sweep.</p>')

    # 3. What's new
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">3 · What\'s New</h3>')
    if now:
        rows = []
        for m in sorted(now, key=lambda x: (x.get("post_date") or "", x.get("entity") or "")):
            link = m.get("url", "")
            summary = truncate(m.get("one_line_summary") or m.get("title_or_snippet", ""), summary_max)
            cell = E(summary)
            if link:
                cell += f' <a href="{E(link)}" style="color:#2b6cb0;">link</a>'
            rows.append([
                E(entities.get(m.get("entity"), m.get("entity", ""))),
                E(platforms.get(m.get("platform"), m.get("platform", ""))),
                E(m.get("post_date") or m.get("captured_at", "")),
                E(H.SENTIMENT_LABELS.get((m.get("sentiment") or "").lower(), "Untagged")),
                cell,
            ])
        h.append(h_table(["Entity", "Platform", "Date", "Sentiment", "Summary"], rows))
    else:
        h.append('<p style="margin:0 0 8px;">No new reviews or posts this week.</p>')

    if swept:
        h.append(f'<p style="margin:0 0 4px;font-size:12px;color:#52606d;">Swept this week: '
                 f'{E(", ".join(swept))}.</p>')
    if gaps:
        detail = "; ".join(f"{g['entity']} on {g['platform']} gained {g['new']} review(s), "
                           f"{g['logged']} logged" for g in gaps)
        h.append(
            '<p style="margin:0 0 8px;padding:8px 10px;background:#FBF0D9;border-radius:4px;'
            'font-size:12px;color:#8a6d3b;"><strong>Not everything was captured.</strong> '
            f'{E(detail)}. The review counts moved further than the rows above account for, '
            'so this table is incomplete.</p>')

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
        h.append(
            '<p style="margin:0 0 8px;color:#a12622;"><strong>'
            f'{plural(len(flags), "item")} escalated this week.</strong> Names of individuals are '
            'held in the restricted escalation log, not in this email.</p>'
        )
        h.append(h_table(
            ["ID", "Entity", "Platform", "Date", "Trigger", "Status", "Detail"],
            [[E(r["mention_id"]), E(r["entity"]), E(r["platform"]), E(r["date"]),
              E(r["reason"]), E(r["status"]),
              (E(truncate(r["summary"], 120)) +
               (f' <a href="{E(r["url"])}" style="color:#2b6cb0;">link</a>' if r["url"] else ""))]
             for r in flags],
        ))
    else:
        h.append('<p style="margin:0 0 8px;">None this week.</p>')

    # 6. Data link
    h.append('<h3 style="font-size:16px;margin:20px 0 6px;">6 · Data</h3>')
    if data_link and not H.is_todo(data_link):
        h.append(f'<p style="margin:0 0 8px;"><a href="{E(data_link)}" style="color:#2b6cb0;">'
                 'Open the tracking sheet</a> for the full week\'s raw entries.</p>')
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
    t.append(f"Week of {week_label}")
    t.append(
        f"{plural(total, 'mention')} ({delta_text(total, total_prev)} vs previous week) · "
        f"net sentiment {sentiment_text(net_now)} "
        f"({delta_text(net_now, net_prev, digits=2)} vs previous week)"
    )
    if partial:
        t.append(f"PARTIAL WEEK - covers {days_elapsed} of 7 days, to "
                 f"{today.strftime('%-d %b')}. The week closes {week_end.strftime('%-d %b')}; "
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
    t.append("")
    t.append("2. RATING MOVEMENT")
    t.append(t_table(
        ["Entity", "Platform", "Rating", "Change", "Reviews", "New"],
        [[r["entity"], r["platform"], r["rating"], r["rating_delta"], r["reviews"], r["reviews_delta"]]
         for r in ratings],
    ) if ratings else "No rating snapshot recorded for this week.")
    t.append("")
    t.append("3. WHAT'S NEW")
    if now:
        for m in sorted(now, key=lambda x: (x.get("post_date") or "", x.get("entity") or "")):
            t.append(
                f"- [{entities.get(m.get('entity'), m.get('entity',''))} / "
                f"{platforms.get(m.get('platform'), m.get('platform',''))} / "
                f"{m.get('post_date') or m.get('captured_at','')} / "
                f"{H.SENTIMENT_LABELS.get((m.get('sentiment') or '').lower(), 'Untagged')}] "
                f"{truncate(m.get('one_line_summary') or m.get('title_or_snippet',''), summary_max)}"
            )
            if m.get("url"):
                t.append(f"  {m['url']}")
    else:
        t.append("No new reviews or posts this week.")
    if swept:
        t.append("")
        t.append(f"Swept this week: {', '.join(swept)}.")
    if gaps:
        t.append("NOT EVERYTHING WAS CAPTURED - " + "; ".join(
            f"{g['entity']} on {g['platform']} gained {g['new']} review(s), {g['logged']} logged"
            for g in gaps) + ". This table is incomplete.")
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
        t.append(f"{plural(len(flags), 'item')} escalated this week. "
                 "Names of individuals are held in the restricted escalation log, not here.")
        for r in flags:
            t.append(f"- {r['mention_id']} [{r['entity']} / {r['platform']} / {r['date']}] "
                     f"{r['reason']} · status {r['status']}")
            t.append(f"  {truncate(r['summary'], 120)}")
            if r["url"]:
                t.append(f"  {r['url']}")
    else:
        t.append("None this week.")
    t.append("")
    t.append("6. DATA")
    t.append(data_link if data_link and not H.is_todo(data_link)
             else "Tracking sheet link not set — add digest.data_link in config/settings.yaml.")
    t.append("")
    t.append("-" * 72)
    t.append(BOUNDARY_NOTE)
    t.append("")
    t.append(TRIAL_NOTE)

    subject_template = digest_cfg.get(
        "subject_template", "HR Intelligence Digest — week of {week_of} ({mention_count} mentions)"
    )
    subject = subject_template.format(
        week_of=week_label, mention_count=total, red_flags=len(flags),
    )
    if partial:
        subject += f" \u00b7 PARTIAL ({days_elapsed}/7 days)"
    if flags:
        subject += f" · {len(flags)} red flag{'s' if len(flags) != 1 else ''}"

    return subject, "".join(h), "\n".join(t), stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="week_of Monday (YYYY-MM-DD); default = last complete week")
    parser.add_argument("--stdout", action="store_true", help="print the plain-text body")
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
    subject, body_html, body_text, stats = build(week_of, settings)

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
        print(f"PARTIAL WEEK — {stats['days_elapsed']} of 7 days. Fine for a mid-week look; "
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

    if args.strict and stats["untagged"]:
        print(f"STRICT: {stats['untagged']} untagged mention(s) in the week.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
