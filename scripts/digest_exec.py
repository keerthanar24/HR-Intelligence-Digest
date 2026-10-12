"""The executive layout of the weekly digest: the default since October 2026.

Same six deliverables as the plain and broadsheet styles, in the same order,
built for a leadership audience. It adds what the October review of the trial
(feedback from Shrinivas against Sonal's requirements) found missing:

  - every figure set against the previous week, with an arrow
  - "Insufficient data" instead of a score built from one review
  - each item labelled by who wrote it, with the company's own posts unscored
  - themes named with the companies they came from, and marked new,
    increasing or recurring - never recurring on one isolated mention
  - job-market and candidate signals (open roles, interview, pay, exits)
  - which channels were checked, when, and which were not
  - whether same-day red-flag alerts can actually reach the four

Kept in its own module so build_digest.py stays the single place the numbers
are computed; this file only decides how they are shown.
"""

from __future__ import annotations

import collections
import datetime as dt
import html

import hrintel as H

E = html.escape
FONT = "-apple-system,Segoe UI,Roboto,Arial,sans-serif"

INK, MUTED, FAINT, RULE, PANEL = "#1c2333", "#6b7280", "#9ca3af", "#eef0f3", "#f7f8fa"
ACCENT = "#8a2f2a"
GOOD = ("#e8f5e9", "#2e7d32")
BAD = ("#fdecea", "#b91c1c")
NEUTRAL = ("#f3f4f6", "#4b5563")
OFF = ("#f9fafb", "#9ca3af")
WARN = ("#fff7e6", "#8a6d3b")

# Mention-level classification. Shared with docs/05-sentiment-and-themes.md.
CLASS_OF = {
    "very_positive": "positive", "positive": "positive",
    "neutral": "neutral", "mixed": "neutral",
    "negative": "negative", "very_negative": "negative",
}

# Themes grouped into the job-market signals the brief asks for.
SIGNALS = [
    ("Interviews & hiring", {"interview", "onboarding"}),
    ("Pay & appraisals", {"compensation", "appraisal", "payroll_delay"}),
    ("Exits & job security", {"exits", "layoffs", "job_security"}),
]

EMPLOYEE_AUTHORS = {"current_employee", "ex_employee", "intern", "contractor"}


# --- small pieces -------------------------------------------------------------


def x(value) -> str:
    return E("" if value is None else str(value))


def pill(text: str, colours: tuple[str, str], *, strong: bool = True) -> str:
    bg, fg = colours
    weight = 700 if strong else 600
    return (f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:2px 9px;'
            f'border-radius:10px;background:{bg};color:{fg};'
            f'font:{weight} 12px/1.4 {FONT};white-space:nowrap;">{text}</span>')


def arrow(diff, *, digits: int = 0, suffix: str = "", up_is_good: bool | None = True,
          show_value: bool = True) -> str:
    """'↑ +0.50' in green, '↓ -1' in red, '→ no change' in grey.

    up_is_good=None colours both directions grey: more mentions is not good or
    bad on its own, and colouring it would say otherwise.
    """
    if diff is None:
        return f'<span style="color:{FAINT};">&mdash;</span>'
    if abs(diff) < 0.5 * (10 ** -digits):
        return f'<span style="color:{MUTED};">&rarr; no change</span>'
    up = diff > 0
    if up_is_good is None:
        colour = MUTED
    else:
        colour = GOOD[1] if up == up_is_good else BAD[1]
    sign = "+" if up else "-"
    value = f" {sign}{abs(diff):.{digits}f}{suffix}" if show_value else ""
    return (f'<span style="color:{colour};font-weight:600;white-space:nowrap;">'
            f'{"&uarr;" if up else "&darr;"}{value}</span>')


def th(text: str, align: str = "left", width: str = "") -> str:
    w = f' width="{width}"' if width else ""
    return (f'<th align="{align}"{w} style="padding:8px 8px 8px 0;font:700 11px/1.3 {FONT};'
            f'text-transform:uppercase;letter-spacing:.03em;color:{FAINT};'
            f'border-bottom:2px solid #e5e7eb;">{text}</th>')


def td(inner: str, align: str = "left", *, last: bool = False, bold: bool = False) -> str:
    border = "" if last else f"border-bottom:1px solid {RULE};"
    weight = 700 if bold else 400
    return (f'<td align="{align}" valign="top" style="padding:9px 8px 9px 0;'
            f'font:{weight} 14px/1.45 {FONT};color:{INK};{border}'
            f'word-break:break-word;overflow-wrap:anywhere;">{inner}</td>')


def table(head: list[str], rows: list[str]) -> str:
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="border-collapse:collapse;table-layout:fixed;">'
            f'<tr>{"".join(head)}</tr>{"".join(rows)}</table>')


