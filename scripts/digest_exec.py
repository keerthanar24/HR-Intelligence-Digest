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
    if diff is None or abs(diff) < 0.005:
        return head + small("No rating change"), False
    return head + small(f"{arrow(diff, digits=2)} since {x(since)}"), True


def recommend_cell(pair, week_of) -> str:
    latest, prev = pair
    value = H.to_float(latest.get("recommend_pct"))
    if value is None:
        return f'<span style="color:{FAINT};">&mdash;</span>'
    out = f"{value:.0f}%"
    if latest.get("week_of") == week_of.isoformat() and prev is not None:
        before = H.to_float(prev.get("recommend_pct"))
        if before is not None:
            out += small("No change" if abs(value - before) < 0.5 else
                         arrow(value - before, suffix="%"))
    return out


def theme_table(now, window, week_of, entities, limit, period=False):
    """Themes this week, each with its companies and a status.

    The status is decided over the rolling window, never on one mention:
    Single mention / New / Increasing / Recurring.
    """
    this_week = week_of.isoformat()
    prev_week = (week_of - dt.timedelta(days=7)).isoformat()
    stats = collections.defaultdict(lambda: {"now": 0, "prev": 0, "weeks": set(),
                                             "total": 0, "companies": set(), "scores": [],
                                             "by_company": collections.defaultdict(
                                                 lambda: {"pos": 0, "neg": 0, "neu": 0})})
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
            if not H.is_company_voice(m):
                tally = s["by_company"][m.get("entity")]
                tally["pos" if (score or 0) > 0 else "neg" if (score or 0) < 0 else "neu"] += 1
            s["now"] += 1
            s["companies"].add(entities.get(m.get("entity"), m.get("entity")))
            if score is not None:
                s["scores"].append(score)

    def status(s):
        earlier = s["total"] - s["now"]
        if s["total"] <= 1:
            return pill("Single mention", OFF, strong=False)
        if period:
            return (pill("Recurring", WARN, strong=False) if len(s["weeks"]) >= 2
                    else pill("New", NEUTRAL, strong=False))
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
    return rows, recurring, [(t, st, status(st), tone(st)) for t, st in current]


TINT = {"pos": "#e8f5e9", "neg": "#fdecea", "neu": "#f7f8fa"}


def tally_counts(t) -> str:
    bits = []
    if t["pos"]:
        bits.append(f'<span style="color:{GOOD[1]};font-weight:700;">&#9650;{t["pos"]}</span>')
    if t["neg"]:
        bits.append(f'<span style="color:{BAD[1]};font-weight:700;">&#9660;{t["neg"]}</span>')
    if t["neu"]:
        bits.append(f'<span style="color:{MUTED};font-weight:700;">&#9679;{t["neu"]}</span>')
    return " ".join(bits)


def tally_td(t, last, bold=False) -> str:
    """One shaded matrix cell: positive / negative / neutral counts."""
    if not (t["pos"] + t["neg"] + t["neu"]):
        return td(f'<span style="color:{FAINT};">&mdash;</span>', "center", last=last)
    lean = "pos" if t["pos"] > t["neg"] else "neg" if t["neg"] > t["pos"] else "neu"
    return (f'<td align="center" valign="top" style="padding:9px 4px;background:{TINT[lean]};'
            f'font:{"700" if bold else "400"} 12.5px/1.45 {FONT};color:{INK};white-space:nowrap;'
            f'border-bottom:{"0" if last else "1px solid #ffffff"};border-left:2px solid #ffffff;">'
            f'{tally_counts(t)}</td>')


def tally(mentions) -> dict:
    out = {"pos": 0, "neg": 0, "neu": 0}
    for m in mentions:
        if H.is_company_voice(m):
            continue
        score = H.sentiment_score(m) or 0
        out["pos" if score > 0 else "neg" if score < 0 else "neu"] += 1
    return out


def matrix_th(label, width, sub="") -> str:
    """A sentence-case header for a narrow matrix column."""
    return (f'<th align="center" width="{width}" style="padding:8px 4px;'
            f'font:700 12px/1.3 {FONT};color:{INK};border-bottom:2px solid #e5e7eb;">'
            f'{label}' + (f'<div style="font:600 11px/1.4 {FONT};color:{FAINT};padding-top:3px;">'
                          f'{sub}</div>' if sub else "") + '</th>')


