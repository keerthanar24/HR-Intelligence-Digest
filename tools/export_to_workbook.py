#!/usr/bin/env python3
"""Write the canonical CSVs into the tracker workbook, so the data link shows data.

The digest's section 6 hands recipients a link to this workbook and calls it
"the raw data". Until now only the rating baseline was ever written into it:
opening the link showed four rating rows, an empty Raw_Data_Log and an empty
Escalations tab, which is not the raw data behind the digest - it is the
schema for it.

This is the other half of scripts/import_sheet.py. That reads the sheet into
the CSVs; this writes the CSVs back into the sheet. Both are driven by
config/column_map.yaml, so a column added there works in both directions with
no code change, and the pair round-trips losslessly (tests/smoke_test.py).

  python3 tools/export_to_workbook.py [workbook.xlsx] [--dry-run]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import hrintel as H

import openpyxl
from openpyxl.styles import Font

DEFAULT_BOOK = os.path.join(H.ROOT, "templates", "HR_Intelligence_Master_Tracker.xlsx")

# Written as real numbers so the sheet can sort and chart them, and so a
# recipient who filters the tab is not filtering text that looks like a number.
NUMERIC = {"review_count", "recommend_pct", "ceo_approval_pct", "engagement",
           "rating_given", "overall_rating", "work_life_balance",
           "salary_benefits", "job_security", "career_growth", "culture"}
INTEGER = {"review_count", "recommend_pct", "ceo_approval_pct", "engagement"}
DATES = {"week_of", "captured_at", "post_date", "raised_at", "notified_at", "closed_at"}
# Fields whose value vocabulary is shared but whose column_map key differs.
VALUE_MAP_FOR = {"red_flag_reason": "red_flag_reason", "status": "status",
                 "entity": "entity", "platform": "platform", "sentiment": "sentiment",
                 "themes": "themes", "author_type": "author_type",
                 "red_flag": "red_flag", "names_individual": "red_flag",
                 "severity": "severity", "reason": "red_flag_reason"}
# 'Status' means different things on different tabs: a mention is
# needs_review/reviewed/escalated, an escalation is open/acknowledged/closed.
# Without this the escalation tab showed a value its own dropdown rejects.
VALUE_MAP_BY_TAB = {"escalations": {"status": "escalation_status"}}


def norm(name) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def reverse_values(cfg: dict) -> dict[str, dict[str, str]]:
    """canonical id -> the sheet's own spelling.

    Several sheet labels can map to one id ('Ex-Employee' and 'Ex Employee'
    both mean ex_employee). The first spelling listed wins, which is the one
    the dropdown offers.
    """
    out: dict[str, dict[str, str]] = {}
    for kind, mapping in cfg.get("values", {}).items():
        table = out.setdefault(kind, {})
        for label, canonical in mapping.items():
            table.setdefault(str(canonical), str(label))
    return out


def as_cell(field: str, raw, rev: dict, tab: str = ""):
    """One canonical value as the sheet should hold it."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    if field in DATES:
        parsed = H.parse_date(text)
        return parsed if parsed else text
    if field in NUMERIC:
        number = H.to_int(text, None) if field in INTEGER else H.to_float(text)
        return number if number is not None else text
    kind = VALUE_MAP_BY_TAB.get(tab, {}).get(field) or VALUE_MAP_FOR.get(field)
    if kind and kind in rev:
        table = rev[kind]
        # themes is multi-valued; the sheet shows all of them rather than
        # dropping every tag after the first.
        if "|" in text:
            return " | ".join(table.get(part.strip(), part.strip())
                              for part in text.split("|") if part.strip())
        return table.get(text, text)
    return text


def columns_for(tab: str, cfg: dict, ws) -> tuple[dict[str, int], list[str]]:
    """{canonical field: column index} plus the fields with no column."""
    spec = cfg["tabs"][tab]
    header = {norm(c.value): i for i, c in enumerate(ws[1], start=1) if c.value}
    index, missing = {}, []
    for field, spellings in spec.get("columns", {}).items():
        found = next((header[norm(s)] for s in spellings if norm(s) in header), None)
        if found:
            index[field] = found
        else:
            missing.append(field)
    return index, missing


def clear_data(ws, ncols: int, first: int, last: int) -> None:
    for r in range(first, last + 1):
        for c in range(1, ncols + 1):
            ws.cell(row=r, column=c).value = None


