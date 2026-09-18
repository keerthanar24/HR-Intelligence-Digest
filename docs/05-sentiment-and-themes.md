# Sentiment and Theme Tagging

Tagging is judgement-based. The brief says so, and the digest says so. This rubric exists to
narrow the inconsistency, not to pretend it away.

**Expect the first two or three weeks to be rough.** Re-read the first fortnight's tags at the
end of Week 4 and re-tag what now looks wrong — a small, honest correction beats a series that
drifts silently.

## Sentiment scale

Six values. The numeric score drives the net-sentiment figure in section 1 of the digest.

| Value | Score | Use when |
|---|---:|---|
| `very_negative` | −2 | Serious allegation, or an unambiguous "do not work here". Unpaid dues, harassment, humiliation |
| `negative` | −1 | Clear complaint about a specific thing — pay, appraisal, a manager, hours |
| `neutral` | 0 | Factual or balanced with no evaluative lean. Most news items |
| `mixed` | 0 | Genuinely both — real praise *and* a real complaint in the same post |
| `positive` | +1 | Clear praise of a specific thing |
| `very_positive` | +2 | Strong, specific endorsement. "Best place I have worked" |

**`neutral` vs `mixed`** is the most common judgement call. Neutral = nothing evaluative said.
Mixed = both directions said. "Fine, nothing special" is neutral. "Great team, terrible pay"
is mixed. If you cannot decide in ten seconds, pick `mixed` and move on.

Untagged rows are **excluded** from the net sentiment average, not counted as neutral, and the
digest states how many were excluded. A blank tag is honest; a fake neutral is not.

### Anchors

| Text | Tag | Why |
|---|---|---|
| "FnF pending for two months, no response from HR" | `very_negative` | Non-payment — also a red flag |
| "Appraisal cycle slipped by a quarter again" | `negative` | Specific, single complaint |
| "Company opened a new facility in Surat, 200 jobs" | `neutral` | Factual, no evaluation |
| "Great team, but the pay is well below market" | `mixed` | Both directions, both real |
| "Manager actually backs you in front of the client" | `positive` | Specific praise |
| "Five years here and I would join again tomorrow" | `very_positive` | Strong endorsement |

### Calibration rules

1. **Tag the post, not your view of the company.** A fair complaint about a real problem is
   still `negative`.
2. **Star ratings do not decide the tag.** A 4-star review whose text is a list of grievances
   is `mixed` or `negative`. Record the stars in `rating_given` separately.
3. **Intensity is not severity.** An angry rant about the canteen is `negative`, not
   `very_negative`. Reserve ±2 for substance.
4. **Ignore anything you cannot see.** Do not infer motive, seniority or backstory. If the post
   does not say it, it is not data.
5. **Tag a whole week in one sitting.** Drift within a week is what makes week-on-week
   comparison meaningless.

## Themes

Fixed list. Pipe-separated in the `themes` column. Two or three per mention is normal; more
than three usually means the summary is doing too much.

| Theme | Covers |
|---|---|
| `compensation` | Pay level, CTC, benefits, market comparison |
| `appraisal` | Appraisal cycle, increments, ratings, promotions |
| `payroll_delay` | Late or unpaid salary, withheld FnF, PF/ESIC, statutory dues |
| `management` | Managers, leadership, favouritism, decision-making |
| `culture` | Day-to-day environment, respect, politics, team spirit |
| `work_hours` | Shift length, weekend work, on-call, leave |
| `workload` | Volume of work, understaffing, targets, pressure |
| `growth_learning` | Career progression, skills, training, mobility |
| `exits` | Resignations, notice period, relieving and experience letters |
| `layoffs` | Terminations, restructuring, forced resignations |
| `interview` | Interview and hiring process, candidate experience, offer handling |
| `onboarding` | Joining formalities, documentation, induction, first weeks |
| `harassment_safety` | Harassment, discrimination, retaliation, unsafe conditions |
| `facilities` | Office, transport, canteen, equipment |
| `transparency` | Communication, policy clarity, broken promises |
| `job_security` | Stability, contract terms, uncertainty |

`scripts/validate_data.py` rejects a theme outside this list. Do not invent one mid-week —
propose it, add it to `THEMES` in `scripts/hrintel.py` and this table in the same commit, and
note it in the digest so the series break is visible.

### Theme rules

- `payroll_delay` is for *not being paid*. `compensation` is for *being paid too little*. They
  are different problems and only one of them is a red flag.
- `harassment_safety` always means a red-flag check — though the tag and the flag are separate
  decisions.
- `appraisal` and `compensation` often co-occur. Tag both when both are discussed.
- A theme with one mention this week is reported as **"single mention — not yet a pattern"**.
  Three or four recurring themes is what section 4 is for; one-offs are visible in section 3.

## The one-line summary

One sentence, factual, no interpretation, no names.

> Ex-employee reports full-and-final settlement pending for two months.

Not:

> Another angry ex-employee complaining about money, probably performance-managed out.

The summary is what the four executives actually read. It is the most valuable thing produced
in the sweep and the easiest to do badly at 5pm on a Friday.