def theme_matrix(current, entities) -> str:
    """Companies down the side, themes across the top.

    Each cell shows how many positive, negative and neutral mentions that
    company had on that theme, shaded by which way it leans, so a reader can
    see at a glance both what a theme is about and where it is coming from.
    """
    names = list(entities.items())
    labels = {"growth_learning": "Growth", "harassment_safety": "Harassment",
              "payroll_delay": "Payroll delay", "compensation": "Pay",
              "job_security": "Job security", "work_hours": "Work hours"}
    share = int(82 / max(1, len(current)))
    head = [th("Company", width=f"{100 - share * len(current)}%")]
    for theme, st, _status, tone_html in current:
        label = labels.get(theme, x(theme.replace("_", " ").capitalize()))
        # Theme names in sentence case: uppercase with letter-spacing overran
        # the narrow columns.
        head.append(f'<th align="center" width="{share}%" style="padding:8px 4px;'
                    f'font:700 12px/1.3 {FONT};color:{INK};border-bottom:2px solid #e5e7eb;">'
                    f'{label}<div style="font:600 11px/1.4 {FONT};padding-top:3px;">{tone_html}'
                    '</div></th>')
    empty = {"pos": 0, "neg": 0, "neu": 0}
    rows = []
    groups = names + [("__all__", "All companies")]
    for i, (eid, name) in enumerate(groups):
        last = i == len(groups) - 1
        is_all = eid == "__all__"
        line = "<tr>" + td(f"<strong>{x(name)}</strong>", last=last)
        for theme, st, _status, _tone in current:
            if is_all:
                t = {k: sum(c[k] for c in st["by_company"].values()) for k in empty}
            else:
                t = st["by_company"].get(eid, empty)
            line += tally_td(t, last, bold=is_all)
        rows.append(line + "</tr>")
    return (table(head, rows)
            + note("&#9650; positive &nbsp; &#9660; negative &nbsp; &#9679; neutral or mixed "
                   "&mdash; number of mentions. Shading shows which way each company leans on "
                   "that theme; the word under each theme is its overall tone. Company posts are "
                   "not counted."))


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
            "name": platforms.get(pid, pid), "pid": pid,
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


def period_coverage(period, week_of, platforms, all_ratings, sweeps, now, settings):
    """One row per platform over a multi-week report: weeks checked of weeks due."""
    first, last_day, _ = period
    start = H.parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    weeks, w = [], H.week_start_of(max(first, start) if start else first)
    while w <= week_of:
        weeks.append(w)
        w += dt.timedelta(days=7)
    found = collections.Counter(m.get("platform") for m in now)
    out = []
    for p in H.load_yaml("sources").get("platforms", []):
        pid = p["id"]
        rows = [r for r in all_ratings if r.get("platform") == pid] + \
               [s for s in sweeps if s.get("platform") == pid]
        no_page = pid == "indeed" and any("no indeed employer page" in (s.get("notes") or "").lower()
                                          for s in sweeps if s.get("platform") == pid)
        done = {r.get("week_of") for r in rows}
        due = [w for w in weeks if H.cadence_due(p.get("cadence", "weekly"), w, settings)]
        hit = sum(1 for w in due if w.isoformat() in done)
        dates = [d for d in (H.parse_date(r.get("captured_at") or r.get("checked_at") or "")
                             for r in rows) if d and d <= last_day]
        if no_page:
            state = pill("No company page", OFF, strong=False)
        else:
            colours = GOOD if due and hit == len(due) else WARN if hit else BAD
            state = pill(f"{hit} of {len(due)} weeks", colours, strong=False)
        out.append({
            "name": platforms.get(pid, pid), "pid": pid, "state": state,
            "last": H.day_month(max(dates)) if dates else "never",
            "found": found.get(pid, 0), "checked": bool(hit),
            "how": "Manual" if pid in {q for _, q in H.rated_profiles()} or
                   p.get("collection") not in ("feed", "api", "alert") else "Automatic",
        })
    return out