def find_tab(wb, names: list[str]):
    wanted = {norm(n) for n in names}
    for name in wb.sheetnames:
        if norm(name) in wanted:
            return wb[name]
    return None


def write_long(wb, tab: str, rows: list[dict], cfg: dict, font) -> tuple[int, list[str]]:
    """A tab whose shape matches the schema one-for-one."""
    ws = find_tab(wb, cfg["tabs"][tab]["sheet_names"])
    if ws is None:
        return 0, [f"no {cfg['tabs'][tab]['sheet_names'][0]} tab in the workbook"]
    index, missing = columns_for(tab, cfg, ws)
    rev = reverse_values(cfg)
    ncols = max(index.values(), default=1)
    clear_data(ws, ncols, 2, ws.max_row)
    for r, row in enumerate(rows, start=2):
        for field, column in index.items():
            cell = ws.cell(row=r, column=column,
                           value=as_cell(field, row.get(field), rev, tab))
            cell.font = font
    return len(rows), [f"{tab}: no column for {f}" for f in missing]


def write_ratings(wb, rows: list[dict], cfg: dict, font) -> tuple[int, list[str]]:
    """The rating tab is wide: one row per entity per week, a block per platform."""
    spec = cfg["tabs"]["ratings"]
    ws = find_tab(wb, spec["sheet_names"])
    if ws is None:
        return 0, ["no Rating_Tracker tab in the workbook"]
    index, missing = columns_for("ratings", cfg, ws)
    index.pop("platform", None)          # the column name carries the platform
    rev = reverse_values(cfg)
    header = {norm(c.value): i for i, c in enumerate(ws[1], start=1) if c.value}

    wide: dict[tuple[str, str], dict] = collections.OrderedDict()
    for row in rows:
        entry = wide.setdefault((row["week_of"], row["entity"]),
                                {"captured_at": row.get("captured_at", ""),
                                 "captured_by": row.get("captured_by", "")})
        entry[row["platform"]] = row

    names = H.entity_names()
    ncols = max(list(index.values()) + list(header.values()), default=1)
    clear_data(ws, ncols, 2, ws.max_row)
    problems = [f"ratings: no column for {f}" for f in missing if f != "platform"]

    for r, ((week, entity), entry) in enumerate(sorted(wide.items()), start=2):
        flat = {"week_of": week, "entity": names.get(entity, entity),
                "captured_at": entry.get("captured_at", ""),
                "captured_by": entry.get("captured_by", ""), "notes": ""}
        for field, column in index.items():
            value = (flat[field] if field == "entity"
                     else as_cell(field, flat.get(field), rev, "ratings"))
            ws.cell(row=r, column=column, value=value).font = font
        for platform, block in (spec.get("per_platform") or {}).items():
            source = entry.get(platform, {})
            for field, spellings in block.items():
                column = next((header[norm(s)] for s in spellings if norm(s) in header), None)
                if column is None:
                    problems.append(f"ratings: no {platform} column for {field}")
                    continue
                ws.cell(row=r, column=column,
                        value=as_cell(field, source.get(field), rev, "ratings")).font = font
    return len(wide), problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbook", nargs="?", default=DEFAULT_BOOK)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written without saving")
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.workbook)
    font = Font(name="Arial")
    problems: list[str] = []
    counts: dict[str, int] = {}

    for tab, path in (("mentions", H.MENTIONS_CSV), ("escalations", H.ESCALATIONS_CSV)):
        written, issues = write_long(wb, tab, H.read_csv(path), H.load_yaml("column_map"), font)
        counts[tab] = written
        problems += issues
    written, issues = write_ratings(wb, H.read_csv(H.RATINGS_CSV),
                                    H.load_yaml("column_map"), font)
    counts["ratings"] = written
    problems += issues

    if not args.dry_run:
        wb.save(args.workbook)
    where = os.path.relpath(args.workbook, H.ROOT)
    print(f"{'Would write' if args.dry_run else 'Wrote'} into {where}:")
    for tab in ("mentions", "ratings", "escalations"):
        print(f"  {tab:12} {counts[tab]} row(s)")
    if problems:
        print("\nNotes:")
        for problem in problems:
            print(f"  - {problem}")
    if not counts["mentions"]:
        print("\nRaw_Data_Log is empty because data/mentions.csv is. Anyone opening the "
              "data link sees the schema, not the week's findings — log the sweep first "
              "(scripts/log_mention.py) and run this again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
