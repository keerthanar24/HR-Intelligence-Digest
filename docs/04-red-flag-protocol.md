# Red Flag Protocol

The one part of this programme that does not wait for the Friday send.

Everything else in the trial is awareness only. A red flag is escalated **the same day it is
found**, to the four recipients, with an acknowledgement expected within
`red_flags.sla_hours` (default 8 working hours).

## The five triggers

A red flag is not "a bad review". Bad reviews are the normal content of this digest. A red
flag is one of these, and only these:

| `red_flag_reason` | Trigger |
|---|---|
| `names_individual` | A named person is accused of specific conduct |
| `harassment_or_safety` | Harassment, assault, discrimination, retaliation, or an unsafe working condition |
| `non_payment` | Unpaid or withheld salary, full-and-final settlement, PF/ESIC or other statutory dues |
| `legal_or_regulatory` | Labour commissioner, tribunal, police complaint, legal notice, regulator |
| `public_escalation_risk` | Traction (engagement at or above the configured threshold), media pickup, or a thread visibly gaining momentum |

If it is not on this list, it goes in the weekly digest, not into anyone's evening.

## Making "same day" true

A red flag is only same-day if it is *found* the same day, and three of the six platforms
cannot be polled. Four things together close that, and none of them is the weekly sweep:

| Cover | Channel | Effort |
|---|---|---|
| **Claim the employer profiles** | Glassdoor, and AmbitionBox if it offers it | One-off, free. The platform emails you on every new review |
| Daily automated scan | Reddit, news, X | None — `.github/workflows/daily-red-flag-scan.yml` |
| **Daily count check** | Glassdoor, AmbitionBox | ~3 min — `make daily` |
| Cross-entity Google Alert | News, blogs, forums | Read it daily |

The **daily count check** is the cheap one. Reading every review daily is unrealistic;
comparing a *number* is not. Each review page shows a review count, and the count moving is
the only signal needed — if it has not moved, nothing was posted. Seven pages, twenty seconds
each.

```bash
make daily                                            # the list with last known counts
python3 scripts/daily_check.py --bump ambitionbox rk_world 54
```

A bump tells you how many arrived and points at the page to read.

**Without at least the employer profiles or the daily check, "immediate, same-day
escalation" is not being delivered** — a Tuesday allegation waits until Friday. Say so to the
four rather than letting the brief imply otherwise.

## The same-day path

1. **Spot it.** From the daily check, the daily scan, or the Friday sweep.
   `python3 scripts/red_flags.py --scan` suggests; **a human confirms every flag.**

2. **Raise it — one command.** This sets the flag on the mention, logs the escalation with
   severity and owner, drafts the alert, and sends it:

   ```bash
   python3 scripts/red_flags.py --raise M-20260919-001 \
       --reason non_payment --severity high --send
   ```

   Without `--send` it does everything except send, and prints the alert for review.

   It used to take four steps — edit the mention row, add an escalation row, draft, then
   copy the draft into a mail client. Every one of those is somewhere an urgent thing
   stalls on a Friday afternoon.

   If sending is not configured it says so and points at the drafted file, rather than
   failing silently and leaving the alert unsent.

3. **Record the acknowledgement** — who replied and when — in `data/escalations.csv`
   (`notified_at`, `status`).

4. **It reappears in the digest.** Section 5 lists every flag raised that week and its
   status, so the weekly record is complete even for items already handled.

## What the alert says, and does not say

The alert is a **notification, not an assessment**. It carries: entity, platform, date,
trigger, author type, the one-line summary, and the source link. It explicitly asks for
acknowledgement only, because the trial assigns no action items.

It does **not** carry:

- **The name of an accused individual.** The name lives in the restricted escalation log;
  the alert links to the source instead. Anyone who needs the name opens the link.
- Any finding about whether the allegation is true. We record that a public claim exists.
  That is the whole claim we are making.
- Anything reached from a private account, a connection request, or a login to a personal
  network.

## Severity

