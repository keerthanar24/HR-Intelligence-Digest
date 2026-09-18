# Weekly Sweep Checklist — week of ______________

Print or copy per week. Full instructions: `docs/03-weekly-sop.md`.

Swept by: ______________   Started: ______  Finished: ______  (budget 3–4 h)

## 0 · Setup
- [ ] `git pull`
- [ ] `python3 scripts/collect_feeds.py`

## 1 · Manual sweep — priority 1, weekly

| Platform | RK Group | RK World | Robust Kommerce | Westbury Kommerce |
|---|---|---|---|---|
| AmbitionBox — new reviews | ☐ | ☐ | ☐ | ☐ |
| AmbitionBox — rating + count logged | ☐ | ☐ | ☐ | ☐ |
| Glassdoor — new reviews | ☐ | ☐ | ☐ | ☐ |
| Glassdoor — rating + count logged | ☐ | ☐ | ☐ | ☐ |
| LinkedIn — page posts + comments | ☐ | ☐ | ☐ | ☐ |
| LinkedIn — public post search | ☐ | ☐ | ☐ | ☐ |
| X — alias search | ☐ | ☐ | ☐ | ☐ |
| Reddit — manual sub check | ☐ | ☐ | ☐ | ☐ |

## 1b · Fortnightly rotation — due this week? ☐ yes ☐ no
- [ ] Indeed
- [ ] Quora
- [ ] YouTube comments
- [ ] Google Reviews (employment-related only)

## 2 · Tag
- [ ] Every `needs_review` row has a one-line summary
- [ ] Every row has sentiment + themes
- [ ] `author_type`, `names_individual`, `red_flag` set
- [ ] Customer/product items marked `out_of_scope` (kept, not deleted)

## 3 · Red flags — same day, no waiting
- [ ] `python3 scripts/red_flags.py --scan` run
- [ ] Each suggestion confirmed or dismissed by a human
- [ ] For each confirmed flag: row updated, escalation logged, alert sent **today**

## 4 · Validate
- [ ] `python3 scripts/validate_data.py --week <monday>` — no ERRORs

## 5 · Send
- [ ] `python3 scripts/build_digest.py --stdout`
- [ ] Plain-text read top to bottom; headline matches what was seen
- [ ] No individual named anywhere in the body
- [ ] Every What's New row links correctly
- [ ] Section 6 data link opens the sheet
- [ ] Pasted into the email **body** — no attachments
- [ ] Sent to all four

## 6 · Close
- [ ] `git add data/ && git commit && git push`
- [ ] Hours logged above (over budget two weeks running → raise it for Phase 3)

Notes / anything odd this week:

________________________________________________________________

________________________________________________________________
