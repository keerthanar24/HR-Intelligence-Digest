#!/usr/bin/env python3
"""Print paste-ready header rows and dropdown lists for the Google Sheet.

Generated from the schema in hrintel.py, so the sheet and the scripts cannot
drift apart. A renamed or reordered column is the one failure that produces a
silently wrong digest rather than an error, which is why this exists.

    python3 scripts/sheet_setup.py              # headers + vocabularies
    python3 scripts/sheet_setup.py --headers    # just the header rows
    python3 scripts/sheet_setup.py --check "col1,col2,..."   # verify a header row

Headers print tab-separated: copy the line, click A1 in the tab, paste, and
Sheets spreads it across the columns.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

TABS = [
    ("mentions", H.MENTION_FIELDS, "One row per public item found."),
    ("ratings", H.RATING_FIELDS, "One row per entity x platform x week. Fill every week."),
    ("escalations", H.ESCALATION_FIELDS,
     "One row per red flag. Restricted - the only file that may carry a name."),
]

# Single-value columns worth locking down with Data validation > Dropdown.
# 'themes' is deliberately absent: it holds pipe-separated values, so it stays
# free text with the allowed list on a reference tab, and validate_data.py
# catches typos on import.
DROPDOWNS = [
    ("sentiment", list(H.SENTIMENT_SCORES)),
    ("author_type", H.AUTHOR_TYPES),
    ("status", H.STATUSES),
    ("red_flag_reason", H.RED_FLAG_REASONS),
    ("names_individual", ["yes", "no"]),
    ("red_flag", ["yes", "no"]),
]


def col_letter(index: int) -> str:
    """0-based column index to a spreadsheet column letter."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def normalise_header(name: str) -> str:
    """Compare headers ignoring case, spaces, hyphens and underscores, so
    'Red Flag', 'red-flag' and 'red_flag' are recognised as the same column."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def check(header: str) -> int:
    given = [c.strip() for c in header.replace("\t", ",").split(",") if c.strip()]
    for name, fields, _ in TABS:
        if given == fields:
            print(f"Matches the '{name}' schema exactly. Nothing to change.")
            return 0

    # Score each tab on normalised names so a cosmetic rename still matches.
    def score(fields):
        norm = {normalise_header(f) for f in given}
        return len(norm & {normalise_header(f) for f in fields})

    name, fields, _ = max(TABS, key=lambda t: score(t[1]))
    given_by_norm = {normalise_header(g): g for g in given}

    exact, renames, missing = [], [], []
    for field in fields:
        match = given_by_norm.get(normalise_header(field))
        if match == field:
            exact.append(field)
        elif match is not None:
            renames.append((match, field))
        else:
            missing.append(field)

    matched_norms = {normalise_header(f) for f in fields}
    extra = [g for g in given if normalise_header(g) not in matched_norms]

    print(f"Closest match: '{name}' tab "
          f"({len(exact) + len(renames)}/{len(fields)} columns recognised)\n")

    if renames:
        print(f"{len(renames)} column(s) just need renaming to the exact schema name:")
        for found, want in renames:
            print(f"  {found!r}  ->  {want}")
        print()
    if missing:
        print(f"{len(missing)} column(s) are missing and must be added:")
        for field in missing:
            print(f"  - {field}")
        print()
    if extra:
        print(f"{len(extra)} column(s) the scripts do not read (harmless, kept as-is):")
        for field in extra:
            print(f"  - {field}")
        print()

    if not missing and not renames:
        print("All required columns present under the right names. Safe to use.")
        return 0
    print("Easiest fix: paste the generated header row over row 1 "
          "(python3 scripts/sheet_setup.py --headers), then line up your data beneath it.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", action="store_true", help="print only the header rows")
    parser.add_argument("--check", metavar="HEADER_ROW",
                        help="compare a comma- or tab-separated header row against the schema")
    args = parser.parse_args()

    if args.check:
        return check(args.check)

    print("=" * 72)
    print("TAB HEADERS  -  copy a line, click A1 on that tab, paste")
    print("=" * 72)
    print("Create three tabs named exactly: mentions, ratings, escalations")
    print()
    for name, fields, note in TABS:
        print(f"--- {name}  ({len(fields)} columns) ---")
        print(f"    {note}")
        print()
        print("\t".join(fields))
        print()

    if args.headers:
        return 0

    print("=" * 72)
    print("DROPDOWNS  -  Data > Data validation > Dropdown, on the 'mentions' tab")
    print("=" * 72)
    print("This is the single highest-value thing you can do for tagging consistency,")
    print("which the brief flags as the weakest part of the method.")
    print()
    for column, values in DROPDOWNS:
        index = H.MENTION_FIELDS.index(column)
        letter = col_letter(index)
        print(f"  Column {letter} ({column}) - range {letter}2:{letter}")
        print(f"    {', '.join(values)}")
        print()

    print("  themes - leave as free text (it holds pipe-separated values such as")
    print("    'appraisal|management'). Put the allowed list on a reference tab:")
    print()
    print("    " + ", ".join(H.THEMES))
    print()
    print("    scripts/validate_data.py rejects a theme outside this list on import,")
    print("    so a typo is caught before it reaches a digest.")
    print()

    print("=" * 72)
    print("CONDITIONAL FORMATTING  -  optional, but it earns its keep")
    print("=" * 72)
    red_flag_col = col_letter(H.MENTION_FIELDS.index("red_flag"))
    status_col = col_letter(H.MENTION_FIELDS.index("status"))
    print(f"  Red background   when ${red_flag_col}2=\"yes\"        (applied to A2:V)")
    print(f"  Amber background when ${status_col}2=\"needs_review\" (applied to A2:V)")
    print("  A row that is still amber on send day has not been tagged.")
    print()

    print("=" * 72)
    print("EXPORT  -  before building each digest")
    print("=" * 72)
    print("  File > Download > Comma-separated values, one tab at a time, saved as:")
    print("    data/mentions.csv    data/ratings.csv    data/escalations.csv")
    print()
    print("  Then:  python3 scripts/validate_data.py --week <monday>")
    print("  Fix every ERROR in the sheet, re-export, and only then build the digest.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)
