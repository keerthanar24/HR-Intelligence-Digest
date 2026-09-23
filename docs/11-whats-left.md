# What is left to do

State as of 2026-09-23 (job-market trends and salary insights are now built — the last two scope gaps are closed). Everything here is an **input only a person can supply** — none of it is
blocked on code. Ordered by what unblocks the most.

Re-check this list any time with:

```bash
python3 scripts/validate_data.py      # config and data gaps
python3 scripts/log_rating.py --status # this week's sweep progress
```

---

## 1. ~~The 60-day review back-read~~ — DONE 2026-09-22

All seven pages were read back sixty days and logged by the programme owner. The week 1 digest
now reports the baseline window (28 Jul – 25 Sep), not a strict seven days.

**The result is itself the finding, and it is the most important early input to the Month 2
decision:**

| | |
|---|---|
| Reviews inside 60 days, across all seven pages | **3** |
| Pages with nothing at all in 60 days | **4 of 7** |
| Red flags | **0** |
| Out of scope (a marketplace/seller complaint, correctly refused) | 1 |

Three reviews in two months is roughly one every three weeks across the whole group. Most weeks
will therefore be genuinely empty — that is the real velocity, not a gap in the sweep. Whether
3–4 hours a week is worth spending on it is exactly the question `docs/07-phase3-review.md`
asks at week 8, and "Stop" is a live answer. The effort log (`python3 scripts/log_week.py`)
records the hours each week so that answer rests on numbers rather than recollection.

---

## Superseded — the original entry

**Why it matters.** `data/mentions.csv` has **0 rows**. Sections 1, 3, 4 and 5 of the digest are
built entirely from mentions, so until reviews are logged every digest is empty no matter what
else is fixed. The ratings baseline is done; the reviews behind those ratings are not.

**What to do.** Open each page, read back 60 days, and log every employment-related review:

| Entity | Platform | Page |
|---|---|---|
| RK Group | AmbitionBox | https://www.ambitionbox.com/reviews/r-dot-k-dot-group-reviews |
| RK World Infocom | AmbitionBox | https://www.ambitionbox.com/reviews/r-k-world-infocom-reviews |
| Westbury Kommerce | AmbitionBox | https://www.ambitionbox.com/reviews/westbury-kommerce-reviews |
| RK Group | Glassdoor | https://www.glassdoor.co.in/Reviews/RK-Group-Reviews-E653077.htm |
| RK World Infocom | Glassdoor | https://www.glassdoor.co.in/Reviews/Rk-Worldinfocom-Reviews-E8268877.htm |
| Robust Kommerce | Glassdoor | https://www.glassdoor.co.in/Reviews/Robust-Reviews-E1882698.htm |
| Westbury Kommerce | Glassdoor | https://www.glassdoor.co.in/Reviews/Westbury-Kommerce-Reviews-E6166527.htm |

Robust Kommerce has no AmbitionBox page — that is recorded in config and is not a gap.

One row per review, either typed into the sheet's `Raw_Data_Log` tab or from the command line,
which validates as it goes:

```bash
python3 scripts/log_mention.py --vocab       # the allowed values, first
python3 scripts/log_mention.py \
    -e rk_world -p ambitionbox -d 2026-09-20 \
    -s "Ex-employee says FnF pending two months, HR not replying" \
    --sentiment very_negative --themes payroll_delay,exits \
    --author ex_employee --url https://... --flag non_payment
```

**Stay inside the boundary.** Employment commentary only. Customer and seller complaints,
product reviews and anything from an individual's personal social account are out of scope —
`log_mention.py` refuses those rather than relying on memory.

---

## 2. ~~RK Group's all-locations figures~~ — DONE 2026-09-22

Both baselines were the city-filtered view, and the correction was large:

| | Was (city view) | Is (all locations) |
|---|---|---|
| AmbitionBox | 2.70 / 27 reviews | **3.30 / 151** |
| Glassdoor | 3.60 / 16, 56% recommend | **3.70 / 30, 64% recommend** |

AmbitionBox's location dropdown settled it: Bengaluru shows exactly 27, the number that had
been recorded as the whole company. Left uncorrected, the first week-on-week comparison would
have reported around +124 new AmbitionBox reviews that had been there for months, and the
completeness gate would have demanded somebody read and log all of them.

**The mistake revealed something worth keeping.** Bengaluru rates RK Group 2.70 against 3.30
company-wide, and Bangalore 3.60 against 3.70 — the same city is the weaker half on both
platforms. The location split is New Delhi 39, Bengaluru 27, Mumbai 6, Ahmedabad 5, Hyderabad 4,
Lucknow 4, Daman & Diu 3. If the programme is ever extended, a location-level view for RK Group
looks like it would carry real signal.

The AmbitionBox sub-scores were cleared: they were read off the Bengaluru view, and beside an
all-locations headline they would have read as company-wide figures.

## Superseded — the original entry

Both RK Group baselines are **Bengaluru-filtered**, not the whole company:

- AmbitionBox 2.70 / 27 reviews — Bengaluru subset
- Glassdoor 3.60 / 16 reviews — Bangalore subset

Every week-on-week comparison is measured against these, so the scope needs settling now. Either
re-read both pages unfiltered and re-record, or decide Bengaluru-only is what you want and the
note stays as the standing caveat.

```bash
python3 scripts/log_rating.py -e rk_group -p ambitionbox -r <rating> -c <count> --replace
```

---

## 3. Still outstanding — state as of 2026-09-23

Nothing below is blocked on code. Ordered by what blocks the most.

### Blocking the send

