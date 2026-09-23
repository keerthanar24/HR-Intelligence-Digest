# HR Intelligence Digest — Programme Brief

**Status:** Trial (60 days) · **Owner:** HR Intelligence desk · **Version:** 1.0 · **Cadence:** Weekly

---

## 1. Purpose

A weekly digest summarising **public chatter about our group entities as an employer** — reviews,
posts, comments and job-market signals.

This is **first-level awareness only**. For the 60-day trial there are:

- no action items assigned off the back of a digest,
- no HR process changes triggered by a digest,
- no individual employee named as a subject of investigation.

At the end of Month 2 we review the accumulated data and decide whether to institutionalise,
expand, hand over, or stop (see `docs/07-phase3-review.md`).

The one exception to "no action" is the **Red Flag** path: a narrow, pre-agreed set of triggers
that escalate the same day. See `docs/04-red-flag-protocol.md`.

## 2. Entities in scope

```
RK Group  (parent / corporate brand)
 |- RK World Infocom Pvt Ltd
 |- Robust Kommerce
 \- Westbury Kommerce
```

| # | Entity | Role | Also appears as |
|---|--------|------|-----------------|
| 1 | RK Group | Parent / corporate brand | R.K. Group |
| 2 | RK World Infocom | Subsidiary | R K World Infocom, Rk Worldinfocom |
| 3 | Robust Kommerce | Subsidiary | Robust |
| 4 | Westbury Kommerce | Subsidiary | Westburry, Westbery |

**ValueCart — deliberately out of scope.** It is a separate company under the same parent, and
the programme owner excluded it from the trial on 2026-09-21. Its names are not in the
register, so its chatter matches nothing and is neither tracked nor misfiled against RK World
Infocom.

It was briefly in scope, long enough to record a Glassdoor baseline of **4.70 on 14 reviews,
91% recommend** — the highest in the group. That figure is noted here rather than in the data
so the exclusion stays clean, and so that anyone proposing to add ValueCart later knows it
would raise the group total and widen the headline range. Adding it back is a scope decision
for the four, not a desk one.

We track **common misspellings and previous names** alongside the registered names — employees
rarely write the registered entity name. The maintained list lives in `config/entities.yaml`
and is explained in `docs/01-entities-and-keywords.md`.

## 3. Platforms in scope

| Platform | What we look for | Collection |
|---|---|---|
| AmbitionBox | Reviews, ratings, interviews, salaries | Manual sweep (highest expected volume for India) |
| Glassdoor | Reviews, ratings, interviews, salaries | Manual sweep |
| LinkedIn | Company page activity, employee/ex-employee posts and comments | Manual sweep |
| X | Mentions, complaints, viral threads | Alert/feed assisted + manual |
| Indeed | Reviews, interview experiences | Manual sweep |
| Reddit | Employment threads (r/india, r/developersIndia, r/jobs, city subs) | Feed assisted |
| Quora | "What is it like to work at…" answers | Alert assisted + manual |
| YouTube | Comments on relevant videos | Manual sweep |
| Google Reviews | Employment-related reviews only | Manual sweep |

Per-platform search strings, cadence and compliance notes: `docs/02-source-map.md`.

## 4. Boundaries — written into every digest

**In scope**

- Culture and management
- Compensation, appraisals, increments, incentives
- Exits, resignations, layoffs, full-and-final settlement
- Work hours and workload
- Interview experiences
- Onboarding issues
- Harassment or safety allegations

**Out of scope**

- Customer or seller complaints
- Product, service or delivery reviews
- Surveillance of individual employees' personal social media accounts

**This boundary is enforced in the tooling, not only written here.**

| Boundary | How it is held |
|---|---|
| No surveillance of personal accounts | A URL that is someone's personal profile — LinkedIn `/in/`, Instagram, Facebook, X, Threads — is **refused** by `log_mention.py`, dropped by the collector, and errors in the validator. A company page or one specific public post is a different thing and stays in scope |
| No customer or seller complaints | Customer-side wording (refund, delivery, warranty…) is **refused** at logging unless flagged as a mixed post, and warned about in validation |
| No product reviews | Same check |