def small(text: str, colour: str = FAINT) -> str:
    return (f'<div style="font:400 12px/1.5 {FONT};color:{colour};'
            f'padding-top:2px;">{text}</div>')


def note(text: str, colour: str = FAINT) -> str:
    return (f'<div style="font:400 12.5px/1.55 {FONT};color:{colour};'
            f'padding-top:8px;">{text}</div>')


def box(inner: str, colours: tuple[str, str] = (PANEL, "#4b5563")) -> str:
    bg, fg = colours
    return (f'<div style="background:{bg};border-radius:6px;padding:12px 14px;'
            f'margin-top:10px;font:400 13px/1.6 {FONT};color:{fg};">{inner}</div>')


def row(inner: str, pad: str = "10px 32px 0 32px") -> str:
    return f'<tr><td class="pad" style="padding:{pad};">{inner}</td></tr>'


def section(number: int, title: str, lead: str) -> str:
    # Matches the other two styles' heading markup closely enough for the
    # smoke test's six-deliverable check: '>N &middot; Title<'.
    return row(
        f'<div style="font:700 12px/1 {FONT};letter-spacing:.08em;'
        f'text-transform:uppercase;color:{ACCENT};">{number} &middot; {E(title)}</div>'
        f'<div style="font:400 13px/1.55 {FONT};color:{MUTED};padding-top:6px;">{lead}</div>',
        pad="28px 32px 0 32px")


def subhead(title: str) -> str:
    return (f'<div style="font:700 11px/1 {FONT};letter-spacing:.08em;'
            f'text-transform:uppercase;color:{MUTED};padding:18px 0 8px 0;">{title}</div>')


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def fmt_day(value: str) -> str:
    day = H.parse_date(value or "")
    return H.day_month(day) if day else (value or "")


# --- classification -------------------------------------------------------------


def mention_class(m: dict) -> str:
    """positive / neutral / negative / company / untagged."""
    if H.is_company_voice(m):
        return "company"
    return CLASS_OF.get((m.get("sentiment") or "").strip().lower(), "untagged")


def breakdown(rows: list[dict]) -> collections.Counter:
    return collections.Counter(mention_class(m) for m in rows)


def overall(rows: list[dict], minimum: int) -> tuple[str, tuple[str, str], float | None]:
    """(label, colours, net) for a set of mentions.

    Below `minimum` scored mentions the label is 'Insufficient data': one
    review is one person's view, and a score built on it reads like a trend.
    """
    scored = [m for m in H.scored_rows(rows) if H.sentiment_score(m) is not None]
    net = H.net_sentiment(rows)
    if not scored:
        if not rows:
            return "No reviews", OFF, None
        if H.untagged_rows(rows):
            return "Awaiting review", WARN, None
        return "Not scored", OFF, None
    if len(scored) < minimum:
        return "Insufficient data", OFF, net
    if net >= 0.5:
        return "Positive", GOOD, net
    if net <= -0.5:
        return "Negative", BAD, net
    return "Neutral", NEUTRAL, net


def who(m: dict) -> str:
    """What kind of voice this is - the distinction the review asked for."""
    author = (m.get("author_type") or "").strip().lower()
    item = (m.get("item_type") or "review").strip().lower()
    if author == "company":
        return "Company post"
    if item == "interview" or author == "candidate":
        return "Candidate"
    if author in EMPLOYEE_AUTHORS:
        return H.AUTHOR_LABELS.get(author, "Employee")
    if author == "anonymous":
        return "Anonymous"
    return "Author unknown"


def mention_pill(m: dict) -> str:
    cls = mention_class(m)
    label = {
        "positive": ("Positive", GOOD), "negative": ("Negative", BAD),
        "neutral": ("Neutral", NEUTRAL), "company": ("Not scored", OFF),
        "untagged": ("Awaiting review", WARN),
    }[cls]
    return pill(label[0], label[1], strong=False)


# --- the data each section needs -----------------------------------------------


def snapshot_pairs(all_ratings, week_of):
    """{(entity, platform): (latest, previous)} using snapshots up to this week."""
    last_day = (week_of + dt.timedelta(days=6)).isoformat()
    by_key = collections.defaultdict(list)
    for r in all_ratings:
        if (r.get("week_of") or "") <= last_day:
            by_key[(r.get("entity"), r.get("platform"))].append(r)
    out = {}
    for key, snaps in by_key.items():
        snaps.sort(key=lambda r: (r.get("week_of", ""), r.get("captured_at", "")))
        out[key] = (snaps[-1], snaps[-2] if len(snaps) > 1 else None)
    return out


