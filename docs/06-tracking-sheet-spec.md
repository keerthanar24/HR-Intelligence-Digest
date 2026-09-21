# Tracking Sheet Spec

Three CSVs under `data/`. They are the record; the weekly email is a rendering of them.

If the team prefers to work in Google Sheets, keep the **same column names in the same order**
and export back to these paths before running the scripts. `scripts/validate_data.py` will
tell you if the schema drifted.

---

## `data/mentions.csv` — one row per public item

| Column | Required | Values / format | Notes |
|---|---|---|---|
| `mention_id` | yes | `M-YYYYMMDD-NNN` | `YYYYMMDD` is the week's start day (Friday); `NNN` sequential within the week |
| `week_of` | yes | `YYYY-MM-DD` | Must be the week-start day (**Friday**, per `digest.week_start`). The reporting week the item counts toward |
| `captured_at` | yes | `YYYY-MM-DD` | When we found it, not when it was posted |
| `captured_by` | yes | name or `collector` | `collector` = added by `scripts/collect_feeds.py` |
| `entity` | yes | entity id from `config/entities.yaml` | `rk_group`, `rk_world`, `robust_kommerce`, `westbury_kommerce` |
| `platform` | yes | platform id from `config/sources.yaml` | `ambitionbox`, `glassdoor`, `linkedin`, `x`, `reddit`, … |
| `source_name` | no | free text | Display name, e.g. `r/developersIndia` |
| `url` | yes in practice | full URL | A row without a link cannot be verified by anyone else |
| `post_date` | yes if known | `YYYY-MM-DD` | Date the item was posted. Cannot be in the future |
| `author_type` | yes | `current_employee`, `ex_employee`, `candidate`, `intern`, `contractor`, `anonymous`, `unknown` | Stated or clearly implied only — never inferred |
| `role_or_dept` | no | free text | Only if the post states it. Never narrow enough to identify a person |
| `title_or_snippet` | no | free text | The review title or first line, as published |
| `one_line_summary` | yes | one sentence | What the four executives read. See `docs/05-sentiment-and-themes.md` |
| `sentiment` | yes once reviewed | `very_negative`…`very_positive` | Blank = untagged, and the digest says so |
| `themes` | yes once reviewed | pipe-separated, from the fixed list | e.g. `appraisal\|management` |
| `rating_given` | no | `1`–`5` | Stars the reviewer gave, where applicable |
| `engagement` | no | integer | Likes + reposts + comments. Drives the virality trigger |
| `names_individual` | yes | `yes` / `no` | Whether the post names a person |
| `red_flag` | yes | `yes` / `no` | See `docs/04-red-flag-protocol.md` |
| `red_flag_reason` | yes if flagged | one of the five triggers | `names_individual`, `harassment_or_safety`, `non_payment`, `legal_or_regulatory`, `public_escalation_risk` |
| `status` | yes | `needs_review`, `reviewed`, `escalated`, `closed`, `out_of_scope` | `out_of_scope` rows are kept, not deleted, and excluded from the digest |
| `notes` | no | free text | Working notes, scope judgement calls |

**Do not add columns for anything internal** — no employee ID, no HR record, no guess at who
wrote an anonymous review. Public URL and public text only.

## `data/ratings.csv` — one row per entity × platform × week

Captured weekly for Glassdoor and AmbitionBox **even when nothing changed**. Section 2 of the
digest is a time series and a skipped week leaves a hole that never fills.

| Column | Format | Notes |
|---|---|---|
| `week_of` | `YYYY-MM-DD` (Friday) | The week the snapshot belongs to |
| `captured_at`, `captured_by` | date, name | |
| `entity`, `platform` | ids | `glassdoor` or `ambitionbox` |
| `overall_rating` | decimal | As displayed, e.g. `3.4` |
| `review_count` | integer | Total reviews on the page — the week-on-week difference is the new-review count |
| `recommend_pct`, `ceo_approval_pct` | integer | Where the platform shows them |
| `work_life_balance`, `salary_benefits`, `job_security`, `career_growth`, `culture` | decimal | Sub-scores where shown; blank is fine |
| `url`, `notes` | | |

A rating that moves by 0.1 on a base of 40 reviews is one review, not a trend. The digest
reports the review count alongside the score for exactly this reason.

## `data/escalations.csv` — one row per red flag

Restricted. This is the only file that may carry the name of an accused individual, recorded
in `reason` or `action_taken` where it is needed. It is never pasted into the digest.

Columns are described in `docs/04-red-flag-protocol.md`.

## Validation

```bash
python3 scripts/validate_data.py                  # schema + config
python3 scripts/validate_data.py --week 2026-09-07  # plus coverage for that week
```

Errors block the digest. Warnings are judgement calls — "no mentions this week" is a warning,
and it is a legitimate result.

## Sample

`data/mentions.sample.csv` holds four illustrative rows with `example.invalid` URLs. It is a
format reference, not data. Delete it or leave it; the scripts never read it.