A mixed post — an ex-employee complaining about both a refund and unpaid salary — is logged
with the employment half only, via `--mixed-post`, and the note records why.

The out-of-scope line is not a soft preference. We log **public, employment-related** commentary.
We do not follow, friend, monitor or compile a picture of any named individual's personal
accounts, and we do not open private or restricted content. If a post is only reachable by
logging into a personal network or by connecting to the author, it is out of scope.

Where a post mixes a customer complaint with an employment claim (e.g. an ex-employee posting
about both a refund and unpaid salary), we log **only the employment portion** and note the
mixed nature in the summary.

## 5. Deliverable

One email per week, sent **Friday between 15:00 and 17:00**, covering the reporting week that
ends that same day (**Saturday 00:00 → Friday**), **in the body of the email — no
attachments**, structured as:

1. **Headline** — total mentions for the week by entity, with net sentiment change week-on-week.
2. **Rating Movement** — Glassdoor and AmbitionBox score updates per entity.
3. **What's New** — table of every new review or post: entity, platform, date, sentiment, one-line summary.
4. **Themes** — 3–4 recurring complaints or areas of praise.
5. **Red Flags** — same-day escalations raised during the week, and their status.
6. **Data Link** — shared link to the underlying tracking spreadsheet.

Generated by `scripts/build_digest.py`; see `docs/03-weekly-sop.md`.

## 6. Distribution

Weekly digest and red-flag alerts go to four recipients: **Mahendra, Sonal, Ramesh, Akshay**.
Addresses and any per-person overrides are in `config/recipients.yaml`.

Distribution is deliberately narrow. The digest is not forwarded outside this group during the
trial, and the raw sheet is shared with the same four plus the desk owner.

## 7. Phasing

| Phase | Weeks | Work |
|---|---|---|
| Phase 1 — Setup | 1–2 | Finalise entity/keyword lists, map platform sources, stand up the tracking sheet, run a manual baseline sweep. The Week 1 digest covers the **past 60 days** rather than seven, to log historical reviews and set the rating baseline |
| Phase 2 — Execution | 3–8 | Weekly semi-automated collection where platforms allow, supplemented by manual sweeps |
| Phase 3 — Review | End of Month 2 | Evaluate utility; decide: automate further / expand scope / transition to HR / stop |

## 8. Operational constraints — stated up front

- **Manual/scripted hybrid.** Glassdoor, AmbitionBox and LinkedIn block automated scraping and
  offer no public API. V1 uses scheduled manual sweeps, search alerts and light scripting only
  against feeds those platforms publish for that purpose. We do not build scrapers for them.
- **Low volume.** Smaller entities will have weeks with zero mentions. An empty section is a
  valid result and is reported as "no new mentions", not padded.
- **Time lag.** Review sites typically reflect a 2–3 month lag. This is a **trailing indicator**,
  not an early-warning system. Do not read a quiet week as a calm month.
- **Sentiment accuracy.** Tagging is judgement-based. Expect inconsistency in the first few
  weeks; the rubric in `docs/05-sentiment-and-themes.md` exists to narrow it, not eliminate it.

## 9. Effort

- Setup: 8–10 hours (Phase 1, one-off)
- Weekly maintenance: 3–4 hours (Phase 2)

If weekly effort runs materially above 4 hours for two consecutive weeks, that is itself a
finding for the Phase 3 review — log it rather than absorbing it.

## 10. Data handling

- The tracking sheet holds **public URLs and public text**. We do not add internal HR records,
  employee IDs, or any attempt to de-anonymise an anonymous reviewer.
- Where a post names an individual, the name is recorded in the escalation log (restricted) and
  is **redacted in the weekly digest body** — the digest links to the source instead.
- Access to the sheet is limited to the distribution group plus the desk owner.
- Retention: for the trial, data is kept until the Phase 3 review, at which point retention is
  decided explicitly.
