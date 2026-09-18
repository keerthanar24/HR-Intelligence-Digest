# Workbook Review — HR_Intelligence_Master_Tracker

Review of the tracker as supplied, and how the scripts consume it.

**The sheet keeps its own column names.** `scripts/import_sheet.py` translates via
`config/column_map.yaml`, so nothing needs renaming. Run:

```bash
python3 scripts/import_sheet.py HR_Intelligence_Master_Tracker.xlsx
python3 scripts/validate_data.py --week <monday>
```

Download the workbook once as `.xlsx` (**File → Download → Microsoft Excel**) — one step
instead of exporting three tabs as CSV.

## What works well

- **Dropdowns on Entity, Platform, Sentiment and Topic Category.** Tagging consistency is the
  weakest part of this method and constrained vocabularies are the fix. Good instinct.
- **`Date Logged` separate from `Date Posted`.** Many trackers collapse these. Keeping them
  apart is what makes the 2–3 month review-site lag measurable instead of invisible.
- **`Keyword_Matrix` as a tab.** Puts the search strings where the sweeper works.

## Fix before Week 1

### 1. `Rating_Tracker` overwrites its own history

The tab is one row per entity holding current state. Section 2 of the digest reports movement
**between consecutive weekly snapshots**, so overwriting a row each week destroys the series,
permanently and silently.

**Fix:** add a `Week Of` column and **append** a new row each week rather than editing in place.
After 8 weeks there should be ~32 rows, not 4.

Two smaller issues on the same tab:

- **`Total Reviews Count` is ambiguous** — one column serving two platforms that have separate
  ratings. It cannot be attributed, so the importer skips it and says so. Split into
  `AmbitionBox Reviews Count` and `Glassdoor Reviews Count` and it imports automatically.
  This matters: a 0.1 rating move on 40 reviews is one review, and the count is what tells you
  which.
- **`Week-on-Week Delta` is stored, not computed.** `build_digest.py` derives it from the
  snapshots. A hand-maintained copy drifts the first time anyone corrects a rating. Leave the
  column if it is useful to eyeball, but the digest ignores it.

### 2. "Red Flag" is in the Sentiment dropdown

`Sentiment` currently offers `Positive, Neutral, Negative, Red Flag`. A red flag is not a point
on a sentiment scale, and there is already a separate `Red Flag Escalated` column.

The cost is concrete: a red-flagged row has **no sentiment**, so it drops out of the section 1
net-sentiment figures entirely — and red-flagged items are exactly the ones that should be
pulling the average down.

The importer sets `red_flag=yes` and leaves sentiment blank rather than inventing a score, then
warns. **Fix:** remove `Red Flag` from the Sentiment list. Use the `Red Flag Escalated` column.

While editing those dropdowns, two more:

- **Each list has its own header as the first option** — `Platform ` is a selectable value in
  the Platform dropdown. Drop the leading entry from all four lists.
- **The Entity list says `RKWorld`**; the brief says `RK World`. The importer accepts both, but
  the dropdown value is what lands in every row from here on. Make it match the brief.
- **Headers carry trailing spaces** (`Entity       `, `Platform `, `Sentiment `). Harmless here
  — the importer normalises — but it breaks naive lookups and `VLOOKUP` in the sheet itself.

### 3. Three columns the deliverable needs

| Column | Why | Values |
|---|---|---|
| `Red Flag Reason` | Section 5 reports **which** of the five triggers fired. Today the sheet records only that one did | `names_individual`, `harassment_or_safety`, `non_payment`, `legal_or_regulatory`, `public_escalation_risk` |
| `Names Individual` | Trigger #1, and it drives the rule that keeps a person's name out of the digest body | `yes` / `no` |
| `Status` | Tells a tagged row from an untagged one, which is what the collector's `needs_review` flow depends on | `needs_review`, `reviewed`, `escalated`, `closed`, `out_of_scope` |

Optional but cheap: `Engagement` (likes + reposts) turns the public-escalation-risk trigger from
pure judgement into something with a threshold.

### 4. There is no escalations tab

Red flags need a log: who was notified, when, and whether they acknowledged within the SLA.
That record is the evidence the protocol was followed, and it is the only place an accused
individual's name may be written.

Add a fourth tab named `Escalations`. Headers:

```bash
python3 scripts/sheet_setup.py --headers
```

If the sheet is ever shared beyond the four recipients, move this tab to a separate file.

## Worth knowing, no action needed

- **`Topic Category` is single-select.** One topic per row is easier to keep consistent, but
  "great team, terrible pay" gets one tag instead of two, so section 4 will undercount
  co-occurring themes. Acceptable for V1 — just don't read theme counts as exhaustive.
- **`Salary & Appraisals` conflates three different problems**: paid too little
  (`compensation`), appraisal cycle issues (`appraisal`), and **not being paid at all**
  (`payroll_delay`). Only the third is a red-flag trigger, and it is among the most likely
  complaints for these entities. It currently imports as `compensation`. Splitting it into
  `Salary`, `Appraisals` and `Payroll / Non-payment` would be the single most useful change to
  that dropdown.
- **No `Layoffs` category** — currently folded into `Exit / Layoff`. Fine, but a layoff wave and
  a stream of individual resignations read very differently in a digest.

## Filling `Keyword_Matrix`

```bash
python3 scripts/alert_queries.py --format matrix
```

Prints the four columns, tab-separated, ready to paste into `Keyword_Matrix!A1`. Generated from
`config/entities.yaml`, so the matrix and the collector's filter cannot drift.

**One deliberate omission.** The classic recruiting "X-ray" targets `site:linkedin.com/in/` to
enumerate people's profiles. That is exactly the surveillance pattern the brief rules out
(`docs/00-brief.md` §4), so the generated strings target review and discussion sites only —
AmbitionBox, Glassdoor, Indeed, Reddit, Quora. Please don't add profile X-ray to that column:
the boundary is the thing that makes this programme defensible if anyone asks what it does.
