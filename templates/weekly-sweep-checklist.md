# Friday Sweep Checklist — week of ______________

Reporting week: **Saturday → Friday**. Sweep 09:00–11:00, send 15:00–17:00.
Full instructions: `docs/03-weekly-sop.md`

Swept by: ______________   Started: ______  Finished: ______  (budget 3–4 h)

---

## 09:00 · Start (5 min)

- [ ] `git pull`
- [ ] `make sweep` — prints every URL and what to capture
- [ ] `make auto` — runs the feed collection (Reddit, news, X if configured)

## 09:05 · Review sites — the part only a person can do (60–75 min)

For each page: record the **rating and review count**, then copy **any review newer than
last Friday**. Sort by newest, not relevance.

**AmbitionBox** — highest volume, rates ~1 point harsher than Glassdoor

| | Rating + count | New reviews copied |
|---|---|---|
| RK Group | ☐ | ☐ |
| RK World Infocom | ☐ | ☐ |
| Robust Kommerce | — *no page on this platform; the digest says so in section 2* | — |
| Westbury Kommerce | ☐ | ☐ |

**Glassdoor**

| | Rating + count | New reviews copied |
|---|---|---|
| RK Group | ☐ | ☐ |
| RK World Infocom | ☐ | ☐ |
| Robust Kommerce | ☐ | ☐ |
| Westbury Kommerce | ☐ | ☐ |

> Robust Kommerce is listed on Glassdoor as plain **"Robust"** (employer id 1882698), confirmed
> by the programme owner on 2026-09-21. It has **no AmbitionBox page**, so Glassdoor is its only
> review-site cover.

> RK Group's baseline was corrected on 2026-09-22 to the **all-locations** view on both
> platforms (3.30/151 on AmbitionBox, 3.70/30 on Glassdoor). Every week from here reads the
> same all-locations page — if a location filter is ever applied, the series breaks.

**LinkedIn** — company page posts and their comments, plus a public post search

- [ ] RK Group · [ ] RK World Infocom *(page URL still needed)* · [ ] Robust Kommerce · [ ] Westbury Kommerce

**Every week, no fixed page**

- [ ] X — logged-out search, unless the API token is set
- [ ] Quora — answers naming the group
- [ ] Reddit — check the subs by hand; the feed sees posts, not comments

**Fortnightly rotation — trial weeks 1, 3, 5, 7.** Don't guess: `make sweep` prints
**DUE this week** or **NOT due this week** beside each one, counted from the trial start.

- [ ] Indeed *(reviews and interview experiences)* · [ ] YouTube comments · [ ] Google Reviews *(employment only — skip customer and product reviews)*

## 10:15 · Log what you found (30 min)

Either paste it all to Claude and let it tag and log, or do it yourself:

```bash
python3 scripts/log_rating.py -e <entity> -p <platform> -r <rating> -c <count> \
    --recommend <pct>          # Glassdoor only; AmbitionBox does not print one
    # add --ceo-approval <pct> if the Glassdoor page shows one
python3 scripts/log_mention.py --vocab        # allowed values
python3 scripts/log_mention.py -e … -p … -d … -s "…" --sentiment … --themes …
```

- [ ] Every rating recorded — `python3 scripts/log_rating.py --status` shows 7/7
- [ ] Every new review logged as a mention, with **both** the review's own words
      (its title or first line) and your one-line summary — the first is refused if missing
- [ ] Star rating and department recorded where the page shows them
- [ ] Customer/product items marked `out_of_scope` (kept, not deleted)

## 10:45 · Red flags — same day, not Friday afternoon (15 min)

```bash
python3 scripts/red_flags.py --scan
```

- [ ] Each suggestion confirmed or dismissed **by a person**
- [ ] For each confirmed flag: row updated, escalation logged, alert sent **today**

## 11:00 · Build and check (15 min)

```bash
python3 scripts/validate_data.py --week <saturday>
python3 scripts/build_digest.py --stdout
```

- [ ] No ERRORs
- [ ] Not marked **PARTIAL WEEK**
- [ ] Read the plain-text version top to bottom — does the headline match what you saw?
- [ ] No individual named anywhere in the body
- [ ] Every What's New row links correctly
- [ ] Section 6 link opens the sheet

## 15:00–17:00 · Send

- [ ] Paste the HTML body into the email — **body only, no attachments**
- [ ] To: Mahendra, Sonal, Ramesh, Akshay
- [ ] Record the week — **while it is fresh**, not at week 8:

  ```bash
  python3 scripts/log_week.py
  ```

  It asks two things nothing else records: the minutes the whole cycle took, and how many of
  this week's mentions were genuinely **new** to the four. Both are Phase 3 questions
  (`docs/07-phase3-review.md`); everything else it stores it counts from the data.

- [ ] `git add data/ && git commit && git push`
- [ ] Over budget two weeks running is a Phase 3 finding — `python3 scripts/log_week.py --show`

Notes / anything odd this week:

________________________________________________________________

________________________________________________________________
