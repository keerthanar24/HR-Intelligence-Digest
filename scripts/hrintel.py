"""Shared helpers for the HR Intelligence Digest kit.

Standard library only, apart from PyYAML for the config files. Everything the
scripts agree on — the week definition, the sentiment scale, the theme
taxonomy, the CSV schemas — lives here so the four scripts cannot drift.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced as a clear message, not a traceback
    raise SystemExit(
        "PyYAML is not installed. Run:  python3 -m pip install -r requirements.txt"
    )

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "out")

MENTIONS_CSV = os.path.join(DATA_DIR, "mentions.csv")
RATINGS_CSV = os.path.join(DATA_DIR, "ratings.csv")
ESCALATIONS_CSV = os.path.join(DATA_DIR, "escalations.csv")
WEEKLY_LOG_CSV = os.path.join(DATA_DIR, "weekly_log.csv")
SWEEPS_CSV = os.path.join(DATA_DIR, "sweeps.csv")

MENTION_FIELDS = [
    "mention_id", "week_of", "captured_at", "captured_by", "entity", "platform",
    "source_name", "url", "post_date", "author_type", "role_or_dept",
    "title_or_snippet", "one_line_summary", "sentiment", "themes",
    "rating_given", "engagement", "names_individual", "red_flag",
    "red_flag_reason", "status", "notes",
]

RATING_FIELDS = [
    "week_of", "captured_at", "captured_by", "entity", "platform",
    "overall_rating", "review_count", "recommend_pct", "ceo_approval_pct",
    "work_life_balance", "salary_benefits", "job_security", "career_growth",
    "culture", "url", "notes",
]

# One row per week, written when the digest goes out. Everything derivable is
# derived; these are the three things only the person who did the sweep knows.
# docs/07-phase3-review.md asks for effort and signal quality at the month-2
# review, and neither can be reconstructed eight weeks later from memory.
# One row per channel per week, written when somebody checks it. The review
# sites prove their own coverage through the review count; these channels have
# no count, so a morning spent on YouTube finding nothing leaves no trace and
# reads at month 2 exactly like a channel nobody opened.
SWEEP_FIELDS = ["week_of", "platform", "checked_at", "checked_by", "found", "notes"]

WEEKLY_LOG_FIELDS = [
    "week_of", "logged_at", "swept_by", "minutes_spent", "new_to_recipients",
    "acted_on_elsewhere", "mentions", "red_flags", "out_of_scope",
    "platforms_swept", "notes",
]

ESCALATION_FIELDS = [
    "escalation_id", "raised_at", "week_of", "mention_id", "entity", "platform",
    "url", "severity", "reason", "notified", "notified_at", "owner",
    "action_taken", "status", "closed_at",
]

# --- Controlled vocabularies -------------------------------------------------
# Kept deliberately short. A tag nobody can apply consistently is worse than no
# tag at all — see docs/05-sentiment-and-themes.md.

SENTIMENT_SCORES = {
    "very_negative": -2,
    "negative": -1,
    "neutral": 0,
    "mixed": 0,
    "positive": 1,
    "very_positive": 2,
}

SENTIMENT_LABELS = {
    "very_negative": "Very negative",
    "negative": "Negative",
    "neutral": "Neutral",
    "mixed": "Mixed",
    "positive": "Positive",
    "very_positive": "Very positive",
}

# How an author type reads in an email. "Who wrote it" changes what a line
# means: the same sentence about pay is a retention signal from a current
# employee and a hiring signal from a candidate.
AUTHOR_LABELS = {
    "current_employee": "Current employee",
    "ex_employee": "Ex-employee",
    "candidate": "Candidate",
    "intern": "Intern",
    "contractor": "Contractor",
    "anonymous": "Anonymous",
    "unknown": "Unknown",
}

# Platforms where a post carries public engagement (likes, reposts, replies).
# A review site has none, so a blank engagement figure there is correct and a
# blank one on X is a gap - which is only visible if the two look different.
ENGAGEMENT_PLATFORMS = {"x", "linkedin", "reddit", "youtube", "quora", "news"}


# Platforms where the post's own words are always visible on the page, so a
# row has no excuse for holding only somebody's paraphrase of them.
VERBATIM_REQUIRED = {"ambitionbox", "glassdoor", "indeed", "google_reviews"}


def unverified_channels(week_of: dt.date, settings: dict | None = None) -> list[str]:
    """Channels due this week that can only prove coverage by being recorded.

    A review site proves it was swept: the rating snapshot carries the review
    count, and the change in that count is checkable arithmetic. Every other
    channel has no count, so "checked and empty" and "never opened" look alike
    unless something says which it was.

    An automated feed does NOT excuse a channel from this. The first draft let
    a configured feed stand in for coverage, and a feed that 403s or 429s every
    week would then have silently counted as cover - which is how three of four
    Reddit queries failed on the first real run while the digest reported an
    empty week. The collector now records the channels it actually fetched, so
    a feed proves coverage by succeeding, not by existing.
    """
    out = []
    for platform in load_yaml("sources").get("platforms", []):
        if "ratings" in (platform.get("captures") or []):
            continue
        if not cadence_due(platform.get("cadence", "weekly"), week_of, settings):
            continue
        out.append(platform["id"])
    return sorted(out)


def channels_checked(week_of: dt.date) -> set[str]:
    """Platform ids somebody recorded checking in this week."""
    return {r.get("platform") for r in read_csv(SWEEPS_CSV)
            if r.get("week_of") == week_of.isoformat() and r.get("platform")}


def platform_publishes(platform_id: str, field: str) -> bool:
    """Does this platform print this headline figure at all?

    An empty cell answered two different questions - "the platform does not
    publish this" and "the sweep did not pick it up" - and only the second is a
    problem. config/sources.yaml now says which figures each platform prints.
    """
    for platform in load_yaml("sources").get("platforms", []):
        if platform.get("id") == platform_id:
            return field in (platform.get("publishes") or [])
    return False


def absent_value(platform_id: str, field: str) -> str:
    """What to store when a figure was not recorded: 'n/a' or 'not shown'.

    'n/a'       - the platform never prints it (AmbitionBox has no CEO approval)
    'not shown' - the platform prints it sometimes, and this page did not
    """
    return "not shown" if platform_publishes(platform_id, field) else "n/a"


def engagement_applies(platform_id: str) -> bool:
    """Does this platform publish an engagement count at all?"""
    return (platform_id or "").strip().lower() in ENGAGEMENT_PLATFORMS


THEMES = [
    "compensation",
    "appraisal",
    "payroll_delay",
    "management",
    "culture",
    "work_hours",
    "workload",
    "growth_learning",
    "exits",
    "layoffs",
    "interview",
    "onboarding",
    "harassment_safety",
    "facilities",
    "transparency",
    "job_security",
]

AUTHOR_TYPES = [
    "current_employee", "ex_employee", "candidate", "intern",
    "contractor", "anonymous", "unknown",
]

STATUSES = ["needs_review", "reviewed", "escalated", "closed", "out_of_scope"]

RED_FLAG_REASONS = [
    "names_individual",
    "harassment_or_safety",
    "non_payment",
    "legal_or_regulatory",
    "public_escalation_risk",
]

# --- Config ------------------------------------------------------------------


def load_yaml(name: str) -> dict:
    """Load a file from config/ by bare name, e.g. load_yaml('entities')."""
    path = os.path.join(CONFIG_DIR, name if name.endswith(".yaml") else name + ".yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def entity_names() -> dict[str, str]:
    """entity id -> display name, in the order declared in config."""
    cfg = load_yaml("entities")
    return {e["id"]: e["name"] for e in cfg.get("entities", [])}


def rated_profiles() -> list[tuple[str, str]]:
    """(entity_id, platform_id) for every profile that carries a review count.

    These are the pairs a weekly sweep is expected to snapshot. Enumerating
    them is what lets the digest tell "checked and complete" apart from "never
    checked" - without the list, a platform nobody swept simply produces no
    rows and looks exactly like a quiet week.

    A URL of 'none' means the page does not exist (Robust Kommerce has no
    AmbitionBox profile), which is not the same as one nobody looked at.
    """
    pairs = []
    for platform in load_yaml("sources").get("platforms", []):
        if "ratings" not in (platform.get("captures") or []):
            continue
        for entity_id, url in (platform.get("urls") or {}).items():
            text = str(url or "").strip()
            if not text or text.lower() == "none" or is_todo(text):
                continue
            pairs.append((entity_id, platform["id"]))
    return sorted(pairs)


def absent_profiles() -> list[tuple[str, str]]:
    """(entity_id, platform_id) pairs where the page is confirmed not to exist.

    The opposite of rated_profiles(): a URL written as 'none' means somebody
    looked and there is no page, which is a fact the digest owes the reader.
    Section 2 promises a line per entity per platform, and Robust Kommerce has
    no AmbitionBox profile - so its row is simply missing, and a missing row
    reads as a quiet week rather than as a platform that cannot see it.
    """
    pairs = []
    for platform in load_yaml("sources").get("platforms", []):
        if "ratings" not in (platform.get("captures") or []):
            continue
        for entity_id, url in (platform.get("urls") or {}).items():
            if str(url or "").strip().lower() == "none":
                pairs.append((entity_id, platform["id"]))
    return sorted(pairs)


def weeks_into_trial(week_of: dt.date, settings: dict | None = None) -> int | None:
    """0 for the trial's first week, 1 for the second, None before it starts."""
    settings = load_yaml("settings") if settings is None else settings
    start = parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    if not start:
        return None
    offset = (week_of - week_start_of(start)).days
    return offset // 7 if offset >= 0 else None


