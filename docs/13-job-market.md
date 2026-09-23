# Capturing the job market and salary insights

The project scope asks for two things that are neither a review nor a rating:
**job-market trends** and **salary insights**. This is how they get into the digest.

Until they are recorded, section 2 of the digest carries a disclosure instead of a
table — *"not recorded this week for any entity. No conclusion about hiring should be
drawn from its absence: the count was not taken."* That is deliberate. Silence there
would read as *no hiring to report*, which is a different claim from *nobody counted*.
Filling it in replaces the disclosure with the figures.

---

## What the two numbers mean

**Open roles** — how many distinct vacancies the entity is advertising. The programme
is about the group *as an employer*, so its own hiring volume is the job-market trend
that matters. A spike in openings beside a run of exit reviews is the correlation this
digest exists to surface, and neither half shows it alone.

**Salary entries** — how many salary submissions the platform holds for that company.
**The count, never a figure.** A company-wide median averages a warehouse packer
against a finance manager and produces a number nobody should act on. The count says
how much salary data employees have volunteered, and whether it is growing — which is
a real signal about willingness to talk.

Neither is useful as a level. The digest reports the **change**, so the first week's
job is to establish a baseline, not to find something interesting. Three open roles is
neither good nor bad until you know it was one last week.

---

## Step 1 — get the pages

```bash
python3 scripts/log_market.py --worksheet --week 2026-09-19
```

Five pages per entity, three for Robust Kommerce (it has no AmbitionBox page, so none
is offered — a derived URL there would be a page that cannot exist).

| Page | What to read |
|---|---|
| LinkedIn Jobs | the Jobs tab on the company page — count the postings |
| Glassdoor Jobs | the count beside the Jobs tab, e.g. `Jobs (3)` |
| AmbitionBox jobs | the `N jobs` heading |
| Glassdoor Salaries | `N salaries for M job titles` — take **N** |
| AmbitionBox salaries | `based on N salaries` near the top — take **N** |

**A page that 404s is not 0.** Say so instead, and the URL gets fixed. Recorded as 0,
a broken link is ticked off as an empty page every week for eight weeks.

---

## Step 2 — the one rule that is easy to get backwards

The two figures **do not combine the same way.**

**Roles — de-duplicate.** Open the Jobs pages, look at the actual listings, and count
how many *distinct* vacancies there are. The same "Store Manager, Rajkot" on LinkedIn
and AmbitionBox is **one** role. You are counting how many people the entity is trying
to hire; summing the platforms turns one job into a hiring push. No script can tell
that two postings are the same job, so this number is a person's judgement.

**Salaries — add them up.** These are separate contributor pools: an employee who
submitted to AmbitionBox did not thereby submit to Glassdoor. The sum is how much
salary data exists, which is the thing being tracked. This one *is* arithmetic, so the
tool does it.

---

## Step 3 — fill in the sheet

`data/job-market-2026-09-19.txt`, one line per entity:

```
#                   roles   glassdoor  ambitionbox
rk_group              3        12          40
rk_world              0         8          51
robust_kommerce       1         5                 # no AmbitionBox page
westbury_kommerce     0         2          18
```

First number is roles, already de-duplicated. The rest are salary counts, one per page,
which get summed. `0` is a real answer and worth recording; a blank line is an error,
because recording a blank as `0` would invent a count nobody took.

```bash
python3 scripts/log_market.py --file data/job-market-2026-09-19.txt --week 2026-09-19
```

```
  RK Group               3 role(s),   52 salary entries  (12 + 40)
  RK World Infocom       0 role(s),   59 salary entries  (8 + 51)
  Robust Kommerce        1 role(s),    5 salary entries  (5)
  Westbury Kommerce      0 role(s),   20 salary entries  (2 + 18)
```

The per-page split is kept in the `source` column so that when a total moves next week,
it can be traced to a platform rather than guessed at.

---

## Step 4 — use the same platforms every week

This is the error that hides. The digest reports the **change**, so a week counted from
three platforms against a week counted from two reports a movement nobody made — and
both figures look like perfectly plausible counts. Nothing in the numbers can catch it.

`log_market.py` compares this week's source against last week's and warns when they
differ. That is the only place the error is catchable, which is why the source is
recorded automatically rather than left to be typed in.

If a platform genuinely has to be dropped — a page is deleted, an account is lost —
record it anyway that week with a note, so the discontinuity is in the data rather than
in somebody's memory.

---

## Expect small numbers

These are four regional companies whose entire 60-day employee-voice output was three
reviews. **Zero open roles is a completely plausible answer**, and recording it is the
point: it is the baseline that makes week 2's `+3 roles` mean something.
