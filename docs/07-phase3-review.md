# Phase 3 — End of Month 2 Review

The trial was set up to produce a decision, not to quietly become permanent. This page is the
agenda for that decision, written in Phase 1 so the criteria are fixed **before** anyone knows
what the data says.

Attendees: the four recipients (Mahendra, Sonal, Ramesh, Akshay) and the desk owner.
Timing: the week after Week 8.

## The four options

| Option | Means |
|---|---|
| **Institutionalise** | Keep the weekly digest, hand it a permanent owner and a budget of hours |
| **Automate further** | Keep it, invest in licensed APIs or paid monitoring to cut the manual sweep |
| **Expand scope** | Keep it and add entities, platforms, or depth (e.g. exit-interview correlation) |
| **Transition to HR** | Keep it, run by HR as part of an existing process rather than a standalone desk |
| **Stop** | The data did not earn its 3–4 hours a week. Archive it and close the desk |

**Stop is a real option**, and the most likely one if volume stays low. Saying so up front is
what keeps the other four options honest.

## What to bring to the review

Produce these from the tracking data before the meeting:

1. **Volume.** Total mentions over 8 weeks, by entity and platform. How many weeks were empty?

   ```bash
   python3 scripts/channel_yield.py
   ```

   It prints found against swept per channel, which is the distinction the decision
   turns on: a channel with nothing found after eight weeks of looking and a channel
   nobody ever opened both print `0`, and point at opposite answers. Only the first
   is evidence for narrowing scope.
2. **Red flags.** How many were raised? How many were acted on outside this programme? How
   many would have been missed without it?
3. **Effort.** Actual hours per week against the 3–4 hour budget. Where did the time go?
4. **Signal quality.** How many mentions were genuinely new information to the four, versus
   already known through normal channels?

   > Items 3 and 4 are the only two on this list that cannot be counted from the tracking
   > data, so they are recorded every Friday instead, at the end of the sweep:
   > `python3 scripts/log_week.py`, stored in `data/weekly_log.csv`. Bring
   > `python3 scripts/log_week.py --show` to the meeting rather than reconstructing eight
   > weeks from memory — a trial that is evaluated on recollection gets renewed on
   > recollection.

5. **Noise.** How many items were logged as `out_of_scope`? A high ratio means the keyword
   list or the platform mix needs work, not that the programme failed.
6. **Rating movement.** Did Glassdoor/AmbitionBox scores move at all in 8 weeks? On what
   review volumes?
7. **Tagging consistency.** Re-tag a sample of 10 early rows blind. How many match the
   original tag?

## Decision criteria, agreed in advance

Written before the data exists, so they cannot be reverse-engineered from it.

| Signal | Points toward |
|---|---|
| ≥ 1 red flag that reached the four **first** through this digest | Institutionalise |
| Consistent volume (≥ 5 mentions/week across the group) | Institutionalise or automate |
| Mostly empty weeks, no red flags, nothing new to the four | Stop |
| Useful signal but the manual sweep dominates the effort | Automate further |
| Useful signal that overlaps an existing HR process | Transition to HR |
| Volume concentrated in one entity or platform | Expand or narrow scope accordingly |

## Questions to actually ask in the room

- Did anyone **change a decision** because of something in a digest? If not, is awareness
  alone worth 3–4 hours a week?
- Was the 2–3 month review-site lag a problem in practice, or did the lag turn out not to
  matter for how the four used it?
- Did the digest ever create pressure to act on an unverified public claim? That is a risk of
  the format, and worth naming if it happened.
- Did the boundary hold? Any instance of the desk being asked to look at an individual's
  personal accounts, or to identify an anonymous reviewer, is a governance finding — record it
  whether or not the request was refused.
- Is there an owner who genuinely wants this, or would it survive as an orphan task?

## Known limitations to weigh honestly

These were stated in the brief and should not be treated as surprises at review time:

- **Trailing indicator.** 2–3 month site lag. This programme cannot catch a problem early;
  it can only confirm that a problem became public.
- **Low volume.** For the smaller entities, low volume may mean a healthy workplace, or it may
  mean employees who do not post reviews. The data cannot tell these apart.
- **Judgement-based sentiment.** Even with the rubric, the net sentiment figure is a rough
  directional signal, not a measurement. A 0.2 move week-on-week on five mentions is noise.
- **Survivorship.** Review sites over-represent the unhappy and the recently-exited. The
  digest measures public chatter, which is not the same as employee sentiment.

## If the answer is "stop"

Archive the repository and the sheet, keep the escalation log per the retention decision,
and write a one-page note on what was learned. A well-documented negative result is worth more
than a programme kept alive out of momentum.