| Severity | Use for | Response |
|---|---|---|
| `high` | Any of the five triggers | Same-day alert, acknowledgement within SLA |
| `critical` | Harassment or safety with a named individual, or active media/regulatory involvement | Same-day alert **plus** a direct call to the desk owner; consider routing to the POSH IC through the normal channel immediately |

`critical` is the only case where the desk does more than send an email — and even then it
routes through the existing HR/IC channel. This programme does not run investigations.

## What this protocol is not

- It is not a substitute for the POSH internal committee or any statutory process. A public
  allegation surfacing here does not start a formal process; it tells the four that one may
  be needed through the proper route.
- It is not an early-warning system. Review sites lag 2–3 months. A red flag is often
  about something that already happened a quarter ago.
- It is not a channel for identifying anonymous reviewers. We do not attempt to work out who
  wrote a review, and a request to do so is out of scope for this desk.

## Recording an escalation

`data/escalations.csv`, one row per flag:

| Column | Notes |
|---|---|
| `escalation_id` | `E-YYYY-NNN`, sequential |
| `raised_at` | Date found — the SLA runs from here |
| `mention_id` | Links to the row in `data/mentions.csv` |
| `severity` | `high` or `critical` |
| `reason` | One of the five triggers |
| `notified` | Names of who the alert went to |
| `notified_at` | Date sent — same day as `raised_at`, or explain why not |
| `owner` | Who is tracking the acknowledgement |
| `action_taken` | Free text; for the trial this is usually "alert sent, acknowledged by X" |
| `status` | `open` → `acknowledged` → `closed` |

`python3 scripts/validate_data.py` errors if a mention is flagged red but has no escalation
row, or if an escalation has no record of who was notified.

## Where same-day cover actually reaches

"Immediate, same-day escalation" is a promise about how fast a flag is **acted on** once it
is found. How fast it is **found** depends on the channel, and the two are not the same
thing. Every digest now says which is which under section 5.

| Channel | How a new item could be seen today | Lag |
|---|---|---|
| AmbitionBox, Glassdoor | `python3 scripts/daily_check.py` — the review count moving | same day **only if the check is run**; otherwise up to 6 days |
| Reddit, news, Quora, Indeed | the collector, run daily by the GitHub Action | same day |
| **LinkedIn, X, YouTube, Google Reviews** | **nothing — only the weekly sweep** | **up to 6 days** |

### The first row is conditional, and the digest now says which way

A route existing is not a route being walked. `H.count_route_is_live()` asks the data
whether those pages have actually been opened since the last sweep, and section 5 names
AmbitionBox and Glassdoor alongside the weekly channels when they have not — with the
cause stated honestly, because "the platforms block automated checking" is true of
LinkedIn and untrue of a two-minute count check nobody ran.

The daily Action prints the pages a person still has to open, and fails — so GitHub
notifies — when nobody has checked in **more than 7 days**. That threshold asserts only
that the weekly sweep happened. Lower it to 1 or 2 if the daily habit starts, and the
digest will upgrade its own wording as soon as the data supports it.

When a count has moved:

```bash
python3 scripts/daily_check.py --bump ambitionbox rk_world 52
```

That writes the new count and today's date into `data/ratings.csv`, which is what makes
the staleness measurable. Until recently it only printed, so nothing recorded that a
check had happened at all.

The four in bold block automated checking or have no feed, so this is a limit of the
sources, not of the process. Two things narrow it, and neither is code:

1. **Turn on LinkedIn page notifications.** Whoever administers the four company pages is
   notified of comments on company posts as they happen. If they forward anything
   employment-related to the desk, LinkedIn's same-day cover comes from LinkedIn itself.
   This is the single largest improvement available to the red-flag protocol and it costs
   nothing — LinkedIn is both the slowest channel here and the fastest-moving one.
2. **Set `X_BEARER_TOKEN`.** The X feeds are written and disabled. A token moves X from the
   weekly sweep to the daily collector, and X is where a complaint goes public fastest.

Claiming the Glassdoor and AmbitionBox employer profiles would also make those platforms
email the desk directly when a review is posted, which is better than a count check.