def cadence_due(cadence: str, week_of: dt.date, settings: dict | None = None) -> bool:
    """Is a channel on this cadence due in this week?

    config/sources.yaml calls Indeed, YouTube and Google Reviews 'fortnightly',
    but nothing worked out which fortnight, so the checklist asked the desk
    'due this week?' and the runner said 'if due'. A cadence nobody can
    evaluate is swept every week or never, and both answers make the source map
    fiction. Fortnightly means weeks 1, 3, 5, 7 of the trial - counted from the
    trial start, so it does not drift.
    """
    cadence = (cadence or "weekly").strip().lower()
    if cadence != "fortnightly":
        return True
    week = weeks_into_trial(week_of, settings)
    return True if week is None else week % 2 == 0


def profile_url(entity_id: str, platform_id: str) -> str:
    """The review page for one entity on one platform, or "".

    Most AmbitionBox reviews have no permalink of their own, so a row logged
    from one carries no URL and the digest can offer the reader nothing to
    click. The page the review sits on is the next best thing: it is the
    right place to go looking, and it is already in config.
    """
    for platform in load_yaml("sources").get("platforms", []):
        if platform.get("id") != platform_id:
            continue
        url = str((platform.get("urls") or {}).get(entity_id, "")).strip()
        return "" if url.lower() == "none" or is_todo(url) else url
    return ""


