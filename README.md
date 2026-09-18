# HR Intelligence Digest

A weekly digest of public chatter about our group entities **as an employer** — reviews, posts,
comments and job-market signals across Glassdoor, AmbitionBox, LinkedIn, X and others.

This repository is the operating kit for the programme: the brief, the keyword and source
registers, the tracking-sheet schema, and the scripts that assemble the weekly email.

> **60-day trial.** First-level awareness only. No action items and no HR process changes
> follow from a digest — the single exception is the Red Flag path, which escalates the same
> day. At the end of Month 2 we decide whether to institutionalise, automate, expand, hand to
> HR, or stop. Read [`docs/00-brief.md`](docs/00-brief.md) first.

## Scope in one box

**In scope** — public, employment-related commentary: culture, management, compensation,
appraisals, exits, layoffs, work hours, interview experiences, onboarding, harassment and
safety allegations.

**Out of scope** — customer or seller complaints, product reviews, and any surveillance of an
individual's personal social media accounts. We do not open private or connection-gated
content, and we do not try to identify anonymous reviewers.

This boundary is printed at the foot of every digest.

## Entities

`RK Group` (parent) · `RK World` · `Robust Kommerce` · `Westbury Kommerce` — each tracked
alongside its common misspellings and previous names, because employees rarely write the
registered name. Register: [`config/entities.yaml`](config/entities.yaml).

## Quick start

```bash
python3 -m pip install -r requirements.txt
python3 scripts/validate_data.py        # tells you which Phase 1 TODOs are outstanding
python3 tests/smoke_test.py             # end-to-end check against the fixtures
```

Then the weekly loop:

```bash
python3 scripts/sheet_setup.py                   # 0. (setup) sheet headers + dropdowns
python3 scripts/alert_queries.py                 # 0. (setup) search strings for alerts + sweeps
python3 scripts/import_sheet.py tracker.xlsx     # 1. pull the sheet into data/
python3 scripts/collect_feeds.py                 # 2. pull the permitted feeds
#    ... manual sweep + tagging, per docs/03-weekly-sop.md ...
python3 scripts/red_flags.py --scan              # 3. surface possible same-day escalations
python3 scripts/validate_data.py --week <monday> # 4. check before sending
python3 scripts/build_digest.py --stdout         # 5. build the email body
```

`make weekly` runs steps 2–4 in order.

## What's here

| Path | |
|---|---|
| [`docs/00-brief.md`](docs/00-brief.md) | Programme brief — scope, boundaries, phasing, constraints |
| [`docs/01-entities-and-keywords.md`](docs/01-entities-and-keywords.md) | How the alias and keyword register works |
| [`docs/02-source-map.md`](docs/02-source-map.md) | Platform-by-platform: what to search, how often, what we may automate |
| [`docs/03-weekly-sop.md`](docs/03-weekly-sop.md) | The 3–4 hour weekly runbook, plus the Phase 1 baseline sweep |
| [`docs/04-red-flag-protocol.md`](docs/04-red-flag-protocol.md) | The five triggers and the same-day escalation path |
| [`docs/05-sentiment-and-themes.md`](docs/05-sentiment-and-themes.md) | Tagging rubric, scale anchors, theme taxonomy |
| [`docs/06-tracking-sheet-spec.md`](docs/06-tracking-sheet-spec.md) | Column-by-column schema for the three data files |
| [`docs/07-phase3-review.md`](docs/07-phase3-review.md) | Month-2 decision agenda and criteria, fixed in advance |
| [`docs/08-google-sheet-setup.md`](docs/08-google-sheet-setup.md) | Standing up the tracking sheet and the weekly export step |
| [`docs/09-workbook-review.md`](docs/09-workbook-review.md) | Review of the supplied tracker and how the importer consumes it |
| `config/` | Entities and aliases, source map and feeds, recipients, settings |
| `data/` | `mentions.csv`, `ratings.csv`, `escalations.csv` — the record |
| `scripts/` | Collector, digest builder, red-flag tool, validator, sheet and alert-query helpers |
| `templates/` | Printable weekly sweep checklist |
| `tests/` | Fixtures and an end-to-end smoke test |

## The digest

Six sections, delivered in the **body** of the email — no attachments:

1. **Headline** — mentions per entity, with week-on-week net sentiment change
2. **Rating Movement** — Glassdoor and AmbitionBox scores, with review counts
3. **What's New** — every new review or post: entity, platform, date, sentiment, one line
4. **Themes** — 3–4 recurring complaints or areas of praise
5. **Red Flags** — same-day escalations raised that week, and their status
6. **Data** — link to the underlying tracking sheet

Goes to four recipients: Mahendra, Sonal, Ramesh, Akshay.

## Collection: what is and is not automated

Glassdoor, AmbitionBox and LinkedIn block automated collection and offer no public API. **We do
not build scrapers for them.** `scripts/collect_feeds.py` reads only feeds a publisher offers
openly for machine reading — Google Alerts RSS, Reddit search RSS, news feeds — and everything
it finds lands as `status=needs_review` for a human to tag. The priority-1 platforms are swept
by hand, on the schedule in the source map.

## Things this programme cannot do

Stated here so nobody discovers them at the Month-2 review:

- **It is a trailing indicator.** Review sites lag 2–3 months. A quiet week is not a calm month.
- **Volume will be low**, especially for the smaller entities. Empty weeks are reported as
  empty, not padded.
- **Sentiment is judgement-based.** The rubric narrows the inconsistency; it does not remove it.
  A 0.2 move on five mentions is noise.
- **Public chatter is not employee sentiment.** Review sites over-represent the unhappy and the
  recently-exited.

## Setup status

The repository ships with `TODO:` placeholders for everything that needs a real value — company
page URLs, Google Alerts feeds, recipient addresses, the tracking-sheet link. Run
`python3 scripts/validate_data.py` for the current list.
