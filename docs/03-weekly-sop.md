# Weekly SOP

Budget: **3–4 hours**, once a week. If it runs materially over for two weeks running, log it —
that is a finding for the Phase 3 review, not something to absorb quietly.

**Friday.** The reporting week runs **Saturday 00:00 → Friday**, so it ends on the day it is
reported and the digest carries the week right up to the send.

| | |
|---|---|
| **09:00–11:00** | Sweep, update the sheet, draft the email |
| **15:00–17:00** | Send |

Sending mid-afternoon gets the summary to leadership before the workweek closes, and leaves
the morning for the sweep. `scripts/build_digest.py` with no arguments picks the right week on
any day: on a Friday it reports the week ending that day; on any other day, the last week that
finished.

**Week 1 is different.** The baseline digest covers the **past 60 days**, to log historical
reviews and establish the platform ratings everything later is measured against. From Week 2
the digest covers strictly the last seven days, Saturday to Friday, and reports new mentions
and week-on-week rating movement.

---

## Step 0 — Start the week (5 min)

```bash
cd HR-Intelligence-Digest
git pull
python3 scripts/collect_feeds.py            # feeds only: news, Reddit, Google Alerts
```

New rows land in `data/mentions.csv` with `status=needs_review` and no sentiment.
Nothing reaches the digest untagged without the digest saying so.

## Step 1 — Manual sweep (90–120 min)

Work the platform list in `docs/02-source-map.md`, priority 1 first. For each entity × platform:

- [ ] AmbitionBox — new reviews, interviews, salaries; **record rating + review count**
- [ ] Glassdoor — new reviews, interviews; **record rating + review count**
- [ ] LinkedIn — company page posts and comments; public post search on the aliases
- [ ] X — logged-out search per alias; note engagement counts
- [ ] Reddit — check the subs the feed tends to miss
- [ ] Quora — weekly, alert-assisted
- [ ] Indeed / YouTube / Google Reviews — fortnightly: **trial weeks 1, 3, 5, 7**

Don't work the rotation from memory. `make sweep` prints the worksheet for the week and marks
each fortnightly channel **DUE this week** or **NOT due this week**, counted from the trial
start so it cannot drift. Indeed carries interview experiences as well as reviews.

Search strings for each platform: `python3 scripts/alert_queries.py --format manual`.

For every new item, log a mention — either by typing a row into the sheet's `Raw_Data_Log`
tab, or from the command line, which validates as it goes:

```bash
python3 scripts/log_mention.py -e rk_world -p ambitionbox -d 2026-09-20 \
  -s "Ex-employee says FnF pending two months, HR not replying" \
  --sentiment very_negative --themes payroll_delay,exits \
  --author ex_employee --url https://... --flag non_payment
```

`--vocab` lists the allowed values; `--list` shows what is already logged for the week. A
duplicate URL is refused, and a red flag prints the alert command rather than waiting for
Friday.

### Knowing when you have them all

Record the rating and review count **first**, then log the reviews. The count is the
platform's own tally, so the change in it is exactly how many new reviews exist:

```bash
python3 scripts/log_rating.py --status
```

```
RK World Infocom  ambitionbox  3.00  (54 reviews)  <-- 3 new review(s), 1 logged: 2 TO READ

10 review(s) exist that have not been logged as mentions:
  RK World Infocom     ambitionbox  3 to read
  Westbury Kommerce    ambitionbox  2 to read
```

That is the sweep's target, not a warning. Work until it says nothing is outstanding, and
"did I get everything?" stops being a feeling and becomes arithmetic. The same check runs in
the digest, so a shortfall is disclosed to the four rather than hidden.

**Two reasons the numbers can legitimately disagree**, so do not hunt indefinitely:

- A review was **edited or removed**, so the count moved without a new review to find.
- The page shows a **ratings** count rather than a written-reviews count. Glassdoor
  distinguishes the two, and a star-only rating has no text to log.

In either case note it and move on. The digest says the table is incomplete, which is the
honest outcome.

