# Google Sheet Setup

The sheet is the working surface; the scripts read CSV exports of it. This page covers
standing it up and the weekly export step.

Tracking sheet: set in `config/settings.yaml` → `digest.data_link`. That URL is what section 6
of every digest links to.

## Tabs and headers

Three tabs, named exactly **`mentions`**, **`ratings`**, **`escalations`**.

Do not hand-type the headers. Generate them so they cannot drift from what the scripts read:

```bash
python3 scripts/sheet_setup.py --headers
```

Copy a line, click **A1** on that tab, paste — Sheets spreads it across the columns.

Already built the sheet with your own column names? Check it rather than guessing:

```bash
python3 scripts/sheet_setup.py --check "<paste your header row here>"
```

It matches ignoring case, spaces and underscores, so it distinguishes *"this column just needs
renaming"* from *"this column is missing"*.

**A renamed or missing column is the one failure mode that produces a silently wrong digest
rather than a loud error.** Worth the two minutes.

Column-by-column meanings: `docs/06-tracking-sheet-spec.md`.

## Dropdowns

The brief names judgement-based sentiment tagging as the weakest part of the method. Dropdowns
are the cheapest fix available — they turn a free-text guess into a six-way choice.

```bash
python3 scripts/sheet_setup.py        # prints the exact columns, ranges and value lists
```

Set **Data → Data validation → Dropdown** on `sentiment`, `author_type`, `status`,
`red_flag_reason`, `names_individual` and `red_flag`.

`themes` stays free text, because it holds pipe-separated values (`appraisal|management`). Put
the 16 allowed themes on a reference tab for the sweeper to copy from;
`scripts/validate_data.py` rejects anything outside the list on import, so a typo is caught
before it reaches a digest rather than after.

## Conditional formatting

Two rules, both worth having:

- Red background where `red_flag = yes`
- Amber background where `status = needs_review`

A row still amber on send day has not been tagged. The digest will say so in section 1, but
seeing it in the sheet mid-week is better than reading it in the email on Friday.

## Sharing

- The four recipients plus the desk owner. Nobody else during the trial.
- **View access is enough** for the four — only the sweeper edits.
- The `escalations` tab may carry the name of an accused individual. If the sheet is shared
  more widely than the four at any point, move that tab to a separate, restricted file.

## Weekly export

Before building the digest:

1. **File → Download → Comma-separated values**, one tab at a time
2. Save as `data/mentions.csv`, `data/ratings.csv`, `data/escalations.csv`
3. `python3 scripts/validate_data.py --week <saturday>`
4. Fix every ERROR **in the sheet**, re-export, then build

Fix errors in the sheet rather than in the CSV — the next export overwrites the CSV and you
would lose the correction.

## Why not connect directly to the Sheets API

It is possible, and it would remove the export step. It also needs a Google Cloud project, a
service account, a credential to store and rotate, and someone to own it. For a 60-day trial
producing one email a week, a three-click export is the right trade. Revisit it at the Phase 3
review if the programme continues — it is on the "automate further" list, not a gap.
