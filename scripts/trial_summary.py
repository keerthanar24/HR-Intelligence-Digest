#!/usr/bin/env python3
"""The 60-day trial evaluation, built from the tracking data.

docs/07-phase3-review.md lists what the end-of-trial review needs. Everything
on that list that can be counted is counted here, so nobody reconstructs eight
weeks from memory: coverage, volume, red flags, noise, recurring themes,
rating movement, job market and effort. The recommendation itself stays with
the programme owner - this report lays out which of the pre-agreed decision
signals the data supports, and stops there.

    python3 scripts/trial_summary.py                 # trial to date
    python3 scripts/trial_summary.py --until 2026-11-14

Writes out/trial-summary-<date>.html and .txt. Run it any time for an interim
view; it says "interim" until the 60 days are up.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import digest_exec as X  # noqa: E402
import hrintel as H  # noqa: E402

TRIAL_DAYS = 60


def weeks_between(first: dt.date, last: dt.date) -> list[dt.date]:
    out, week = [], H.week_start_of(first)
    while week <= last:
        out.append(week)
        week += dt.timedelta(days=7)
    return out


def build(until: dt.date, settings: dict) -> tuple[str, str]:
    start = H.parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    if not start:
        raise SystemExit("programme.trial_start is not set in config/settings.yaml")
    end = start + dt.timedelta(days=TRIAL_DAYS - 1)
    last = min(until, end)
    final = until >= end
    weeks = [w for w in weeks_between(start, last) if w + dt.timedelta(days=6) <= last]
    entities, platforms = H.entity_names(), H.platform_names()

    mentions = H.read_csv(H.MENTIONS_CSV)
    in_trial = [m for m in mentions if (m.get("week_of") or "") >= start.isoformat()
                and (m.get("week_of") or "") <= last.isoformat()]
    # Week 1 carries the 60-day back-read; it is reported, but kept apart from
    # the weekly run-rate so the baseline does not inflate it.
    base = H.baseline_window(H.week_start_of(start), settings)
    baseline = ([m for m in H.mentions_in(mentions, base[0], base[1])
                 if (m.get("status") or "") != "out_of_scope"] if base else [])
    base_ids = {m.get("mention_id") for m in baseline}
    weekly = [m for m in in_trial if (m.get("status") or "") != "out_of_scope"
              and m.get("mention_id") not in base_ids]
    scope = baseline + weekly
    noise = [m for m in in_trial if (m.get("status") or "") == "out_of_scope"]

    per_week = collections.Counter(m.get("week_of") for m in weekly)
    empty_weeks = sum(1 for w in weeks[1:] if not per_week.get(w.isoformat()))
    run_weeks = max(len(weeks) - 1, 1)
    per_week_avg = len(weekly) / run_weeks

    # 1. Coverage: weeks each channel was checked against weeks it was due.
    sweeps, ratings = H.read_csv(H.SWEEPS_CSV), H.read_csv(H.RATINGS_CSV)
    cov_rows = []
    for p in H.load_yaml("sources").get("platforms", []):
        pid = p["id"]
        due = sum(1 for w in weeks if H.cadence_due(p.get("cadence", "weekly"), w, settings))
        done = {s.get("week_of") for s in sweeps if s.get("platform") == pid}
        done |= {r.get("week_of") for r in ratings if r.get("platform") == pid}
        checked = sum(1 for w in weeks if w.isoformat() in done)
        found = sum(1 for m in scope if m.get("platform") == pid)
        cov_rows.append((platforms.get(pid, pid), checked, due, found))

    # 2. Volume and sentiment by entity
    ent_rows = []
    for eid, name in entities.items():
        mine = [m for m in scope if m.get("entity") == eid]
        c = X.breakdown(mine)
        label, _, net = X.overall(mine, int(settings.get("digest", {})
                                           .get("min_scored_mentions", 2)))
        ent_rows.append((name, len(mine), c["positive"], c["neutral"], c["negative"],
                         c["company"], label))

    # 3. Red flags
    flags = [m for m in scope if H.is_yes(m.get("red_flag"))]
    escalations = {e.get("mention_id"): e for e in H.read_csv(H.ESCALATIONS_CSV)}
    same_day = 0
    for m in flags:
        e = escalations.get(m.get("mention_id"), {})
        raised, sent = H.parse_date(e.get("raised_at", "")), H.parse_date(e.get("notified_at", ""))
        same_day += bool(raised and sent and sent <= raised)

    # 4. Recurring themes: two or more mentions in two or more weeks
    themes = collections.defaultdict(lambda: {"n": 0, "weeks": set(), "who": set()})
    for m in scope:
        for t in H.split_themes(m.get("themes", "")):
            themes[t]["n"] += 1
            themes[t]["weeks"].add(m.get("week_of"))
            themes[t]["who"].add(entities.get(m.get("entity"), m.get("entity")))
    recurring = sorted(((t, s) for t, s in themes.items() if s["n"] >= 2 and len(s["weeks"]) >= 2),
                       key=lambda ts: -ts[1]["n"])

    # 5. Rating movement: first and latest reading per profile
    by_key = collections.defaultdict(list)
    for r in ratings:
        if (r.get("week_of") or "") <= last.isoformat():
            by_key[(r.get("entity"), r.get("platform"))].append(r)
    rate_rows = []
    for (eid, pid), snaps in sorted(by_key.items()):
        snaps.sort(key=lambda r: r.get("week_of", ""))
        a, b = H.to_float(snaps[0].get("overall_rating")), H.to_float(snaps[-1].get("overall_rating"))
        rate_rows.append((entities.get(eid, eid), platforms.get(pid, pid),
                          a, b, len(snaps), snaps[-1].get("week_of", "")))

    # 6. Effort and signal quality, from the Friday log
    log = [r for r in H.read_csv(H.WEEKLY_LOG_CSV) if (r.get("week_of") or "") <= last.isoformat()]
    minutes = [H.to_int(r.get("minutes_spent"), 0) for r in log]
    new_to_four = sum(H.to_int(r.get("new_to_recipients"), 0) for r in log)

    # Decision signals from docs/07, evaluated - not decided.
    signals = [
        ("At least one red flag reached the four first through this programme",
         "Institutionalise", bool(flags)),
        ("Consistent volume (5+ mentions a week across the group)",
         "Institutionalise or automate", per_week_avg >= 5),
        # "Nothing new to the four" is only knowable from the Friday log.
        ("Mostly empty weeks, no red flags, nothing new to the four",
         "Stop", (empty_weeks >= run_weeks / 2 and not flags and new_to_four == 0)
         if log else None),
        ("Volume concentrated in one entity",
         "Expand or narrow scope",
         bool(scope) and max(r[1] for r in ent_rows) >= 0.6 * len(scope)),
    ]

    # ---- HTML, in the digest's executive look
    p = []
    status = "Final" if final else f"Interim, to {H.day_month(last, year=True)}"
    p.append('<meta charset="utf-8"><table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0" style="background:{X.RULE};"><tr><td align="center" '
             'style="padding:28px 12px;"><table role="presentation" width="640" cellpadding="0" '
             'cellspacing="0" border="0" style="width:640px;max-width:100%;background:#ffffff;'
             'border-radius:10px;overflow:hidden;">')
    p.append(f'<tr><td style="background:{X.INK};padding:26px 32px;">'
             f'<div style="font:700 22px/1.3 {X.FONT};color:#ffffff;">60-day trial evaluation</div>'
             f'<div style="font:400 13px/1.5 {X.FONT};color:#aab4ca;padding-top:4px;">'
             f'HR Intelligence Digest &middot; {H.day_month(start)} &ndash; '
             f'{H.day_month(end, year=True)} &middot; {X.x(status)}</div></td></tr>')

    p.append(X.section(1, "Coverage", "Weeks each channel was actually checked, against the "
                       "weeks it was due."))
    rows = [("<tr>" + X.td(X.x(n), last=i == len(cov_rows) - 1)
             + X.td(f"{c} of {d}", "center", last=i == len(cov_rows) - 1)
             + X.td(str(f), "right", last=i == len(cov_rows) - 1) + "</tr>")
            for i, (n, c, d, f) in enumerate(cov_rows)]
    p.append(X.row(X.table([X.th("Channel", width="50%"), X.th("Weeks checked", "center", "25%"),
                            X.th("Mentions found", "right", "25%")], rows)))

    p.append(X.section(2, "Volume and sentiment", f"{len(scope)} in-scope mentions "
                       f"({len(baseline)} from the 60-day back-read, {len(weekly)} from the "
                       f"{run_weeks} weekly runs, {per_week_avg:.1f} a week). "
                       f"{empty_weeks} of {run_weeks} weekly runs found nothing."))
    rows = []
    for i, (name, n, pos, neu, neg, co, label) in enumerate(ent_rows):
        last_row = i == len(ent_rows) - 1
        rows.append("<tr>" + X.td(X.x(name), last=last_row) + X.td(str(n), "center", last=last_row)
                    + X.td(f"{pos} / {neu} / {neg}" + (X.small(f"+{co} company posts") if co else ""),
                           "center", last=last_row)
                    + X.td(X.x(label), "right", last=last_row) + "</tr>")
    p.append(X.row(X.table([X.th("Company", width="34%"), X.th("Mentions", "center", "18%"),
                            X.th("Pos / Neu / Neg", "center", "24%"),
                            X.th("Overall", "right", "24%")], rows)
                   + X.note(f"Noise: {len(noise)} item(s) logged and ruled out of scope "
                            f"({(len(noise) / max(len(in_trial), 1)):.0%} of what the weekly runs "
                            "returned).")))

    p.append(X.section(3, "Red flags", "Issues that met one of the five triggers."))
    p.append(X.row(X.box(f"<strong>{len(flags)}</strong> raised; {same_day} alerted the same "
                         "day. Whether any reached the four first through this programme, or "
                         "was acted on elsewhere, is for the review to confirm.")))

    p.append(X.section(4, "Recurring themes", "Themes with two or more mentions in two or "
                       "more weeks. A single mention is never called a pattern."))
    if recurring:
        rows = [("<tr>" + X.td(X.x(t.replace("_", " ").capitalize()), last=i == len(recurring) - 1)
                 + X.td(X.x(", ".join(sorted(s["who"]))), last=i == len(recurring) - 1)
                 + X.td(f"{s['n']} in {len(s['weeks'])} weeks", "right",
                        last=i == len(recurring) - 1) + "</tr>")
                for i, (t, s) in enumerate(recurring)]
        p.append(X.row(X.table([X.th("Theme", width="30%"), X.th("Companies", width="40%"),
                                X.th("Seen", "right", "30%")], rows)))
    else:
        p.append(X.row(X.note("No theme recurred across weeks.", X.INK)))

    p.append(X.section(5, "Rating movement", "First and latest Glassdoor and AmbitionBox "
                       "readings in the trial."))
    rows = []
    for i, (name, plat, a, b, n, when) in enumerate(rate_rows):
        last_row = i == len(rate_rows) - 1
        diff = None if a is None or b is None else b - a
        rows.append("<tr>" + X.td(X.x(name) + X.small(X.x(plat)), last=last_row)
                    + X.td(f"{a:.2f}" if a is not None else "&mdash;", "center", last=last_row)
                    + X.td(f"{b:.2f}" if b is not None else "&mdash;", "center", last=last_row)
                    + X.td(X.arrow(diff, digits=2) + X.small(f"{n} reading(s)"), "right",
                           last=last_row) + "</tr>")
    p.append(X.row(X.table([X.th("Profile", width="40%"), X.th("First", "center", "18%"),
                            X.th("Latest", "center", "18%"), X.th("Change", "right", "24%")],
                           rows)))

    p.append(X.section(6, "Effort and signal", "From the Friday effort log."))
    if log:
        hours = sum(minutes) / 60
        p.append(X.row(X.box(f"{len(log)} week(s) logged: {hours:.1f} hours in total, "
                             f"{hours / len(log):.1f} a week against the 3&ndash;4 hour budget. "
                             f"{new_to_four} item(s) were new information to the four.")))
    else:
        p.append(X.row(X.box("No weeks recorded in the effort log yet. Hours and "
                             "&ldquo;new to the four&rdquo; cannot be counted from the data; "
                             "record them with <code>scripts/log_week.py</code> before the "
                             "review.", X.WARN)))

    p.append(X.section(7, "Recommendation", "The decision signals agreed before the trial "
                       "(docs/07-phase3-review.md), checked against the data. The "
                       "recommendation is the programme owner&rsquo;s."))
    rows = [("<tr>" + X.td(X.x(text), last=i == len(signals) - 1)
             + X.td(X.x(points), last=i == len(signals) - 1)
             + X.td(X.pill("Yes", X.GOOD) if held else
                    X.pill("Not yet known", X.WARN) if held is None else X.pill("No", X.OFF),
                    "right",
                    last=i == len(signals) - 1) + "</tr>")
            for i, (text, points, held) in enumerate(signals)]
    p.append(X.row(X.table([X.th("Signal", width="54%"), X.th("Points toward", width="28%"),
                            X.th("Holds", "right", "18%")], rows)
                   + X.note("Tagging consistency (re-tag 10 early rows blind) is a manual "
                            "check for the meeting."), pad="10px 32px 28px 32px"))
    p.append("</table></td></tr></table>")

    # ---- text
    t = [f"60-DAY TRIAL EVALUATION - {status}",
         f"{H.day_month(start)} to {H.day_month(end, year=True)}", "",
         "1. COVERAGE (weeks checked / due, mentions found)"]
    t += [f"- {n}: {c} of {d}, {f} found" for n, c, d, f in cov_rows]
    t += ["", f"2. VOLUME: {len(scope)} in scope ({len(baseline)} back-read, {len(weekly)} weekly, "
               f"{per_week_avg:.1f}/week); {empty_weeks} of {run_weeks} weekly runs empty; "
               f"{len(noise)} ruled out of scope"]
    t += [f"- {n}: {c} mentions, {p_}/{u}/{g} pos/neu/neg, {label}"
          for n, c, p_, u, g, _co, label in ent_rows]
    t += ["", f"3. RED FLAGS: {len(flags)} raised, {same_day} alerted same day", "",
          "4. RECURRING THEMES"]
    t += [f"- {k}: {s['n']} in {len(s['weeks'])} weeks ({', '.join(sorted(s['who']))})"
          for k, s in recurring] or ["- none"]
    t += ["", "5. RATING MOVEMENT"]
    t += [f"- {n} / {pl}: {a} -> {b} ({k} readings)" for n, pl, a, b, k, _w in rate_rows]
    t += ["", "6. EFFORT: " + (f"{sum(minutes) / 60:.1f} h over {len(log)} logged weeks; "
                               f"{new_to_four} new to the four" if log else "not logged yet")]
    t += ["", "7. DECISION SIGNALS (recommendation is the owner's)"]
    t += [f"- [{'x' if held else '?' if held is None else ' '}] {text} -> {points}"
          for text, points, held in signals]
    return "".join(p), "\n".join(t)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--until", help="last day to include (YYYY-MM-DD); default today")
    parser.add_argument("--out-dir", default=H.OUT_DIR)
    args = parser.parse_args()
    until = H.parse_date(args.until) if args.until else dt.date.today()
    html, text = build(until, H.load_yaml("settings"))
    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.join(args.out_dir, f"trial-summary-{until.isoformat()}")
    with open(stem + ".html", "w", encoding="utf-8") as fh:
        fh.write(f"<!doctype html><html><head><title>60-day trial evaluation</title></head>"
                 f"<body>{html}</body></html>")
    with open(stem + ".txt", "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    print(f"\nHTML: {stem}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