def rating_cell(pair, week_of) -> tuple[str, bool]:
    """(html, changed_this_week) for one entity on one review site."""
    latest, prev = pair
    score = H.to_float(latest.get("overall_rating"))
    count = H.to_int(latest.get("review_count"), -1)
    this_week = latest.get("week_of") == week_of.isoformat()
    head = (f'<strong>{score:.2f}</strong>' if score is not None else "&mdash;")
    if count >= 0:
        head += f' <span style="color:{FAINT};font-size:12px;">({count})</span>'
    if not this_week:
        when = fmt_day(latest.get("captured_at") or latest.get("week_of"))
        return head + small(f"not re-checked ({x(when)})", WARN[1]), False
    if prev is None:
        return head + small("first reading"), False
    before = H.to_float(prev.get("overall_rating"))
    diff = None if score is None or before is None else score - before
    since = fmt_day(prev.get("week_of"))
    before_count = H.to_int(prev.get("review_count"), count)
    new_reviews = count - before_count
    if new_reviews < 0:
        # Review counts do not go down. A drop means the page was read a
        # different way, or is not the page it was - so the score cannot be
        # compared and must not be reported as a movement.
        return (head + small(f"review count fell {before_count} &rarr; {count}: "
                             "check this page", BAD[1]), False)
    extra = (f' &middot; +{new_reviews} reviews' if new_reviews > 0 else "")
    return (head + small(f"{arrow(diff, digits=2)} since {x(since)}{extra}"),
            diff is not None and abs(diff) >= 0.005)


def recommend_cell(pair, week_of) -> str:
    latest, prev = pair
    value = H.to_float(latest.get("recommend_pct"))
    if value is None:
        return f'<span style="color:{FAINT};">&mdash;</span>'
    out = f"{value:.0f}%"
    if latest.get("week_of") == week_of.isoformat() and prev is not None:
        before = H.to_float(prev.get("recommend_pct"))
        if before is not None:
            out += small(arrow(value - before, suffix="pp"))
    return out


def theme_table(now, window, week_of, entities, limit):
    """Themes this week, each with its companies and a status.

    The status is decided over the rolling window, never on one mention:
    Single mention / New / Increasing / Recurring.
    """
    this_week = week_of.isoformat()
    prev_week = (week_of - dt.timedelta(days=7)).isoformat()
    stats = collections.defaultdict(lambda: {"now": 0, "prev": 0, "weeks": set(),
                                             "total": 0, "companies": set(), "scores": []})
    for m in window:
        for theme in H.split_themes(m.get("themes", "")):
            s = stats[theme]
            s["total"] += 1
            s["weeks"].add(m.get("week_of"))
            if m.get("week_of") == prev_week:
                s["prev"] += 1
    for m in now:
        score = None if H.is_company_voice(m) else H.sentiment_score(m)
        for theme in H.split_themes(m.get("themes", "")):
            s = stats[theme]
            s["now"] += 1
            s["companies"].add(entities.get(m.get("entity"), m.get("entity")))
            if score is not None:
                s["scores"].append(score)

    def status(s):
        earlier = s["total"] - s["now"]
        if s["total"] <= 1:
            return pill("Single mention", OFF, strong=False)
        if earlier == 0:
            return pill("New", NEUTRAL, strong=False)
        if s["prev"] and s["now"] > s["prev"]:
            return pill("Increasing", BAD, strong=False)
        if len(s["weeks"]) >= 2:
            return pill("Recurring", WARN, strong=False)
        return pill("New", NEUTRAL, strong=False)

    def tone(s):
        if not s["scores"]:
            return f'<span style="color:{FAINT};">Not scored</span>'
        mean = sum(s["scores"]) / len(s["scores"])
        if mean <= -0.5:
            return f'<span style="color:{BAD[1]};font-weight:600;">Complaint</span>'
        if mean >= 0.5:
            return f'<span style="color:{GOOD[1]};font-weight:600;">Praise</span>'
        return f'<span style="color:{MUTED};font-weight:600;">Mixed</span>'

    current = sorted(((t, s) for t, s in stats.items() if s["now"]),
                     key=lambda ts: (-ts[1]["now"], ts[0]))[:limit]
    rows = []
    for i, (theme, s) in enumerate(current):
        last = i == len(current) - 1
        rows.append(
            "<tr>"
            + td(f'<strong>{x(theme.replace("_", " ").capitalize())}</strong>', last=last)
            + td(x(", ".join(sorted(s["companies"]))), last=last)
            + td(str(s["now"]), "center", last=last)
            + td(status(s), last=last)
            + td(tone(s), "right", last=last)
            + "</tr>")

    # Only what genuinely repeats: two or more mentions in two or more weeks.
    recurring = sorted(((t, s) for t, s in stats.items()
                        if s["total"] >= 2 and len(s["weeks"]) >= 2),
                       key=lambda ts: (-ts[1]["total"], ts[0]))
    return rows, recurring


