#!/usr/bin/env python3
"""One command: is this project healthy, and what is it waiting on?

Everything here is already available - validate_data.py, the smoke tests,
log_sweep --show, log_market --status. Four commands, and remembering which
four is its own small tax. This runs them and prints one answer.

    python3 scripts/status.py

Exit code is 0 when nothing is broken. Outstanding INPUTS - an address nobody
has supplied yet, a count nobody has taken - are reported but do not fail it:
they are work remaining, not faults, and a status command that always exits
non-zero is one people stop reading.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402


def run(*args: str) -> tuple[int, str]:
    result = subprocess.run([sys.executable, *args], capture_output=True,
                            text=True, cwd=ROOT)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def head(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    broken = []

    head("Code")
    code, out = run(os.path.join("tests", "smoke_test.py"))
    passed = out.count("  ok    ")
    if code == 0:
        print(f"  ok       {passed} checks pass")
    else:
        failed = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
        print(f"  BROKEN   {len(failed)} check(s) failing")
        for line in failed[:5]:
            print(f"           {line}")
        broken.append("tests")

    head("Data and config")
    code, out = run(os.path.join("scripts", "validate_data.py"))
    for line in out.splitlines():
        if line.startswith(("ERROR", "WARNING", "note")):
            print(f"  {line}")
    if "0 error(s)" not in out:
        broken.append("validator")

    settings = H.load_yaml("settings")
    # NOT last_complete_week(). That is right for a digest - it reports a week
    # that has run its course - but mid-week-1 there is no complete week yet,
    # and it reaches back to a week before the trial began and reports every
    # channel unswept. The week being WORKED ON is the one to show, and it
    # never precedes the trial.
    trial_start = H.parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    week = H.week_start_of(dt.date.today())
    if trial_start and week < trial_start:
        week = H.week_start_of(trial_start)
    # weeks_into_trial is 0-based, so `if number` hides week 1 - the only week
    # that exists yet - behind the generic label.
    number = H.weeks_into_trial(week, settings)
    label = "Current week" if number is None else f"Week {number + 1}"
    head(f"{label} sweep — {H.fmt_week(week)}")
    names = H.platform_names()
    unswept = H.unverified_channels(week, settings) if hasattr(H, "unverified_channels") else []
    checked = H.channels_checked(week)
    print(f"  {len(checked)} channel(s) recorded as swept")
    still = [p for p in unswept if p not in checked]
    if still:
        print(f"  NOT SWEPT  {', '.join(names.get(p, p) for p in still)}")

    head("Waiting on a person")
    waiting = []
    recipients = H.load_yaml("recipients") or {}
    unset = {p.get("name") for block in ("digest", "red_flag")
             for p in (recipients.get(block) or [])
             if H.is_todo(str(p.get("email") or "")) or not p.get("email")}
    if unset:
        waiting.append(f"{len(unset)} recipient address(es): "
                       f"{', '.join(sorted(n for n in unset if n))}"
                       "  ->  scripts/set_recipients.py <name> <email>")
    programme = settings.get("programme", {})
    for field in ("owner", "reply_to"):
        if H.is_todo(str(programme.get(field) or "")):
            waiting.append(f"programme.{field} in config/settings.yaml")

    entities = H.entity_names()
    recorded = {r.get("entity") for r in H.read_csv(H.MARKET_CSV)
                if r.get("week_of") == week.isoformat()}
    if len(recorded) < len(entities):
        waiting.append(f"job market / salary: {len(recorded)}/{len(entities)} counted"
                       "  ->  scripts/log_market.py --worksheet")
    if not any(r.get("week_of") == week.isoformat()
               for r in H.read_csv(H.WEEKLY_LOG_CSV)):
        waiting.append("effort log for this week  ->  scripts/log_week.py")

    if waiting:
        for item in waiting:
            print(f"  -  {item}")
    else:
        print("  nothing")

    print()
    if broken:
        print(f"BROKEN: {', '.join(broken)}. Fix before anything else.")
        print("  If these are new to you, check you have pulled: "
              "git pull origin $(git branch --show-current)")
        return 1
    print("Nothing is broken." + (f" {len(waiting)} input(s) outstanding." if waiting else ""))
    return 0


if __name__ == "__main__":
    H.run_report(main)
