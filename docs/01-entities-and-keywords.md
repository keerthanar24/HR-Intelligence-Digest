# Entities, Aliases and Keywords

Everything the sweep searches for is in `config/entities.yaml`. This page explains how to
maintain it. **Edit the config, not the scripts.**

## Why aliases matter more than registered names

Employees almost never write the registered entity name. They write what they called the place
over chai. A review that says *"westburry kommers"* is invisible to a search for
"Westbury Kommerce", and that review is exactly the kind we exist to catch.

So every entity carries four kinds of string:

| Field | What goes in it |
|---|---|
| `aliases` | Every spelling we expect to see, including misspellings, spacings and abbreviations |
| `needs_confirmation` | Previous/registered names HR has **not yet confirmed**. Searched, but flagged by the validator until confirmed |
| `exclude_terms` | Wording that means it is a different company with a similar name |
| — | Employment context comes from the shared `context_terms` list, not per entity |

## Matching rules

Matching is done by `EntityMatcher` in `scripts/hrintel.py`:

1. Text is lowercased, accents and punctuation stripped, whitespace collapsed.
   `R.K. Group`, `r k group` and `RK  Group` all become `rk group`.
2. Aliases are matched on **word boundaries**, longest alias first. "RK World Private Limited"
   wins over "RK World", so we attribute to the most specific entity name present.
3. If any of the entity's `exclude_terms` appears in the same text, the hit is dropped.
   This is what keeps *"RK World Tours"* and *"RK Group of Hotels"* out of the sheet.
4. A hit is marked `has_context` if the text also contains an employment term
   (salary, appraisal, manager, notice period, FnF, harassment…). For noisy platforms —
   news, Reddit, X, Quora, YouTube, Google Reviews — a hit **without** context is filtered
   out by the collector. Review sites are exempt: every review there is about employment.
5. A hit is marked `out_of_scope_hint` if it also contains customer-side wording (refund,
   delivery, courier, warranty…). That is a **prompt for a human**, not an automatic delete —
   an ex-employee complaining about both a refund and unpaid salary is in scope for the
   salary half.

Check any change with:

```bash
python3 tests/smoke_test.py
```

## Adding an alias

1. Add the string to the right entity's `aliases` list in `config/entities.yaml`.
2. Run `python3 tests/smoke_test.py` to confirm nothing else broke.
3. If the alias is generic enough to collide with another company, add the collision to
   that entity's `exclude_terms` in the same commit.

## Where aliases come from

Restock the list from real data, not imagination:

- Misspellings seen in reviews already logged in `data/mentions.csv`.
- Former names, trading names and the name on the offer letter — **ask HR, do not guess**.
  Anything unconfirmed goes in `needs_confirmation` so the validator keeps nagging.
- Shortenings people use internally ("RKW", "Westbury") — add only if specific enough not to
  drown the sheet in noise. A two-letter abbreviation usually is not.
- Hindi/Gujarati transliterations if they appear in practice.

Review the list at the end of Week 2 (the end of Phase 1) and again at the Phase 3 review.

## Current state

| Entity | Aliases | Confirmed via | Unconfirmed |
|---|---|---|---|
| RK Group | 7 | — | none |
| RK World Infocom | 11 | R K World Infocom (AmbitionBox), Rk Worldinfocom (Glassdoor) | none |
| Robust Kommerce | 7 | — | none |
| Westbury Kommerce | 7 | — | none |

RK World Infocom is written three different ways across two platforms, none of them the form
in the original brief ("RK World"). A sweep searching only the registered name would see a
fraction of its chatter — the clearest evidence so far that the alias register earns its keep.

`RK Enterprises` is a placeholder recorded during setup. It is searched but flagged by
`scripts/validate_data.py` until someone confirms or removes it. Do not treat it as fact.

## Names that were ruled out

**`Robust Results`** was carried in as an alias of Robust Kommerce on the strength of a
single AmbitionBox page. It was **ruled out on 2026-09-21**: it is a different company.
It is gone from `config/entities.yaml`, from the generated alert queries, and — since
2026-09-23 — from the live Google Alert that was still running the old query.

It is recorded here rather than deleted because a name that was once searched for will
resurface, and "we looked and it is not ours" is a cheaper answer the second time than
the investigation was the first.
