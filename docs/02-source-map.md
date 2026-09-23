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

### X — weekly, API where available

`scripts/collect_feeds.py` queries X's official **recent-search** endpoint (last 7 days, which
is exactly the digest window) when a bearer token is present:

```bash
export X_BEARER_TOKEN="…"        # never commit this; .env and config/secrets.yaml are gitignored
```

Then set the four `x_search_*` feeds in `config/sources.yaml` to `enabled: true`.

The query is built from the alias register at run time, so a newly confirmed trading name is
searched without editing anything. It pairs the aliases with a spread of employment terms —
pay, harassment, layoffs, interviews, notice period — rather than pay alone, because X is
where a harassment thread or a layoff claim goes public. `-is:retweet` keeps a viral complaint
to one row instead of hundreds.

**Why the API matters here beyond convenience:** it returns like, repost, reply and quote
counts. `public_escalation_risk` is the only red-flag trigger with a numeric threshold
(`red_flags.virality_engagement_threshold` in `config/settings.yaml`), and without those counts
it is a guess. With them, `python3 scripts/red_flags.py --scan` surfaces a post gaining
traction automatically.

**No token?** The collector says so and skips, and X falls back to a logged-out manual search:

```bash
python3 scripts/alert_queries.py --format manual
```

Record `engagement` by hand in that case — a rough count is still far better than a blank.

### Reddit — weekly, feed

`scripts/collect_feeds.py` reads Reddit's public search feed for each entity, with the query
built from the alias register at run time. No token or account needed; this runs today.

**Known limitation: Reddit's search covers posts, not comments.** A thread titled "Best
e-commerce employers in Gujarat?" whose comments name our entities will not surface. That is
Collected as **one search for the whole group**, not one per entity. Reddit rate-limits per IP
and cumulatively: across three real runs the first request always succeeded and later ones
returned 429, a different pair failing each time, so two entities went unsearched every run.
Four requests became one. The collector assigns each hit to whichever entity its text matches,
as it already does for the cross-entity red-flag alert.

That is also why the manual check stays in the weekly SOP: look through `r/india`, `r/developersIndia`,
`r/IndianWorkplace`, `r/jobs` and the relevant city subs for threads the feed cannot see.
Do not treat a quiet Reddit feed as a quiet Reddit.

### Indeed — fortnightly, manual, alert-assisted
Company reviews and interview experiences. A site-restricted Google Alert
(`google_alerts_indeed`) feeds the collector, but Indeed stays **manual**: its company pages
are indexed and individual reviews often are not, and an alert only fires on what Google
newly indexes. The alert is partial cover, so `log_sweep.py` still asks for the fortnightly
look and the collector does not tick the box on Indeed's behalf.

Indeed has no public API — the Publisher API was closed years ago and automated collection is
blocked — so this alert is the only automation available for it.

> **Swept 2026-09-22 (trial week 1): no Indeed employer page exists for any of the four
> entities.** Not "a page with no reviews" — no profile at all. Recorded in
> `data/sweeps.csv`. Confirm once more in week 3; if it is still absent, the fortnightly
> manual look has nothing to look at and `google_alerts_indeed` should carry the channel on
> its own. A profile can appear at any time — usually created by a candidate, or by Indeed
> once a job is posted — which is what the alert is standing cover for.

> **What "fortnightly" means.** Trial weeks 1, 3, 5, 7 — counted from `programme.trial_start`
> in `config/settings.yaml`, so the rotation cannot drift. The cadence in `config/sources.yaml`
> is now evaluated rather than left to the desk: `make sweep` marks each fortnightly channel
> DUE or NOT due for the week being swept, and `scripts/weekly_run.py` names the ones due.

## Priority 3

### Quora — weekly, alert-collected
"What is it like to work at…" style answers. A site-restricted Google Alert covering all four
entities feeds the collector (`google_alerts_quora`), so Quora no longer needs a weekly manual
search. The alert catches what Google **newly** indexes, so it is standing cover from the day
it was created — the back catalogue still needs one manual look.

### YouTube — fortnightly, manual
Comments on videos about the group. **Employment-related comments only** — skip the customer
and product commentary that will make up most of the thread.

### Google Reviews — fortnightly, manual
Employment-related reviews only. On a Google Business listing these are a small minority;
most are customer reviews and are out of scope.

### News / web — weekly, feed
Google Alerts RSS per entity. Catches layoffs, labour disputes and hiring coverage.

## The alerts layer — what it does and does not cover

Set expectations before spending an afternoon on this. **Alerts do not cover the platforms
that matter most.** Glassdoor, AmbitionBox and LinkedIn reviews are largely invisible to
Google Alerts — the pages are dynamic, often noindexed, and a new review rarely surfaces as a
crawlable "news" item. Alerts are good at the tail: news coverage, blogs, forums, Quora, the
occasional Reddit thread.

So the alerts layer is worth an hour because it is the only thing watching **between** sweeps.
It is not a substitute for the manual sweep, and a quiet alert inbox means nothing.

| Layer | Covers | Latency |
|---|---|---|
| Google Alerts (RSS) | News, blogs, forums, Quora, some Reddit | Hours to a day |
| Reddit search RSS | Reddit only | Near real-time |
| Employer-account notifications | New reviews on a claimed profile | Same day, where offered |
| Manual sweep | Everything, properly | Weekly |

### Generating the queries

Do not hand-write the search strings — generate them from the alias register so they cannot
drift from what the collector filters on:

```bash
python3 scripts/alert_queries.py --format google   # alert queries, ready to paste
python3 scripts/alert_queries.py --format manual   # per-platform sweep strings
```

Each entity gets a **broad** query (aliases OR-ed) and a **narrow** fallback (aliases AND an
employment term, minus the known collisions). Start broad. Switch to narrow the first time an
alert delivers a batch about a hotel chain in Dubai.

### Platform-native alerts

Worth setting up alongside Google Alerts, and often better:

| Platform | What is available | Notes |
|---|---|---|
| **Glassdoor** | A free Employer Account on a **claimed** company profile gives email notification of new reviews | The most direct review alert available to us. Requires someone to claim and verify the profile — a decision for the group, not the desk |
| **AmbitionBox** | Employer/business profile claiming exists; check whether the claimed account offers new-review notification | Verify before relying on it — do not assume parity with Glassdoor |
| **LinkedIn** | Page admins are notified when the page is **@mentioned** | Plain-text mentions that do not tag the page produce no notification. The public post search in the weekly sweep is what actually catches those |
| **X** | No free keyword alerting. The recent-search API needs a paid plan, and `scripts/collect_feeds.py` uses it when `$X_BEARER_TOKEN` is set | Without a plan, the logged-out manual search is the V1 answer |
| **Reddit** | No native keyword alert, but the public search RSS already runs in `scripts/collect_feeds.py` | Third-party keyword-to-email services exist and are free; they send our brand names to an outside party, so treat as an optional convenience, not part of the standard setup |
| **Google Reviews** | Notification on new reviews via the Google Business Profile, if the group holds it | Mostly customer reviews — employment ones are a small minority |

Claiming an employer profile is a **group decision, not a desk decision**: it is a public,
attributable action and it changes the relationship with the platform. Raise it with the four
rather than doing it to make the sweep easier.

## Setting up Google Alerts (Phase 1, once)

1. Go to <https://www.google.com/alerts>.
2. Create one alert per entity. Paste the query from
   `python3 scripts/alert_queries.py --format google` — do not retype it.
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