def coverage(week_of, platforms, all_ratings, sweeps, now, settings):
    """One row per platform: checked this week or not, last checked, found."""
    this_week = week_of.isoformat()
    last_day = week_of + dt.timedelta(days=6)
    rated = {p for _, p in H.rated_profiles()}
    found = collections.Counter(m.get("platform") for m in now)
    out = []
    for p in H.load_yaml("sources").get("platforms", []):
        pid = p["id"]
        dates = []
        checked = False
        for r in all_ratings:
            if r.get("platform") == pid:
                d = H.parse_date(r.get("captured_at", ""))
                if d and d <= last_day + dt.timedelta(days=3):
                    dates.append(d)
                checked |= r.get("week_of") == this_week
        notes = []
        for s in sweeps:
            if s.get("platform") == pid:
                d = H.parse_date(s.get("checked_at", ""))
                if d and d <= last_day + dt.timedelta(days=3):
                    dates.append(d)
                if s.get("week_of") == this_week:
                    checked = True
                    notes.append((s.get("notes") or "").lower())
        no_page = pid == "indeed" and any("no indeed employer page" in (s.get("notes") or "").lower()
                                          for s in sweeps if s.get("platform") == pid)
        due = H.cadence_due(p.get("cadence", "weekly"), week_of, settings)
        if checked:
            state = pill("Checked", GOOD, strong=False)
        elif no_page:
            state = pill("No company page", OFF, strong=False)
        elif not due:
            state = pill("Not due (fortnightly)", OFF, strong=False)
        else:
            state = pill("Not checked", WARN, strong=False)
        out.append({
            "name": platforms.get(pid, pid),
            "state": state,
            "last": H.day_month(max(dates)) if dates else "never",
            "last_date": max(dates) if dates else None,
            "found": found.get(pid, 0),
            "checked": checked,
            "due": due and not no_page,
            "how": "Automatic" if pid not in rated and p.get("collection") in ("feed", "api", "alert")
                   else "Manual",
        })
    return out


def alert_readiness():
    """(configured, total) red-flag recipients with a real address."""
    people = H.load_yaml("recipients").get("red_flag", [])
    ready = [p for p in people if str(p.get("email", "")).strip()
             and not H.is_todo(p.get("email", ""))]
    return len(ready), len(people)


def name_variants() -> int:
    return sum(len(e.get("aliases") or []) for e in H.load_yaml("entities").get("entities", []))


# --- the email ------------------------------------------------------------------