def platform_names() -> dict[str, str]:
    cfg = load_yaml("sources")
    return {p["id"]: p["name"] for p in cfg.get("platforms", [])}


def is_todo(value: Any) -> bool:
    """True for a placeholder left in config, so scripts can warn rather than
    silently ship 'TODO: paste the URL' into an email to four executives."""
    return isinstance(value, str) and value.strip().upper().startswith("TODO")


# --- Dates and weeks ---------------------------------------------------------


def parse_date(value: str) -> dt.date | None:
    """Parse the date spellings a spreadsheet actually produces.

    A date cell read out of .xlsx stringifies as '2026-08-31 00:00:00'. Left
    unhandled that returns None, and a caller with a fallback then files the row
    under the wrong date without any error - so the time part is stripped here
    rather than at each call site.
    """
    value = (value or "").strip()
    if not value:
        return None
    if " " in value and ":" in value.split(" ", 1)[1]:
        value = value.split(" ", 1)[0]
    if value.endswith("T00:00:00"):
        value = value[:-9]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# Python's date.weekday(): Monday is 0, Sunday is 6.
WEEKDAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def week_start_day() -> int:
    """Which weekday starts the reporting week, from config/settings.yaml.

    Every day must fall inside exactly one week. A window shorter than seven
    days would drop the days outside it, and a mention posted on a dropped day
    would never appear in any digest.
    """
    name = str(load_yaml("settings").get("digest", {}).get("week_start", "monday"))
    return WEEKDAY_INDEX.get(name.strip().lower(), 0)


def week_start_of(day: dt.date) -> dt.date:
    """The first day of the reporting week containing `day`."""
    return day - dt.timedelta(days=(day.weekday() - week_start_day()) % 7)


# Kept as the historical name so older callers and docs keep working; it
# follows the configured week start rather than always meaning Monday.
monday_of = week_start_of


def last_complete_week(today: dt.date | None = None) -> dt.date:
    """First day of the most recent reporting week that has run its course.

    The week ends on the send day, so on a send day the week finishing that
    same day is the one to report. On any other day the current week is still
    running and the previous one is reported instead. Without this, a Friday
    send would report the week that ended a week ago.
    """
    today = today or dt.date.today()
    start = week_start_of(today)
    return start if start + dt.timedelta(days=6) <= today else start - dt.timedelta(days=7)


def week_range(week_of: dt.date) -> tuple[dt.date, dt.date]:
    return week_of, week_of + dt.timedelta(days=6)


