# The 60-day back-read

Week 1's baseline is not just the ratings — it is **every employment review published in the
last 60 days**, logged as one row each. Until that exists, sections 1, 3, 4 and 5 of the digest
are empty no matter what else is configured, because all four are built from mentions.

This is the one job in the programme that cannot be automated. Glassdoor and AmbitionBox block
automated collection, offer no public API, and the brief commits to staying inside their terms.
A person reads the pages.

---

## Six pages, not seven

| Entity | AmbitionBox | Glassdoor |
|---|---|---|
| RK Group | [reviews](https://www.ambitionbox.com/reviews/r-dot-k-dot-group-reviews) | [reviews](https://www.glassdoor.co.in/Reviews/RK-Group-Reviews-E653077.htm) |
| RK World Infocom | [reviews](https://www.ambitionbox.com/reviews/r-k-world-infocom-reviews) | [reviews](https://www.glassdoor.co.in/Reviews/Rk-Worldinfocom-Reviews-E8268877.htm) |
| Westbury Kommerce | [reviews](https://www.ambitionbox.com/reviews/westbury-kommerce-reviews) | [reviews](https://www.glassdoor.co.in/Reviews/Westbury-Kommerce-Reviews-E6166527.htm) |
| **Robust Kommerce** | *no page* | *no page* |

Robust Kommerce has no review-site presence at all. Nothing to back-read for it, and the digest
says so rather than leaving it to look like a quiet company.

**Sort each page by newest first**, not by "most relevant" or "most helpful" — the default sort
is designed to surface good reviews, not recent ones.

---

## How to log them

Use the guided prompt. It asks one field at a time, rejects a value that is not in the
vocabulary on the spot, and remembers the entity and platform between reviews on the same page:

```bash
python3 scripts/log_mention.py --interactive
```

The command-line form is still there for a single row:

```bash
python3 scripts/log_mention.py \
    -e rk_world -p ambitionbox -d 2026-08-14 \
    -s "Ex-employee says full-and-final settlement pending two months" \
    --sentiment very_negative --themes payroll_delay,exits \
    --author ex_employee --url https://... --flag non_payment
```

### What each field is

| Field | What to put |
|---|---|
| **date** | the date the review was **published**, not the date you read it |
| **title** | the review's own headline, copied as published |
| **summary** | one factual sentence. No names. No interpretation — say what the reviewer said, not whether they are right |
| **sentiment** | your read of the *post*, not of the company |
| **theme(s)** | one or more from the fixed list; several is fine |
| **author** | only if the page states or clearly implies it — otherwise `unknown` |
| **stars** | what the reviewer gave, if shown |
| **red-flag trigger** | blank unless it names an individual, alleges harassment, non-payment, legal action, or looks likely to escalate publicly |

`mixed` sentiment is the one people under-use. "Great team, terrible pay" is mixed, not negative.

---

## What does NOT get logged

The boundary is enforced, not just documented — `log_mention.py` refuses these rather than
trusting anyone to remember:

- **Customer or seller complaints** — a late delivery, a refund, a faulty product.
- **Product reviews** of anything the group sells.
- **Anything from an individual's personal social account.** Company pages and public posts are
  in scope; browsing a named person's profile is not.

A post that mixes a customer complaint with an employment one is logged with `--mixed-post`,
and only the employment half is recorded.

---

## Red flags do not wait for Friday

If a review in the back-read names an individual, alleges harassment or non-payment, mentions
legal action, or looks likely to escalate publicly, it is escalated **the same day you find it**,
even though the review itself may be weeks old:

```bash
python3 scripts/red_flags.py --scan     # what looks like a trigger
python3 scripts/red_flags.py --raise M-20260919-003 --reason non_payment
```

---

## Knowing when it is done

```bash
python3 scripts/log_mention.py --list --week 2026-09-19   # what is logged
python3 scripts/log_rating.py --status                    # ratings for the week
python3 scripts/build_digest.py                           # refuses while reviews are unread
```

From week 2 onward the build compares the review-count delta against the rows logged and
refuses to send while the two disagree, naming the page and how many are outstanding. Week 1 has
no previous count to compare against, so the back-read is the one sweep the arithmetic cannot
check for you — it is finished when you have been through all six pages.

## Roughly how long

Six pages, 60 days. On the recorded counts (27, 51, 18 on AmbitionBox; 16, 20, 2 on Glassdoor)
most of those reviews are older than 60 days, so expect perhaps 10–25 in scope. At two or three
minutes each including the judgement call, that is **one to two hours**, once.