def render(*, week_of, week_label, prev_label, baseline, partial_notice, entities, platforms,
           now, prev, all_mentions, all_ratings, flags, lagging, data_link, holdings,
           settings) -> tuple[str, dict]:
    cfg = settings.get("digest", {})
    minimum = int(cfg.get("min_scored_mentions", 2))
    max_themes = int(cfg.get("max_themes", 4))
    rolling_weeks = int(cfg.get("rolling_theme_weeks", 4))
    summary_max = int(cfg.get("summary_max_chars", 160))
    sweeps = H.read_csv(H.SWEEPS_CSV)
    market = H.read_csv(H.MARKET_CSV)

    counts_now, counts_prev = breakdown(now), breakdown(prev)
    pairs = snapshot_pairs(all_ratings, week_of)
    rating_changes = sum(1 for (e, p), pair in pairs.items()
                         if rating_cell(pair, week_of)[1])
    rechecked = any(pair[0].get("week_of") == week_of.isoformat() for pair in pairs.values())
    cover = coverage(week_of, platforms, all_ratings, sweeps, now, settings)
    not_checked = [c["name"] for c in cover if c["due"] and not c["checked"]]
    checked_dates = [c["last_date"] for c in cover if c["last_date"]]
    last_monitored = max(checked_dates) if checked_dates else None
    ready, needed = alert_readiness()
    compare = not baseline

    p: list[str] = []
    p.append(
        # Body content only, like the broadsheet: build_digest.main() wraps it
        # in the document, and send_digest.py puts it straight into the email.
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>a{text-decoration:none;}@media only screen and (max-width:620px){'
        '.shell{width:100%!important;}.pad{padding-left:18px!important;'
        'padding-right:18px!important;}.tile{display:block!important;width:100%!important;'
        'margin-bottom:8px!important;}}</style>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{RULE};"><tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" class="shell" width="640" cellpadding="0" cellspacing="0" '
        'border="0" style="width:640px;max-width:100%;background:#ffffff;border-radius:10px;'
        'overflow:hidden;">')

    # Header
    period = (f"{x(week_label)}" if baseline else f"Week of {x(week_label)}")
    vs = "" if baseline else f" &middot; compared with {x(prev_label)}"
    monitored = (f"Last monitored {H.day_month(last_monitored, year=True)}"
                 if last_monitored else "Not yet monitored")
    p.append(
        f'<tr><td class="pad" style="background:{INK};padding:26px 32px;">'
        f'<div style="font:700 22px/1.3 {FONT};color:#ffffff;">HR Intelligence Digest</div>'
        f'<div style="font:400 13px/1.5 {FONT};color:#aab4ca;padding-top:4px;">'
        f'{period}{vs}</div>'
        f'<div style="font:400 12px/1.5 {FONT};color:#8fa0c7;padding-top:2px;">{monitored}</div>'
        '</td></tr>')

    if partial_notice:
        p.append(row(box(partial_notice, WARN), pad="16px 32px 0 32px"))

    # Executive summary tiles
    def tile(value, label, sub="", colour=INK, bg=PANEL):
        return (f'<td class="tile" width="20%" align="center" valign="top" '
                f'style="background:{bg};border-radius:8px;padding:12px 4px;">'
                f'<div style="font:700 22px/1 {FONT};color:{colour};">{value}</div>'
                f'<div style="font:400 11.5px/1.35 {FONT};color:{MUTED};padding-top:6px;">'
                f'{label}</div>'
                f'<div style="font:400 11px/1.35 {FONT};padding-top:3px;">{sub}</div></td>')

    gap = '<td width="6" style="font-size:0;">&nbsp;</td>'
    total, total_prev = len(now), len(prev)
    tiles = [
        tile(total, "New mentions",
             arrow(total - total_prev, up_is_good=None) + " vs last wk" if compare else ""),
        tile(counts_now["positive"], "Positive", colour=GOOD[1]),
        tile(counts_now["negative"], "Negative", colour=BAD[1] if counts_now["negative"] else INK),
        tile(rating_changes, "Rating changes",
             "" if rechecked else f'<span style="color:{WARN[1]};">not re-checked</span>'),
        tile(len(flags), "Red-flag alerts", colour=BAD[1] if flags else GOOD[1],
             bg=BAD[0] if flags else GOOD[0]),
    ]
    p.append(row('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                 f'border="0"><tr>{gap.join(tiles)}</tr></table>', pad="22px 32px 0 32px"))

    # In short - derived, never hand-written
    said = []
    if total:
        parts = [f"{counts_now[k]} {k}" for k in ("positive", "negative", "neutral")
                 if counts_now[k]]
        if counts_now["company"]:
            parts.append(plural(counts_now["company"], "company post"))
        if counts_now["untagged"]:
            parts.append(f"{counts_now['untagged']} awaiting review")
        said.append(f"{plural(total, 'new mention')} ({', '.join(parts)}).")
    else:
        said.append("No new mentions of the four companies this week.")
    if rechecked:
        said.append(f"{plural(rating_changes, 'rating')} changed." if rating_changes
                    else "No rating changes.")
    else:
        last = max((H.parse_date(pr[0].get("captured_at", "")) for pr in pairs.values()),
                   default=None)
        said.append("Glassdoor and AmbitionBox ratings were not re-checked this week"
                    + (f" (last checked {H.day_month(last)})." if last else "."))
    said.append(f"{plural(len(flags), 'red-flag alert')} - see section 5." if flags
                else "Nothing tripped a red-flag trigger.")
    if not_checked:
        said.append(f"Not checked this week: {', '.join(not_checked)}.")
    p.append(row(f'<div style="font:400 14px/1.6 {FONT};color:{INK};"><strong>In short:</strong> '
                 f'{x(" ".join(said))}</div>', pad="14px 32px 0 32px"))

    # 1 Headline - sentiment by company
    p.append(section(1, "Headline", "New mentions and sentiment for each company this week"
                     + ("" if baseline else ", against last week") + "."))
    rows = []
    groups = list(entities.items()) + [("__group__", "Group total")]
    for i, (eid, name) in enumerate(groups):
        is_total = eid == "__group__"
        mine = now if is_total else [m for m in now if m.get("entity") == eid]
        theirs = prev if is_total else [m for m in prev if m.get("entity") == eid]
        c = breakdown(mine)
        chips = "".join(pill(f"{c[k]} {lbl}", col, strong=False) for k, lbl, col in (
            ("positive", "positive", GOOD), ("neutral", "neutral", NEUTRAL),
            ("negative", "negative", BAD), ("company", "company post", OFF),
            ("untagged", "awaiting review", WARN)) if c[k])
        if not chips:
            chips = f'<span style="color:{FAINT};font-size:13px;">Nothing new</span>'
        label, colours, net = overall(mine, minimum)
        shown = label + (f" &middot; {'0.0' if abs(net) < 0.05 else f'{net:+.1f}'}"
                         if net is not None and label not in
                         ("Insufficient data", "No reviews", "Not scored", "Awaiting review") else "")
        _, _, net_prev = overall(theirs, minimum)
        move = ""
        if compare:
            count_move = arrow(len(mine) - len(theirs), up_is_good=None)
            enough = (label not in ("Insufficient data", "No reviews", "Not scored", "Awaiting review")
                      and overall(theirs, minimum)[0] not in
                      ("Insufficient data", "No reviews", "Not scored", "Awaiting review"))
            senti_move = arrow(net - net_prev, digits=1) if enough else \
                f'<span style="color:{FAINT};">&mdash;</span>'
            move = small(f"mentions {count_move} &middot; sentiment {senti_move}", MUTED)
        last = i == len(groups) - 1
        rows.append("<tr>"
                    + td(f"<strong>{x(name)}</strong>" if is_total else x(name), last=last)
                    + td(str(len(mine)), "center", last=last, bold=is_total)
                    + td(chips, last=last)
                    + td(pill(shown, colours) + move, "right", last=last)
                    + "</tr>")
    pending = len(H.untagged_rows(now))
    pending_note = (note(f"{plural(pending, 'mention')} not yet sentiment-tagged &mdash; shown as "
                         "awaiting review and left out of the scores until a person reads "
                         f"{'it' if pending == 1 else 'them'}.", WARN[1]) if pending else "")
    p.append(row(table([th("Company", width="27%"), th("Mentions", "center", "13%"),
                        th("What was said", width="30%"), th("Overall", "right", "30%")],
                       rows)
                 + pending_note
                 + box("<strong style=\"color:#1c2333;\">How it is scored:</strong> each "
                       "employee or reviewer mention is tagged Positive (+1), Neutral or mixed "
                       "(0) or Negative (&minus;1), &plusmn;2 when very strong. The overall "
                       "label is the average: +0.5 or above is Positive, &minus;0.5 or below "
                       f"is Negative, anything between is Neutral. With fewer than {minimum} "
                       "scored mentions it reads <em>Insufficient data</em> &mdash; one review "
                       "is one person&rsquo;s view, not a trend. The company&rsquo;s own posts "
                       "are counted as mentions but never scored.")))

    # 2 Rating Movement
    p.append(section(2, "Rating Movement", "Star ratings on the two main employer review "
                     "sites, with the change since the previous check."))
    rows = []
    names = list(entities.items())
    covered = {e for e, _ in H.rated_profiles()}
    unrated = [name for eid, name in names if eid not in covered]
    absent = [f"{entities.get(e, e)} on {platforms.get(pl, pl)}" for e, pl in H.absent_profiles()
              if entities.get(e) and entities.get(e) not in unrated]
    page_note = ""
    if absent:
        page_note += f" No page exists for {x('; '.join(absent))}."
    if unrated:
        page_note += (f" {x(', '.join(unrated))} {'has' if len(unrated) == 1 else 'have'} no "
                      "Glassdoor or AmbitionBox page, so absence here is not evidence of a "
                      "quiet week.")
    for i, (eid, name) in enumerate(names):
        last = i == len(names) - 1
        cells = []
        for pid in ("glassdoor", "ambitionbox"):
            pair = pairs.get((eid, pid))
            cells.append(rating_cell(pair, week_of)[0] if pair else
                         f'<span style="color:{FAINT};">No page</span>')
        gd = pairs.get((eid, "glassdoor"))
        rows.append("<tr>" + td(f"<strong>{x(name)}</strong>", last=last)
                    + td(cells[0], "right", last=last) + td(cells[1], "right", last=last)
                    + td(recommend_cell(gd, week_of) if gd else
                         f'<span style="color:{FAINT};">&mdash;</span>', "right", last=last)
                    + "</tr>")
    p.append(row(table([th("Company", width="28%"),
                        th(platforms.get("glassdoor", "Glassdoor"), "right", "26%"),
                        th(platforms.get("ambitionbox", "AmbitionBox"), "right", "26%"),
                        th("Recommend", "right", "20%")], rows)
                 + note("Out of 5, number of reviews in brackets. Recommend is Glassdoor&rsquo;s "
                        "&ldquo;would recommend to a friend&rdquo;." + page_note)))

    # 3 What's New
    p.append(section(3, "What's New", "Every new review or post this week. Click a line to "
                     "open the original."))
    if now:
        items = []
        ordered = sorted(now, key=lambda m: (m.get("post_date") or "", m.get("entity") or ""),
                         reverse=True)
        for m in ordered:
            cls = mention_class(m)
            stripe = {"positive": GOOD[1], "negative": BAD[1], "neutral": FAINT,
                      "company": "#d1d5db", "untagged": WARN[1]}[cls]
            link = (m.get("url") or "").strip() or H.profile_url(m.get("entity", ""),
                                                                   m.get("platform", ""))
            text = (m.get("one_line_summary") or m.get("title_or_snippet")
                    or "(no summary)").strip()
            text = text if len(text) <= summary_max else text[:summary_max - 1].rstrip() + "…"
            body = (f'<a href="{x(link)}" style="font:400 14px/1.5 {FONT};color:{INK};">'
                    f'{x(text)}</a>' if link else
                    f'<span style="font:400 14px/1.5 {FONT};color:{INK};">{x(text)}</span>')
            stars = H.to_int(str(m.get("rating_given") or "").strip(), 0)
            meta = " &middot; ".join(filter(None, [
                x(entities.get(m.get("entity"), m.get("entity"))),
                x(platforms.get(m.get("platform"), m.get("platform"))),
                f"posted {x(fmt_day(m.get('post_date') or m.get('captured_at')))}",
                x(who(m)),
                f"{stars}/5" if 1 <= stars <= 5 else "",
            ]))
            items.append(
                f'<tr><td style="padding:10px 0 10px 12px;border-left:3px solid {stripe};'
                f'border-bottom:1px solid {RULE};">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'border="0"><tr><td valign="top" style="font:600 11px/1.4 {FONT};'
                f'text-transform:uppercase;letter-spacing:.03em;color:{FAINT};">{meta}</td>'
                f'<td valign="top" align="right" width="120">{mention_pill(m)}</td></tr></table>'
                f'{body}</td></tr>')
        p.append(row('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                     f'border="0" style="border-collapse:collapse;">{"".join(items)}</table>'))
    else:
        p.append(row(f'<div style="font:400 14px/1.6 {FONT};color:{INK};">Nothing new on any '
                     'checked channel this week.</div>'))
    quiet = [name for eid, name in entities.items()
             if not any(m.get("entity") == eid for m in now)]
    if quiet and now:
        p.append(row(note(f"Nothing new this week: {x(', '.join(quiet))}.")))

    # 4 Themes, then job-market signals
    p.append(section(4, "Themes", "What the comments were about, which companies they "
                     "concern, and whether the theme is new, increasing or recurring."))
    start = week_of - dt.timedelta(days=7 * (rolling_weeks - 1))
    window = []
    for offset in range(rolling_weeks):
        window += H.mentions_for_week(all_mentions, start + dt.timedelta(days=7 * offset))
    window = [m for m in window if (m.get("status") or "") != "out_of_scope"]
    if baseline:
        window = list(now)
    theme_rows, recurring = theme_table(now, window, week_of, entities, max_themes)
    if theme_rows:
        p.append(row(table([th("Theme", width="24%"), th("Companies", width="30%"),
                            th("This week", "center", "13%"), th("Status", width="20%"),
                            th("Tone", "right", "13%")], theme_rows)))
    else:
        p.append(row(f'<div style="font:400 14px/1.6 {FONT};color:{INK};">No themes this week '
                     '&mdash; nothing tagged to group.</div>'))
    if recurring:
        p.append(row(note(f"Recurring across the last {rolling_weeks} weeks: " + x("; ".join(
            f"{t.replace('_', ' ').capitalize()} ({plural(s['total'], 'mention')} across "
            f"{len(s['weeks'])} weeks)" for t, s in recurring)), MUTED)))

    # Job market and candidate signals
    sig_counts = []
    for label, themes in SIGNALS:
        hits = [m for m in now if themes & set(H.split_themes(m.get("themes", "")))]
        sig_counts.append(f"{x(label)}: <strong>{len(hits)}</strong>")
    latest_market = {}
    for r in sorted(market, key=lambda r: r.get("week_of", "")):
        if (r.get("week_of") or "") <= (week_of + dt.timedelta(days=6)).isoformat():
            latest_market.setdefault(r.get("entity"), []).append(r)
    mrows = []
    for i, (eid, name) in enumerate(names):
        snaps = latest_market.get(eid, [])
        last = i == len(names) - 1
        if not snaps:
            mrows.append("<tr>" + td(x(name), last=last)
                         + td(f'<span style="color:{FAINT};">not recorded</span>', "right",
                              last=last) + td("", "right", last=last) + "</tr>")
            continue
        cur = snaps[-1]
        before = snaps[-2] if len(snaps) > 1 else None
        roles = H.to_int(cur.get("open_roles"), 0)
        move = (arrow(roles - H.to_int(before.get("open_roles"), 0), up_is_good=None)
                if before else f'<span style="color:{FAINT};">first count</span>')
        stale = cur.get("week_of") != week_of.isoformat()
        when = fmt_day(cur.get("captured_at") or cur.get("week_of"))
        mrows.append("<tr>" + td(x(name), last=last) + td(f"<strong>{roles}</strong>", "right",
                                                            last=last)
                     + td(move + (small(f"as of {x(when)}", WARN[1] if stale else FAINT)),
                          "right", last=last) + "</tr>")
    p.append(row(subhead("Job market &amp; candidate signals")
                 + f'<div style="font:400 13.5px/1.6 {FONT};color:{INK};padding-bottom:8px;">'
                 + " &nbsp;&middot;&nbsp; ".join(sig_counts) + "</div>"
                 + table([th("Company", width="44%"), th("Open roles", "right", "22%"),
                          th("Change", "right", "34%")], mrows)
                 + note("Interview experiences, salary comments, hiring posts and exit "
                        "feedback are counted from this week&rsquo;s mentions; open roles from "
                        "the company jobs pages on Glassdoor, AmbitionBox and LinkedIn.")))

    # 5 Red Flags
    p.append(section(5, "Red Flags", "Serious issues that are escalated the same day, "
                     "separately from this digest."))
    if flags:
        rows = []
        for i, r in enumerate(flags):
            last = i == len(flags) - 1
            if not r["notified"]:
                sent = f'<strong style="color:{BAD[1]};">Not yet sent</strong>'
            else:
                colour = GOOD[1] if r["on_time"] else BAD[1]
                sent = (f'{x(fmt_day(r["notified"]))}'
                        + small(f'<strong style="color:{colour};">{x(r["timing"])}</strong>'))
            rows.append("<tr>" + td(f'<strong>{x(r["entity"])}</strong>'
                                    + small(x(r["platform"])), last=last)
                        + td(x(r["reason"]) + small(x(r["status"])), last=last)
                        + td(x(fmt_day(r["raised"])), last=last)
                        + td(sent, "right", last=last) + "</tr>")
        p.append(row(table([th("Company", width="30%"), th("Trigger", width="30%"),
                            th("Found", width="18%"), th("Alert sent", "right", "22%")], rows)))
    else:
        p.append(row(box(f'<strong style="color:{INK};">None this week.</strong> '
                         f"{plural(len(now), 'mention')} checked for: a named individual, "
                         "harassment or safety, non-payment, legal or regulatory action, or "
                         "public traction.", (GOOD[0], "#4b5563"))))
    alert_line = (f"Same-day alerts: the daily scan runs at 09:00 IST on the automatic "
                  f"channels. ")
    if ready < needed:
        alert_line += (f'<strong style="color:{BAD[1]};">Alert recipients set up: {ready} of '
                       f"{needed}</strong> &mdash; until all {needed} have an address, a red "
                       "flag cannot be emailed to them the same day.")
    else:
        alert_line += f"All {needed} alert recipients are set up."
    if lagging:
        alert_line += (f" {x(', '.join(lagging))} {'is' if len(lagging) == 1 else 'are'} only "
                       "read on the weekly sweep, so an issue there can be up to a week old "
                       "when found.")
    p.append(row(note(alert_line, MUTED)))

    # Monitoring transparency, then 6 Data Link
    crow = []
    for i, c in enumerate(cover):
        last = i == len(cover) - 1
        crow.append("<tr>" + td(x(c["name"]) + small(c["how"]), last=last)
                    + td(c["state"], last=last)
                    + td(x(c["last"]), "center", last=last)
                    + td(str(c["found"]) if c["checked"] else
                         f'<span style="color:{FAINT};">&mdash;</span>', "right", last=last)
                    + "</tr>")
    p.append(row(subhead("Monitoring this week")
                 + table([th("Channel", width="30%"), th("Status", width="32%"),
                          th("Last checked", "center", "20%"), th("Found", "right", "18%")],
                         crow)
                 + note(f"{name_variants()} name variants searched across the four companies, "
                        "including short forms and common misspellings. "
                        "&ldquo;Not checked&rdquo; means nobody looked &mdash; it is not the "
                        "same as nothing found."),
                 pad="28px 32px 0 32px"))

    p.append(section(6, "Data Link", "Every mention, rating and check, with links to the "
                     "originals."))
    p.append(row(
        (f'<a href="{x(data_link)}" style="display:inline-block;background:{INK};'
         f'color:#ffffff;font:600 13px/1 {FONT};padding:11px 20px;border-radius:6px;">'
         'Open tracking sheet &rarr;</a>' if data_link and not H.is_todo(data_link) else
         f'<span style="color:{BAD[1]};">Tracking sheet link not set.</span>')
        + note(x(holdings)), pad="12px 32px 28px 32px"))

    p.append(f'<tr><td class="pad" style="background:{PANEL};padding:14px 32px;'
             f'border-top:1px solid #e5e7eb;"><div style="font:400 11.5px/1.6 {FONT};'
             f'color:{FAINT};">60-day awareness trial. Public, employment-related commentary only. '
             'Customer and product complaints are out of scope, and no individual&rsquo;s '
             'personal social media is monitored. Review sites lag 2&ndash;3 months, so read '
             'this as a trailing indicator. Confidential.</div></td></tr>')
    p.append("</table></td></tr></table>")

    extra = {
        "positive": counts_now["positive"], "negative": counts_now["negative"],
        "neutral": counts_now["neutral"], "rating_changes": rating_changes,
        "ratings_rechecked": rechecked, "not_checked": not_checked,
        "last_monitored": last_monitored.isoformat() if last_monitored else "",
        "alert_recipients_ready": ready, "alert_recipients_needed": needed,
    }
    return "".join(p), extra