def found_late(all_mentions, week_of, now) -> list[dict]:
    """In-scope items logged during this week whose post date falls earlier."""
    first, last = week_of, week_of + dt.timedelta(days=6)
    ids = {m.get("mention_id") for m in now}
    out = []
    for m in all_mentions:
        if (m.get("status") or "") == "out_of_scope" or m.get("mention_id") in ids:
            continue
        found = H.parse_date(m.get("captured_at", ""))
        if found and first <= found <= last and (m.get("week_of") or "") < week_of.isoformat():
            out.append(m)
    return out


def rating_sites(cfg) -> list[str]:
    """Review sites that carry a rating, in the order the digest shows them.

    digest.rating_site_order puts named sites first (Glassdoor before
    AmbitionBox, as leadership asked); any other site with ratings in
    config/sources.yaml follows in config order, so a new one appears without
    a code change.
    """
    rated = [p["id"] for p in H.load_yaml("sources").get("platforms", [])
             if "ratings" in (p.get("captures") or [])]
    first = [pid for pid in (cfg.get("rating_site_order") or []) if pid in rated]
    return first + [pid for pid in rated if pid not in first]


def shared_pages() -> set[tuple[str, str]]:
    """(entity, platform) pages that also carry another company's reviews."""
    out = set()
    for p in H.load_yaml("sources").get("platforms", []):
        for eid in (p.get("shared_pages") or {}):
            out.add((eid, p["id"]))
    return out


def alert_readiness():
    """(configured, total) red-flag recipients with a real address."""
    people = H.load_yaml("recipients").get("red_flag", [])
    ready = [p for p in people if str(p.get("email", "")).strip()
             and not H.is_todo(p.get("email", ""))]
    return len(ready), len(people)


# --- the email ------------------------------------------------------------------


