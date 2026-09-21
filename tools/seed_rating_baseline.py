#!/usr/bin/env python3
"""Write the recorded rating snapshots into the workbook's Rating_Tracker tab.

data/ratings.csv is long (one row per entity x platform x week); the sheet is
wide (one row per entity per week). This pivots between them so the sheet ships
carrying the baseline instead of asking someone to retype seven numbers and
risk a transcription error against the series everything is measured from.
"""
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import hrintel as H

import openpyxl
from openpyxl.styles import Font

BOOK = sys.argv[1] if len(sys.argv) > 1 else "templates/HR_Intelligence_Master_Tracker.xlsx"

rows = H.read_csv(H.RATINGS_CSV)
if not rows:
    print("No rating snapshots recorded; nothing to seed.")
    raise SystemExit(0)

names = H.entity_names()
wide = collections.OrderedDict()
for r in rows:
    key = (r["week_of"], r["entity"])
    entry = wide.setdefault(key, {"notes": [], "checked": r.get("captured_at", "")})
    entry[r["platform"]] = r
    if r.get("notes"):
        entry["notes"].append(f"{r['platform']}: {r['notes']}")

wb = openpyxl.load_workbook(BOOK)
ws = wb["Rating_Tracker"]
font = Font(name="Arial")

for i, ((week, entity), entry) in enumerate(sorted(wide.items()), start=2):
    ab, gd = entry.get("ambitionbox", {}), entry.get("glassdoor", {})
    values = [
        dt.date.fromisoformat(week),
        names.get(entity, entity),
        H.to_float(ab.get("overall_rating")),
        H.to_int(ab.get("review_count"), 0) or None,
        H.to_float(gd.get("overall_rating")),
        H.to_int(gd.get("review_count"), 0) or None,
        dt.date.fromisoformat(entry["checked"]) if entry.get("checked") else None,
        " | ".join(entry["notes"])[:600],
    ]
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=i, column=col, value=value)
        cell.font = font

wb.save(BOOK)
print(f"Seeded {len(wide)} Rating_Tracker row(s) into {BOOK}")
for (week, entity) in sorted(wide):
    print(f"  {week}  {names.get(entity, entity)}")