def day_month(day: dt.date, year: bool = False) -> str:
    """'14 Aug', or '14 Aug 2026'. Day number unpadded, on every platform.

    The %-d directive is a glibc extension: it strips the leading zero on Linux
    and macOS and raises ValueError on Windows. It crashed the first real
    logging session on a Windows machine, after the row had been written -
    so the review was saved and the confirmation line was the thing that
    failed. Formatting the integer ourselves has no platform opinion.
    """
    return f"{day.day} {day.strftime('%b')}" + (f" {day.year}" if year else "")


def fmt_week(week_of: dt.date) -> str:
    start, end = week_range(week_of)
    if start.month == end.month:
        return f"{start.day}–{day_month(end, year=True)}"
    return f"{day_month(start)} – {day_month(end, year=True)}"


# --- Text matching -----------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Makes 'R.K. Group', 'r k group' and 'RK  Group' all compare equal, which is
    the whole point of the misspelling list.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _PUNCT.sub(" ", text.lower())
    return _SPACE.sub(" ", text).strip()


@dataclass
class Match:
    entity_id: str
    alias: str
    has_context: bool
    out_of_scope_hint: bool


class EntityMatcher:
    """Matches free text against the alias register in config/entities.yaml."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or load_yaml("entities")
        self.entities = cfg.get("entities", [])
        self.context_terms = [normalise(t) for t in cfg.get("context_terms", [])]
        self.out_terms = [normalise(t) for t in cfg.get("out_of_scope_terms", [])]
        self._aliases: list[tuple[str, str, str]] = []  # (entity_id, alias, normalised)
        self._excludes: dict[str, list[str]] = {}
        for ent in self.entities:
            names = list(ent.get("aliases") or []) + list(ent.get("needs_confirmation") or [])
            for alias in names:
                self._aliases.append((ent["id"], alias, normalise(alias)))
            self._excludes[ent["id"]] = [normalise(x) for x in (ent.get("exclude_terms") or [])]
        # Longest alias first so "RK World Private Limited" wins over "RK World".
        self._aliases.sort(key=lambda a: len(a[2]), reverse=True)

    @staticmethod
    def _contains(haystack: str, needle: str) -> bool:
        """Word-boundary containment on already-normalised strings."""
        if not needle:
            return False
        return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None

    def match(self, text: str) -> list[Match]:
        norm = normalise(text)
        if not norm:
            return []
        has_context = any(self._contains(norm, t) for t in self.context_terms)
        out_hint = any(self._contains(norm, t) for t in self.out_terms)
        seen: set[str] = set()
        results: list[Match] = []
        for entity_id, alias, alias_norm in self._aliases:
            if entity_id in seen or not self._contains(norm, alias_norm):
                continue
            if any(self._contains(norm, x) for x in self._excludes.get(entity_id, [])):
                continue
            seen.add(entity_id)
            results.append(Match(entity_id, alias, has_context, out_hint))
        return results


# --- URLs --------------------------------------------------------------------

_TRACKING_PARAMS = re.compile(
    r"(^|&)(utm_[^=]*|fbclid|gclid|igshid|ref|ref_src|si)=[^&]*", re.IGNORECASE
)


def canonical_url(url: str) -> str:
    """Normalise a URL enough to dedupe the same post arriving twice."""
    url = (url or "").strip()
    if not url:
        return ""
    url = url.split("#", 1)[0]
    if "?" in url:
        base, query = url.split("?", 1)
        query = _TRACKING_PARAMS.sub("", query).strip("&")
        url = f"{base}?{query}" if query else base
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    return url.rstrip("/").lower()


# --- Scope guardrail ---------------------------------------------------------
# The brief's out-of-scope list is a boundary, not a preference: customer or
# seller complaints, product reviews, and surveillance of individuals' personal
# social media. The first two are judgement calls a person confirms. The third
# is not - it is mechanically checkable from the URL, and it is the one whose
# breach would be hardest to explain, so it is refused rather than warned about.

# A person's own profile page. A COMPANY page, or a specific public POST, is a
# different thing and stays in scope.
PERSONAL_PROFILE_PATTERNS = [
    (re.compile(r"(^|\.)linkedin\.com/in/", re.I), "a LinkedIn personal profile"),
    (re.compile(r"(^|\.)linkedin\.com/pub/", re.I), "a LinkedIn personal profile"),
    (re.compile(r"(^|\.)instagram\.com/(?!p/|reel/|explore/|tv/)[^/]+/?$", re.I),
     "an Instagram profile"),
    (re.compile(r"(^|\.)facebook\.com/(?!.*(posts|permalink|story|groups|watch))[^/]+/?$", re.I),
     "a Facebook profile"),
    (re.compile(r"(^|\.)(x|twitter)\.com/(?!i/|search|hashtag)[^/]+/?$", re.I),
     "an X profile rather than a specific post"),
    (re.compile(r"(^|\.)threads\.net/@", re.I), "a Threads profile"),
]


def personal_profile_reason(url: str) -> str | None:
    """Why this URL is a person's profile, or None if it is not one.

    Surveillance of individuals' personal accounts is out of scope. A link to
    someone's profile is that, whatever the intent behind logging it; a link to
    one public post they wrote about their employer is not.
    """
    cleaned = canonical_url(url)
    if not cleaned:
        return None
    for pattern, description in PERSONAL_PROFILE_PATTERNS:
        if pattern.search(cleaned):
            return description
    return None


def customer_side_terms(text: str, cfg: dict | None = None) -> list[str]:
    """Out-of-scope wording found in the text: refunds, deliveries, product faults.

    A prompt, not a verdict - an ex-employee can complain about a refund and
    unpaid salary in one post, and the employment half is in scope.
    """
    cfg = cfg or load_yaml("entities")
    haystack = normalise(text)
    return [term for term in (cfg.get("out_of_scope_terms") or [])
            if re.search(r"(?<!\w)" + re.escape(normalise(term)) + r"(?!\w)", haystack)]


# --- CSV ---------------------------------------------------------------------


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ensure_csv(path: str, fields: list[str]) -> None:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=fields).writeheader()


def append_csv(path: str, fields: list[str], rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    ensure_csv(path, fields)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    return len(rows)


def write_csv(path: str, fields: list[str], rows: Iterable[dict]) -> int:
    """Replace a CSV wholesale. Callers that only add rows want append_csv."""
    rows = list(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    return len(rows)


def mentions_for_week(rows: list[dict], week_of: dt.date) -> list[dict]:
    """Rows belonging to a week, by week_of when set, else by post_date."""
    target = week_of.isoformat()
    picked = []
    for row in rows:
        if (row.get("week_of") or "").strip() == target:
            picked.append(row)
            continue
        if not (row.get("week_of") or "").strip():
            posted = parse_date(row.get("post_date", ""))
            if posted and monday_of(posted) == week_of:
                picked.append(row)
    return picked


def baseline_window(week_of: dt.date, settings: dict):
    """(first_day, last_day, days) for week 1, or None for an ordinary week.

    The brief makes week 1 a sixty-day baseline, but every digest reported a
    strict seven days. The back-read then landed in the weeks the reviews were
    actually posted - August and early September - and the week 1 digest
    reported zero mentions with the whole baseline sitting in the file,
    invisible. A digest that says "no new reviews" the week you read sixty
    days of them is worse than no digest.
    """
    start = parse_date(str(settings.get("programme", {}).get("trial_start", "")))
    if not start or week_start_of(start) != week_of:
        return None
    days = int(settings.get("digest", {}).get("baseline_days", 60))
    last = week_of + dt.timedelta(days=6)
    return last - dt.timedelta(days=days - 1), last, days


def mentions_in(all_mentions: list[dict], first: dt.date, last: dt.date) -> list[dict]:
    """Every mention posted between two dates, inclusive."""
    kept = []
    for mention in all_mentions:
        posted = parse_date(mention.get("post_date", "")) or \
            parse_date(mention.get("captured_at", ""))
        if posted and first <= posted <= last:
            kept.append(mention)
    return kept


def split_themes(value: str) -> list[str]:
    return [t.strip() for t in re.split(r"[|,;]", value or "") if t.strip()]


def sentiment_score(row: dict) -> int | None:
    return SENTIMENT_SCORES.get((row.get("sentiment") or "").strip().lower())


def net_sentiment(rows: list[dict]) -> float | None:
    """Mean sentiment score over the rows that carry a valid tag.

    Untagged rows are excluded rather than counted as neutral — a neutral-looking
    average built from untagged rows would be a lie.
    """
    scores = [s for s in (sentiment_score(r) for r in rows) if s is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def is_yes(value: str) -> bool:
    return (value or "").strip().lower() in {"yes", "y", "true", "1"}


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def to_float(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def next_mention_id(existing: list[dict], week_of: dt.date) -> str:
    """M-YYYYMMDD-NNN, sequential within the week."""
    prefix = f"M-{week_of.strftime('%Y%m%d')}-"
    used = [
        to_int(r["mention_id"][len(prefix):], 0)
        for r in existing
        if (r.get("mention_id") or "").startswith(prefix)
    ]
    return f"{prefix}{(max(used) + 1) if used else 1:03d}"