def render(*, week_of, week_label, prev_label, baseline, partial_notice, entities, platforms,
           now, prev, period=None, all_mentions, all_ratings, flags, lagging, data_link, holdings,
           settings) -> tuple[str, dict]:
    cfg = settings.get("digest", {})
    minimum = int(cfg.get("min_scored_mentions", 2))
    max_themes = int(cfg.get("max_themes", 4))
    rolling_weeks = int(cfg.get("rolling_theme_weeks", 4))
    summary_max = int(cfg.get("summary_max_chars", 160))
    sweeps = H.read_csv(H.SWEEPS_CSV)
    market = H.read_csv(H.MARKET_CSV)

    counts_now, counts_prev = breakdown(now), breakdown(prev)
    tracked = set(H.rated_profiles())
    pairs = {k: v for k, v in snapshot_pairs(all_ratings, week_of).items() if k in tracked}
    rating_changes = sum(1 for (e, p), pair in pairs.items()
                         if rating_cell(pair, week_of)[1])
    rechecked = any(pair[0].get("week_of") == week_of.isoformat() for pair in pairs.values())
    cover = coverage(week_of, platforms, all_ratings, sweeps, now, settings)
    not_checked = [c["name"] for c in cover if c["due"] and not c["checked"]]
    checked_dates = [c["last_date"] for c in cover if c["last_date"]]
    last_monitored = max(checked_dates) if checked_dates else None
    ready, needed = alert_readiness()
    compare = not baseline
    # The words for the period this email covers.
    span = f"in the last {period[2]} days" if period else "this week"
    if period:
        # Rating movement across the whole period: the latest reading against
        # the first one taken inside it.
        for key, (latest, _before) in list(pairs.items()):
            inside = sorted((r for r in all_ratings
                             if (r.get("entity"), r.get("platform")) == key
                             and r is not latest
                             and period[0].isoformat() <= (r.get("week_of") or "")
                             <= latest.get("week_of", "")),
                            key=lambda r: (r.get("week_of", ""), r.get("captured_at", "")))
            if inside:
                pairs[key] = (latest, inside[0])
        rating_changes = sum(1 for pair in pairs.values() if rating_cell(pair, week_of)[1])

    p: list[str] = []
    p.append(
        # Body content only, like the broadsheet: build_digest.main() wraps it
        # in the document, and send_digest.py puts it straight into the email.
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>a{text-decoration:none;}@media only screen and (max-width:900px){'
        '.shell{width:100%!important;}.pad{padding-left:18px!important;'
        'padding-right:18px!important;}.tile{display:block!important;width:100%!important;'
        'margin-bottom:8px!important;}}</style>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{RULE};"><tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" class="shell" width="880" cellpadding="0" cellspacing="0" '
        'border="0" style="width:880px;max-width:100%;background:#ffffff;border-radius:10px;'
        'overflow:hidden;">')

    # Header
    heading = (f"{x(week_label)}" if baseline else f"Week of {x(week_label)}")
    vs = "" if baseline else f" &middot; compared with {x(prev_label)}"
    monitored = (f"Last monitored {H.day_month(last_monitored, year=True)}"
                 if last_monitored else "Not yet monitored")
    p.append(
        f'<tr><td class="pad" style="background:{INK};padding:26px 32px;">'
        f'<div style="font:700 22px/1.3 {FONT};color:#ffffff;">HR Intelligence Digest</div>'
        f'<div style="font:400 13px/1.5 {FONT};color:#aab4ca;padding-top:4px;">'
        f'{heading}{vs}</div>'
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
        tile(total, "Mentions" if period else "New mentions",
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

    # 1 Headline - sentiment by company
    p.append(section(1, "Headline", f"Mentions and sentiment for each company {span}"
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
        # Two decimals: +0.25 printed to one place came out as "+0.2" (round
        # half to even), which nobody could reproduce from the chips.
        shown = label + (f" &middot; {'0.00' if abs(net) < 0.005 else f'{net:+.2f}'}"
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
        if is_total:
            name_html = f"<strong>{x(name)}</strong>"
        else:
            links = [(platforms.get(pid, pid), H.profile_url(eid, pid))
                     for pid in rating_sites(cfg)]
            links = [(n, u) for n, u in links if u]
            first = links[0][1] if links else ""
            name_html = (f'<a href="{x(first)}" style="color:{INK};font-weight:600;'
                         f'text-decoration:underline;">{x(name)}</a>' if first else x(name))
            if links:
                name_html += small(" &middot; ".join(
                    f'<a href="{x(u)}" style="color:{MUTED};text-decoration:underline;">{x(n)}</a>'
                    for n, u in links))
        rows.append("<tr>"
                    + td(name_html, last=last)
                    + td(str(len(mine)), "center", last=last, bold=is_total)
                    + td(chips, last=last)
                    + td(pill(shown, colours) + move, "right", last=last)
                    + "</tr>")
    pending = len(H.untagged_rows(now))
    pending_note = (note(f"{plural(pending, 'mention')} not yet sentiment-tagged &mdash; shown as "
                         "awaiting review and left out of the scores until a person reads "
                         f"{'it' if pending == 1 else 'them'}.", WARN[1]) if pending else "")
    p.append(row(table([th("Company", width="27%"), th("Mentions", "center", "13%"),
                        th("What was said", width="30%"), th("Overall score", "right", "30%")],
                       rows)
                 + pending_note
                 + note("Overall score = average of reviews (+1 positive, 0 neutral, &minus;1 negative); "
                        f"under {minimum} reviews reads <em>Insufficient data</em>.")))

    # 2 Rating Movement - one column per review site in config/sources.yaml,
    # so adding a site there (Indeed, Naukri, Google...) adds it here. Up to
    # three sites fit as columns; beyond that each company gets one row per
    # site, because an 880px email cannot hold more columns legibly.
    sites = rating_sites(cfg)
    names = list(entities.items())
    covered = {e for e, _ in tracked}
    unrated = [name for eid, name in names if eid not in covered]
    absent = [f"{entities.get(e, e)} on {platforms.get(pl, pl)}" for e, pl in H.absent_profiles()
              if entities.get(e) and entities.get(e) not in unrated]
    shared = shared_pages()
    site_names = " and ".join(platforms.get(pid, pid) for pid in sites) or "review"
    any_site = " or ".join(platforms.get(pid, pid) for pid in sites) or "review-site"
    p.append(section(2, "Rating Movement", f"Star ratings on {x(site_names)}, with the "
                     "change since the previous check."))

    def cell(eid, pid):
        pair = pairs.get((eid, pid))
        if not pair:
            return f'<span style="color:{FAINT};">No page</span>'
        return rating_cell(pair, week_of)[0]

    recommenders = [pid for pid in sites if H.platform_publishes(pid, "recommend_pct")]
    rows = []
    if len(sites) <= 3:
        rec = recommenders[0] if len(recommenders) == 1 else None
        for i, (eid, name) in enumerate(names):
            last = i == len(names) - 1
            line = "<tr>" + td(f"<strong>{x(name)}</strong>", last=last)
            for pid in sites:
                line += td(cell(eid, pid), "right", last=last)
            if rec:
                pair = pairs.get((eid, rec))
                line += td(recommend_cell(pair, week_of) if pair else
                           f'<span style="color:{FAINT};">&mdash;</span>', "right", last=last)
            rows.append(line + "</tr>")
        share = int(72 / (len(sites) + (1 if rec else 0)))
        head = [th("Company", width="28%")] + [
            th(x(platforms.get(pid, pid)), "right", f"{share}%") for pid in sites]
        if rec:
            head.append(th(f'Recommend<div style="font:600 11px/1.4 {FONT};text-transform:none;'
                           f'letter-spacing:0;padding-top:2px;">on {x(platforms.get(rec, rec))}'
                           '</div>', "right", f"{share}%"))
        rec_note = (f" Recommend = {x(platforms.get(rec, rec))}." if rec else "")
    else:
        flat = [(eid, name, pid) for eid, name in names for pid in sites
                if (eid, pid) in tracked]
        for i, (eid, name, pid) in enumerate(flat):
            last = i == len(flat) - 1
            first = i == 0 or flat[i - 1][0] != eid
            pair = pairs.get((eid, pid))
            rows.append("<tr>" + td(f"<strong>{x(name)}</strong>" if first else "", last=last)
                        + td(x(platforms.get(pid, pid)), last=last)
                        + td(cell(eid, pid), "right", last=last)
                        + td(recommend_cell(pair, week_of) if pair and pid in recommenders
                             else f'<span style="color:{FAINT};">&mdash;</span>', "right",
                             last=last) + "</tr>")
        head = [th("Company", width="30%"), th("Site", width="22%"),
                th("Rating", "right", "28%"), th("Recommend", "right", "20%")]
        rec_note = ""
    # "No page" already shows in the table, so absent pages need no sentence.
    page_note = ""
    if unrated:
        page_note += (f" {x(', '.join(unrated))}: no {x(any_site)} page &mdash; not evidence "
                      "of a quiet week.")
    if shared:
        who_shared = sorted({entities.get(e, e) for e, _ in shared})
        page_note += (f" &#9888; {x(', '.join(who_shared))} pages include other firms of the "
                      "same name.")
    p.append(row(table(head, rows)
                 + (note(f"{x(', '.join(unrated))}: no {x(any_site)} page &mdash; not evidence "
                         "of a quiet week.") if unrated else "")))

    # 3 Themes, then job-market signals
    p.append(section(3, "Themes", "What the comments were about, company by company."))
    start = week_of - dt.timedelta(days=7 * (rolling_weeks - 1))
    window = []
    for offset in range(rolling_weeks):
        window += H.mentions_for_week(all_mentions, start + dt.timedelta(days=7 * offset))
    window = [m for m in window if (m.get("status") or "") != "out_of_scope"]
    if baseline:
        window = list(now)
    theme_rows, recurring, current = theme_table(now, window, week_of, entities,
                                                 max(max_themes, 8), period=bool(period))
    if theme_rows:
        p.append(row(theme_matrix(current, entities)))
    else:
        p.append(row(f'<div style="font:400 14px/1.6 {FONT};color:{INK};">No themes {span} '
                     '&mdash; nothing tagged to group.</div>'))
    if recurring and not period:
        p.append(row(note(f"Recurring across the last {rolling_weeks} weeks: " + x("; ".join(
            f"{t.replace('_', ' ').capitalize()} ({plural(s['total'], 'mention')} across "
            f"{len(s['weeks'])} weeks)" for t, s in recurring)), MUTED)))

    # Job market and candidate signals: one row per company, one column per
    # signal, each counted positive / negative / neutral like the theme matrix.
    latest_market = {}
    for r in sorted(market, key=lambda r: r.get("week_of", "")):
        if (r.get("week_of") or "") <= (week_of + dt.timedelta(days=6)).isoformat():
            latest_market.setdefault(r.get("entity"), []).append(r)
    signals = [("Interviews &amp; hiring", {"interview", "onboarding"}),
               ("Pay &amp; appraisals", {"compensation", "appraisal", "payroll_delay"}),
               ("Exits &amp; layoffs", {"exits", "layoffs"}),
               ("Job security", {"job_security"})]
    mrows = []
    groups = names + [("__all__", "All companies")]
    for i, (eid, name) in enumerate(groups):
        last = i == len(groups) - 1
        is_all = eid == "__all__"
        mine = now if is_all else [m for m in now if m.get("entity") == eid]
        if is_all:
            roles_total = sum(H.to_int(v[-1].get("open_roles"), 0) for v in latest_market.values())
            roles_html = f"<strong>{roles_total}</strong>"
        else:
            snaps = latest_market.get(eid, [])
            if snaps:
                cur, before = snaps[-1], (snaps[-2] if len(snaps) > 1 else None)
                roles = H.to_int(cur.get("open_roles"), 0)
                move = (arrow(roles - H.to_int(before.get("open_roles"), 0), up_is_good=None)
                        if before else f"as of {x(fmt_day(cur.get('captured_at') or cur.get('week_of')))}")
                roles_html = f"<strong>{roles}</strong>" + small(move)
            else:
                roles_html = f'<span style="color:{FAINT};">not recorded</span>'
        line = ("<tr>" + td(f"<strong>{x(name)}</strong>", last=last)
                + td(roles_html, "center", last=last))
        for _label, themes in signals:
            line += tally_td(tally(m for m in mine
                                   if themes & set(H.split_themes(m.get("themes", "")))),
                             last, bold=is_all)
        mrows.append(line + "</tr>")
    p.append(row(subhead("Job market &amp; candidate signals")
                 + table([th("Company", width="24%"), matrix_th("Open roles", "16%")]
                         + [matrix_th(label, "15%") for label, _ in signals], mrows)
                 + note("&#9650; positive &nbsp; &#9660; negative &nbsp; &#9679; neutral "
                        f"&mdash; reviews and posts {span} that talk about each topic. Open roles "
                        "from the company jobs pages on Glassdoor, AmbitionBox and LinkedIn.")))

    # 5 Red Flags
    p.append(section(4, "Red Flags", "Serious issues that are escalated the same day, "
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
            # A direct way to the review itself: its own link when we have one,
            # otherwise the company's review page plus who wrote it and when,
            # which is enough to find it there.
            m = next((m for m in all_mentions if m.get("mention_id") == r["mention_id"]), {})
            link = (m.get("url") or "").strip()
            exact = bool(link)
            link = link or H.profile_url(m.get("entity", ""), m.get("platform", ""))
            who_when = " &middot; ".join(filter(None, [
                x((m.get("role_or_dept") or "").strip()),
                f"posted {x(fmt_day(m.get('post_date') or ''))}" if m.get("post_date") else ""]))
            review = ((f'<a href="{x(link)}" style="color:{INK};font-weight:600;'
                       f'text-decoration:underline;">Open on {x(r["platform"])} &rarr;</a>' if link else
                       f'<span style="color:{FAINT};">No link</span>')
                      + small(who_when + ("" if exact or not link else
                                          " &middot; on the company review page")))
            rows.append("<tr>" + td(f'<strong>{x(r["entity"])}</strong>'
                                    + small(x(r["platform"])), last=last)
                        + td(x(r["reason"]) + small(f'{x(r["status"])} &middot; found '
                                                    f'{x(fmt_day(r["raised"]))}'), last=last)
                        + td(review, last=last)
                        + td(sent, "right", last=last) + "</tr>")
        p.append(row(table([th("Company", width="22%"), th("Trigger", width="22%"),
                            th("Review", width="36%"), th("Alert sent", "right", "20%")], rows)))
    else:
        p.append(row(box(f'<strong style="color:{INK};">None {span}.</strong> '
                         f"{plural(len(now), 'mention')} checked for named people, harassment, "
                         "non-payment, legal action or viral posts.", (GOOD[0], "#4b5563"))))
    alert_line = "Same-day alerts: "
    if ready < needed:
        alert_line += (f'<strong style="color:{BAD[1]};">{ready} of {needed} recipients set '
                       "up.</strong>")
    else:
        alert_line += f"all {needed} recipients set up."
    if lagging:
        alert_line += (f" {x(', '.join(lagging))} {'is' if len(lagging) == 1 else 'are'} only "
                       "read on the weekly sweep.")
    p.append(row(note(alert_line, MUTED)))

    # Monitoring transparency, then 6 Data Link
    if period:
        cover = period_coverage(period, week_of, platforms, all_ratings, sweeps, now, settings)
    absent = set(H.absent_profiles())
    no_page_anywhere = {c["pid"] for c in cover if "No company page" in c["state"]}
    crow = []
    totals = collections.Counter()
    for i, c in enumerate(cover):
        last = False
        pid = c["pid"]
        line = "<tr>" + td(f"<strong>{x(c['name'])}</strong>" + small(c["how"]), last=last)
        for eid, _ in names:
            if pid in no_page_anywhere or (eid, pid) in absent:
                line += td(f'<span style="color:{FAINT};font-size:12px;">no page</span>',
                           "center", last=last)
                continue
            n = sum(1 for m in now if m.get("entity") == eid and m.get("platform") == pid)
            totals[eid] += n
            line += td(f"<strong>{n}</strong>" if n else f'<span style="color:{FAINT};">0</span>',
                       "center", last=last)
        total = sum(1 for m in now if m.get("platform") == pid)
        line += td(f"<strong>{total}</strong>", "center", last=last)
        crow.append(line + "</tr>")
    crow.append("<tr>" + td("<strong>All channels</strong>", last=True)
                + "".join(td(f"<strong>{totals[eid]}</strong>", "center", last=True)
                          for eid, _ in names)
                + td(f"<strong>{len(now)}</strong>", "center", last=True) + "</tr>")
    share = 15
    p.append(row(subhead(f"Number of mentions {span}")
                 + table([th("Channel", width="24%")]
                         + [matrix_th(x(name), f"{share}%") for _, name in names]
                         + [matrix_th("All", f"{76 - share * len(names)}%")],
                         crow),
                 pad="28px 32px 0 32px"))

    p.append(section(5, "Data Link", "Every mention, rating and check, with links to the "
                     "originals."))
    p.append(row(
        (f'<a href="{x(data_link)}" style="display:inline-block;background:{INK};'
         f'color:#ffffff;font:600 13px/1 {FONT};padding:11px 20px;border-radius:6px;">'
         'Open tracking sheet &rarr;</a>' if data_link and not H.is_todo(data_link) else
         f'<span style="color:{BAD[1]};">Tracking sheet link not set.</span>')
        + note(x(holdings)), pad="12px 32px 28px 32px"))

    p.append(f'<tr><td class="pad" style="background:{PANEL};padding:14px 32px;'
             f'border-top:1px solid #e5e7eb;"><div style="font:400 11.5px/1.6 {FONT};'
             f'color:{FAINT};">Public, employment-related commentary only. Customer and product '
             'complaints are out of scope. Confidential.</div></td></tr>')
    p.append("</table></td></tr></table>")

    extra = {
        "positive": counts_now["positive"], "negative": counts_now["negative"],
        "neutral": counts_now["neutral"], "rating_changes": rating_changes,
        "ratings_rechecked": rechecked, "not_checked": not_checked,
        "last_monitored": last_monitored.isoformat() if last_monitored else "",
        "alert_recipients_ready": ready, "alert_recipients_needed": needed,
    }
    return "".join(p), extra
