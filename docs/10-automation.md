# Automation

What the machine does each week, what it cannot, and how to schedule it.

## The honest split

| Channel | Volume so far | Automated? |
|---|---|---|
| AmbitionBox | 96 reviews | **No** — blocked, no public API |
| Glassdoor | 45 reviews | **No** — blocked, no public API |
| LinkedIn | — | **No** — blocked, no public API |
| Reddit | — | Yes, runs today |
| News (Google Alerts) | — | Yes, once RSS feed URLs are configured |
| X | — | Yes, with a paid API token |

**Most of the signal is on the three that cannot be automated.** That is the operating
constraint in `docs/00-brief.md`, not a gap in the tooling, and it would be true on any
machine. Automation removes the typing around the sweep; it does not remove the sweep.

Two things also stay with a person by design:

- **Sentiment and theme tagging** — judgement-based, per `docs/05-sentiment-and-themes.md`.
- **Confirming a red flag.** The scan suggests; a human decides and sends.

## What runs

```bash
make auto          # or: python3 scripts/weekly_run.py
```

Three steps in order — collect the permitted feeds, validate config and data, build the
digest — then print **STILL NEEDS A PERSON**: the rating sweep if no snapshot is recorded,
any untagged mentions, the manual channels, and the red-flag check.

A feed outage is reported but does not stop the digest being built from what is already
logged. Validation errors do not stop the build either: you get the digest and the errors,
rather than neither.

## Scheduling it

### GitHub Actions (recommended)

`.github/workflows/weekly-digest.yml` runs **Friday 03:30 UTC (09:00 IST)**, matching the
sweep window in `config/settings.yaml`, so collected rows are waiting when the sweeper sits
down. It commits anything the collector found to `data/`, uploads the digest as a build
artifact, and puts the run log in the job summary.

Needs nothing to start working. Optionally add a repository secret **`X_BEARER_TOKEN`** to
switch X collection on; without it the X feeds are skipped and X stays manual.

Run it early with **Actions → Weekly HR Intelligence digest → Run workflow**, which also
accepts a specific week.

### cron, on a machine that stays on

```cron
30 9 * * 5  cd /path/to/HR-Intelligence-Digest && make auto >> logs/weekly.log 2>&1
```

Local time, so 09:00 Friday. Prefer Actions unless the repository must stay off GitHub —
a laptop that is asleep on Friday morning silently skips a week.

## What automation cannot rescue

- **A missed rating snapshot.** Ratings are read from a page by a person. Miss a Friday and
  that week has no snapshot, and the week-on-week movement either side of it is broken.
  `python3 scripts/log_rating.py --status` shows what is outstanding.
- **An untagged mention.** It is collected and counted, but excluded from net sentiment and
  reported as untagged in the digest.
- **A red flag nobody looked at.** The scan surfaces candidates; nothing escalates on its own.
  That is deliberate — an automated escalation to four executives about an unverified public
  allegation is a worse failure than a late one.
