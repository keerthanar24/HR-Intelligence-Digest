# What is left to do

State as of 2026-09-21 (Google Alerts now connected — see section 4). Everything here is an **input only a person can supply** — none of it is
blocked on code. Ordered by what unblocks the most.

Re-check this list any time with:

```bash
python3 scripts/validate_data.py      # config and data gaps
python3 scripts/log_rating.py --status # this week's sweep progress
```

---

## 1. The 60-day review back-read — BLOCKING, and the big one

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

## 2. RK Group's all-locations figures — do before week 2

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

## 3. Two identity confirmations

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

## 6. Upload the workbook to the Google Sheet

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
