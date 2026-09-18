# Platform Source Map

Machine-readable half: `config/sources.yaml`. This page is the narrative — what to search,
how often, and what we are and are not allowed to automate.

## Compliance position

Glassdoor, AmbitionBox and LinkedIn **block automated collection and offer no public API**.
We do not build scrapers for them, and we do not work around a block. Version 1 is a
manual/scripted hybrid:

- **Manual sweep** — a person opens the page on schedule and records what is new.
- **Feeds** — the collector reads only feeds a publisher offers openly for machine reading
  (Google Alerts RSS, Reddit search RSS, news RSS).
- **Alerts** — standing alerts that email or feed to the desk.

`scripts/collect_feeds.py` touches feeds only. If a platform later offers a licensed API, that
is a Phase 3 decision, not a shortcut to take mid-trial.

We also do not open private, restricted or connection-gated content, and we do not create fake
accounts. If it takes a login to a personal network to see it, it is out of scope.

## Priority 1 — weekly, manual

### AmbitionBox
Expected to be the highest-volume source for India.

- Open each entity's company page (URLs in `config/sources.yaml` → `platforms.ambitionbox.urls`).
- Record **every new review** since the last sweep into `data/mentions.csv`.
- Record the **overall rating and review count into `data/ratings.csv` every week**, even when
  nothing new appeared. Section 2 of the digest is a time series; a missed week leaves a hole.
- Also check the Interviews and Salaries tabs — interview experiences are in scope.

### Glassdoor
Same routine as AmbitionBox: reviews, rating, review count, interviews. Lower expected volume
for these entities, but the rating movement still matters.

### LinkedIn
- Company page: posts, and the comments under them.
- Public post search on the alias list, restricted to the past week.
- Ex-employee updates only where they appear publicly and are about the employment (e.g. a
  public "why I left" post). **Do not browse individual profiles to compile a picture of a
  named person** — that is the surveillance boundary in `docs/00-brief.md` §4.

## Priority 2

### X — weekly, manual (logged-out search)
Search each alias plus an employment term. Look for complaints and threads gaining traction.
Record `engagement` (likes + reposts) — it drives the public-escalation-risk red flag.
If the group holds an X API plan, the recent-search endpoint may be used instead; put the
bearer token in the environment, never in this repo.

### Reddit — weekly, feed-assisted
`scripts/collect_feeds.py` reads Reddit's public search RSS for each alias. Manually check
`r/india`, `r/developersIndia`, `r/jobs`, `r/IndianWorkplace` and the relevant city subs for
threads the feed missed — Reddit search is unreliable for exact phrases.

### Indeed — fortnightly, manual
Company reviews and interview experiences.

## Priority 3

### Quora — weekly, alert-assisted
"What is it like to work at…" style answers. A standing Google Alert usually catches these.

### YouTube — fortnightly, manual
Comments on videos about the group. **Employment-related comments only** — skip the customer
and product commentary that will make up most of the thread.

### Google Reviews — fortnightly, manual
Employment-related reviews only. On a Google Business listing these are a small minority;
most are customer reviews and are out of scope.

### News / web — weekly, feed
Google Alerts RSS per entity. Catches layoffs, labour disputes and hiring coverage.

## Setting up Google Alerts (Phase 1, once)

1. Go to <https://www.google.com/alerts>.
2. Create one alert per entity. Use quoted aliases OR-ed together, e.g.
   `"Robust Kommerce" OR "Robust Commerce" OR "Robust Komerce"`.
3. Set **How often: as-it-happens**, **Sources: automatic**, **Deliver to: RSS feed**.
4. Copy the feed URL into the matching entry under `feeds:` in `config/sources.yaml` and set
   `enabled: true`.
5. Run `python3 scripts/collect_feeds.py --dry-run` to confirm it parses before switching it on.

Expect Google Alerts to be noisy for a short brand name like "RK Group". The collector's
employment-context filter removes most of it; raise `exclude_terms` for whatever gets through.

## Search string template

For manual sweeps, combine one alias with one context term:

```
"<alias>" (salary OR appraisal OR manager OR interview OR "notice period" OR "full and final")
```

Restrict to the past week where the platform allows it. Some platforms sort by relevance by
default — switch to newest first, or you will re-read the same old reviews every week.

## Filling in the TODOs

`config/sources.yaml` ships with `TODO:` placeholders for every company-page URL. Paste the
real URLs during Phase 1; `python3 scripts/validate_data.py` counts what is still missing.