**This is the step that fills sections 1, 3 and 4.** A rating snapshot is one number for a
whole company; a mention is one row per review, and the digest cannot summarise reviews it
has never been given.
For every priority-1 page, add a row to `data/ratings.csv` **even when nothing changed** — the
rating series needs the zero weeks as much as the movement.

Two rules that save time later:

- Record the URL. A row without a link cannot be checked by anyone else.
- Write the one-line summary while the review is still on screen. Coming back to it costs
  three times as long.

## Step 2 — Tag (45–60 min)

Every row with `status=needs_review` needs:

- `one_line_summary` — one sentence, factual, no interpretation
- `sentiment` — `very_negative` / `negative` / `neutral` / `mixed` / `positive` / `very_positive`
- `themes` — from the fixed list, pipe-separated (`appraisal|management`)
- `author_type`, `names_individual`, `red_flag` (+ `red_flag_reason` if yes)
- `status` → `reviewed`, `escalated`, or `out_of_scope`

Rubric and worked examples: `docs/05-sentiment-and-themes.md`. Tag the whole week in one
sitting — consistency within a week matters more than consistency with three weeks ago.

Mark anything customer-side as `out_of_scope` rather than deleting it. Knowing how much noise
we filtered is itself a Phase 3 input.

## Step 3 — Red flags (10 min, but **same day, always**)

```bash
python3 scripts/red_flags.py --scan
```

The scan suggests rows whose wording looks like a trigger. **A human decides.** For anything
that is a genuine trigger:

1. Set `red_flag=yes` and a `red_flag_reason` on the row.
2. Add a row to `data/escalations.csv`.
3. `python3 scripts/red_flags.py --alert <MENTION_ID>` and send it the same day.

Red flags do **not** wait for the Friday digest. Full protocol: `docs/04-red-flag-protocol.md`.

## Step 4 — Export and validate (10 min)

Working in Google Sheets? Export first — the scripts read the CSVs, not the sheet
(`docs/08-google-sheet-setup.md`):

**File → Download → Comma-separated values**, one tab at a time, into `data/mentions.csv`,
`data/ratings.csv`, `data/escalations.csv`. Then:

```bash
python3 scripts/validate_data.py --week $(python3 -c "import sys;sys.path.insert(0,'scripts');import hrintel as H;print(H.last_complete_week())")
```

Fix every ERROR **in the sheet**, then re-export — a fix made in the CSV is lost on the next
export. WARNINGs are judgement calls; an empty week is a warning, and it is fine.

## Step 4b — The completeness gate

The build refuses while the review counts say more arrived than was logged:

```
NOT SENDABLE — 2 review(s) still to read.
  RK World Infocom / AmbitionBox: 3 new, 1 logged, 2 TO READ
    https://www.ambitionbox.com/reviews/r-k-world-infocom-reviews
```

This used to be a caption inside the email — *"not everything was captured"* — and the digest
went out anyway. That told four people the table under-reports the week and gave none of them a
way to act on it. The sweep is finished when the logged rows account for every review the counts
say arrived, so that is the gate now, and the lines above are the worklist: open the URL, read
the reviews you have not logged, log them, build again.

Three things stop the build, and they are different failures:

| | What it means |
|---|---|
| `N TO READ` | the count moved further than the logged rows explain — reviews are unread |
| `NOT SWEPT` | no rating snapshot this week; nobody opened that profile at all |
| `no previous snapshot` | only one snapshot exists, so there is nothing to subtract |

The second one is the important one. Before, a profile nobody swept produced no rows and read
exactly like a quiet week — the check could only fail on profiles someone had already looked at,
which is the wrong way round. Every profile in `config/sources.yaml` that carries a review count
is now enumerated up front and has to come back accounted for. A page that does not exist
(Robust Kommerce on AmbitionBox, recorded as `none`) is not expected and never counts as a gap.

Week 1 is exempt from the third: a baseline week has no previous snapshot by definition. It is
**not** exempt from the second.