| | |
|---|---|
| Four recipient addresses | `python3 scripts/set_recipients.py <name> <email>` — sets both the `digest` and `red_flag` blocks at once |
| `programme.owner` | `config/settings.yaml:6` — who runs the desk |
| `programme.reply_to` | `config/settings.yaml:7` — the address it comes from |

Do not edit `config/recipients.yaml` by hand: the same four are listed twice, and an
address set for the digest but not for red_flag is now a validator **error** — the
weekly send would look finished while escalations had nowhere to go.

The baseline also does not close until **25 Sep**, so nothing goes out before then
whatever else is filled in.

### Blocking a complete week 1

- **YouTube** — the last unswept channel. Four searches; read the COMMENTS, not the
  videos. `python3 scripts/log_sweep.py --checked youtube` once done.
- **Job market and salary entries — 0/4.** The digest now says the count was not taken
  rather than rendering silence, but that is a disclosure, not a substitute.
  `python3 scripts/log_market.py --status --week 2026-09-19`.
- **Two held LinkedIn posts** — the store-launch campaign, 2026-08-18 and 2026-09-08.
  In scope only if the body mentions hiring, jobs or the team. They sit commented out
  in `data/linkedin-posts-2026-09-19.txt` with the question beside them.

### Worth doing, blocks nothing

- **The Robust Kommerce Google Alert still carries `OR "Robust Results"`** from the old
  query, so it keeps pulling in another company. Regenerate with
  `python3 scripts/alert_queries.py --entity robust_kommerce --format google`.
- **Three back-read rows hold no verbatim text** (M-20260808-001, M-20260829-001,
  M-20260905-002). Their summaries are unverifiable at the Month 2 review.
- **`collector.user_agent` says `contact: TODO`** — `config/settings.yaml:47`. A bot
  with no contact address is the kind a site blocks without asking.
- **Confirm the Google Sheet is shared** with the four recipients.

### Optional, costs money or time

- **X bearer token** — without it the four X searches are skipped and X stays manual.
- **Reddit API credentials** — two of four queries still hit HTTP 429 from CI.
- **YouTube Data API collector** — free, roughly an hour's work, would make YouTube
  automatic instead of the one channel still swept by hand every week.
- **Claim the Glassdoor employer profiles** — closes the last red-flag gap.

---

## Superseded — the identity confirmations


~~**`Robust Results`**~~ **Resolved 2026-09-21: it was never a name of Robust Kommerce**, and the
alias is removed. One follow-up: the live Google Alert for Robust Kommerce was created with the
old query and still contains `OR "Robust Results"`. Edit it to match
`python3 scripts/alert_queries.py --entity robust_kommerce --format google`, or it keeps pulling
in another company.

~~**Glassdoor employer 1882698**~~ **Resolved 2026-09-21: it IS Robust Kommerce.** The programme
owner first said it was not, then supplied the Overview page for that same employer id as the
company's own Glassdoor page. Taken as confirmed on the second, specific statement; the 4.00 / 7
baseline stands.

Robust Kommerce has **no AmbitionBox page**, so Glassdoor is its only review-site cover. Its
seven reviews therefore carry more weight than the raw count suggests — there is no second
platform to cross-check them against.

---

## 4. Missing source URLs

~~**Four Google Alerts RSS feeds.**~~ **Done.** All five alerts are connected and verified on a
live run — each feed reports its own query as its title, which confirms every URL is bound to the
entity it belongs to. They return 0 items today because a Google Alert only carries items indexed
after it was created; they fill from here.

~~**RK World Infocom's LinkedIn page.**~~ **Done.** The platform map is complete: every entity
has a page on every platform that carries one.

**X bearer token** (optional) — set `X_BEARER_TOKEN` as a repository secret and the four X
searches start running. Without it they are skipped and X stays manual.

**Reddit API credentials** (optional) — two of four Reddit queries still hit HTTP 429 from a
shared CI address, even after four retries. More waiting will not fix it; an API client id
would.

---

## 5. Who the digest is from and to

Three separate things, all needed before anything can be sent:

- **The four recipient addresses** in `config/recipients.yaml` — Mahendra, Sonal, Ramesh, Akshay.
- **`programme.owner`** in `config/settings.yaml` — the name of whoever runs the desk.
- **`programme.reply_to`** in `config/settings.yaml` — the address the digest comes from and
  replies go to. Without it the send has no From address and refuses.

None of these block the build or the sweep; they block only the send.

---

## 6. ~~Upload the workbook to the Google Sheet~~ — DONE 2026-09-22

The original sheet was never populated, so the workbook was uploaded to Drive as a new file and
`digest.data_link` now points at it. **This repeats every week**: export, upload, replace — it is
the one step nothing here can do, because writing to Google Sheets needs credentials this
project does not have.

## Superseded — the original entry

`templates/HR_Intelligence_Master_Tracker.xlsx` now carries every field the schema holds
(22 / 26 / 15 columns) and the rating baseline. The Google Sheet behind the data link still has
the old structure. Nothing in this repo can write to Google Sheets, so someone has to upload it.

After that, the weekly refresh is `python3 tools/export_to_workbook.py`, then re-upload.

---

## 7. Claim the Glassdoor employer profiles — optional, closes the last red-flag gap

Neither RK World Infocom nor Robust Kommerce has a claimed profile. Claiming is free and makes
the platform email you on every new review, which is the only route to genuinely same-day notice
on a site that cannot be polled. Without it, review-site red flags are found at the Friday sweep,
not the same day.

---

## Not outstanding

The digest's six sections, the red-flag protocol with same-day evidence, the completeness gate,
the alias register (35 spellings across four entities), the Glassdoor and AmbitionBox platform
map, the tracking sheet schema, and the GitHub automation are all built and tested.