`--allow-gaps` builds anyway, for a mid-sweep look. Use it knowing the email will **not** say the
week is incomplete — the disclosure was removed along with the caption, because an incomplete
digest is no longer supposed to reach anyone.

## Step 5 — Build and send (20 min)

Refresh the sheet first, then build. Section 6 tells four people the sheet holds this week's raw
data, so it has to hold it by the time they click:

```bash
python3 tools/export_to_workbook.py     # CSVs -> workbook
python3 scripts/build_digest.py --stdout
```

Then upload the refreshed workbook to the Google Sheet behind the data link. (`weekly_run.py`
does the export for you as its step 3; the upload is still a person's job.)

Writes `out/digest-<week>.html` and `out/digest-<week>.txt`.

1. Read the plain-text version top to bottom. Does the headline match what you actually saw?
2. Open the HTML file in a browser, select all, paste into the email body.
   **Body only — no attachments.** That is in the brief.
3. Send to the four recipients in `config/recipients.yaml`.
4. Sanity-check before hitting send:
   - No individual is named anywhere in the body.
   - Every row in What's New has a working link.
   - The data link in section 6 opens the tracking sheet, and `Raw_Data_Log` shows this
     week's rows — not just headers. Section 6 states the counts; check they match section 3.
   - The build exited 0. A non-zero exit means reviews are still unread; the digest is not
     finished, whatever it looks like on screen.

## Step 6 — Record the week, then commit (5 min)

```bash
python3 scripts/log_week.py
git add data/ && git commit -m "Week of <date>: <n> mentions, <n> red flags" && git push
```

`log_week.py` asks two questions the data cannot answer for itself:

- **How many minutes the whole cycle took.** The brief budgets 3–4 hours a week. Whether that
  held is the first thing Phase 3 asks, and by week 8 nobody remembers.
- **How many of this week's mentions were genuinely new to the four.** A digest that only
  repeats what the four already knew through normal channels is costing four hours a week to
  tell them nothing — which is a finding, but only if it was written down at the time.

Everything else in the row — mentions, red flags, out-of-scope, platforms swept — it counts
from the data. Week 1 is counted over the sixty-day baseline window, the same window the
week 1 digest reported, so the two agree.

Answer it the same Friday. `python3 scripts/log_week.py --show` prints the running average
against the budget; it refuses to record the same week twice.

The `out/` directory is gitignored — the data is the record, the email is a rendering of it.

---

## Phase 1 baseline sweep (one-off, 8–10 hours)

Before weekly execution starts, run a deeper sweep to establish the baseline:

1. Fill in every `TODO:` in `config/sources.yaml`, `config/settings.yaml` and
   `config/recipients.yaml`. Run `python3 scripts/validate_data.py` until the errors clear.
2. Stand up the sheet: `python3 scripts/sheet_setup.py` prints the headers, dropdowns and
   formatting rules. See `docs/08-google-sheet-setup.md`.
3. Confirm the alias list with HR — especially former names
   (`needs_confirmation` in `config/entities.yaml`).
4. Create the Google Alerts: `python3 scripts/alert_queries.py --format google` prints the
   queries; paste each RSS URL back into `config/sources.yaml` and set `enabled: true`.
   See the alerts layer in `docs/02-source-map.md` for what alerts can and cannot cover.
5. Capture the **current** rating and review count for every entity on Glassdoor and
   AmbitionBox into `data/ratings.csv`. This is week zero; every later movement is measured
   from here.
6. Read back the last ~90 days of reviews on the priority-1 platforms and log them. Do not
   send them as a digest — they are context for judging what "normal" looks like, and the
   2–3 month site lag means they describe the quarter before last.
7. Do a dry run: build a digest for a past week and circulate it to the four for format
   feedback, clearly marked as a sample.

## Empty weeks

A week with no mentions is a valid result. Send the digest anyway, with the sections showing
zero. Do not pad it, do not skip it. The pattern of quiet weeks is data, and skipping sends
cannot be told apart from forgetting to send.
