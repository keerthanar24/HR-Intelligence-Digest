#!/usr/bin/env python3
"""Open every page and feed the sweep expects to exist, and say which answer.

Every URL in config/sources.yaml was typed in by hand from a browser. A typo
survives indefinitely because the worksheet prints it either way and the desk
ticks the box: a dead LinkedIn page looks exactly like a quiet one. Nothing in
this project has ever loaded any of them.

This is deliberately NOT part of the weekly run. It touches company pages on
sites that ask not to be crawled, so it is a one-off check a person runs after
editing config - not something on a schedule.

    python3 scripts/check_urls.py
    python3 scripts/check_urls.py --platform linkedin
    python3 scripts/check_urls.py --feeds      # the Google Alerts RSS URLs

What the codes mean is the whole point of the output: Glassdoor, AmbitionBox
and LinkedIn all answer a script differently from a browser, and treating their
bot-blocks as "dead link" would be worse than not checking at all.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hrintel as H  # noqa: E402

# A browser User-Agent, because these pages are being opened the way a person
# opens them - one at a time, on request. The collector's own agent identifies
# itself as a bot, which is right for feeds and wrong here.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Statuses that mean "the page is there, the site just will not talk to a
# script". Reporting these as broken would send somebody hunting for a URL
# that is perfectly correct.
BOT_BLOCK = {403: "blocked as a bot (normal here - open it yourself to confirm)",
             429: "rate limited (normal here - try again later)",
             999: "LinkedIn's bot block (normal - the page is almost certainly fine)"}


def verdict(url: str, timeout: int) -> tuple[str, str]:
    """(state, detail). state is one of ok / blocked / MISSING / error."""
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA},
                                     method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return "ok", f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in BOT_BLOCK:
            return "blocked", f"HTTP {exc.code} - {BOT_BLOCK[exc.code]}"
        if exc.code in (400, 404, 410):
            # 400 is what Google Alerts returns for a feed id that does not
            # exist, which is the commonest way an alert turns out never to
            # have been saved.
            return "MISSING", f"HTTP {exc.code} - no such page or feed. Check the URL in config."
        return "error", f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return "error", str(exc)


def feed_targets() -> list[tuple[str, str, str, str]]:
    """Every enabled feed URL, so a dead alert is caught when it is added.

    A Google Alerts RSS URL that returns 400 means the alert behind it does
    not exist - usually because it was never saved, since Google declines to
    create an alert whose query matches nothing. That is indistinguishable
    from a quiet week unless somebody reads the collector's output, and a
    channel assumed to be fed is not prompted for by hand either. So it is
    worth being able to ask directly.
    """
    rows = []
    for feed in H.load_yaml("sources").get("feeds", []):
        url = str(feed.get("url") or "").strip()
        if not feed.get("enabled") or not url or H.is_todo(url):
            continue
        rows.append(("feed", "Feed", feed["id"], url))
    return rows


def targets(platform_filter: str = "") -> list[tuple[str, str, str, str]]:
    """(platform_id, platform_name, entity_name, url) for every page configured."""
    entities = H.entity_names()
    rows = []
    for platform in H.load_yaml("sources").get("platforms", []):
        if platform_filter and platform["id"] != platform_filter:
            continue
        for entity_id, url in (platform.get("urls") or {}).items():
            text = str(url or "").strip()
            if not text or text.lower() == "none" or H.is_todo(text):
                continue
            rows.append((platform["id"], platform["name"],
                         entities.get(entity_id, entity_id), text))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", default="", help="check one platform only")
    parser.add_argument("--feeds", action="store_true",
                        help="check the enabled feed URLs instead of the pages")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="seconds between requests (default 2)")
    args = parser.parse_args()

    timeout = int(H.load_yaml("settings").get("collector", {}).get("timeout_seconds", 20))
    rows = feed_targets() if args.feeds else targets(args.platform)
    if not rows:
        print("No enabled feeds configured." if args.feeds else
              ("No pages configured to check." if not args.platform
               else f"No pages configured for {args.platform!r}."))
        return 0

    what = "feed" if args.feeds else "configured page"
    print(f"Opening {len(rows)} {what}(s). This touches real sites, so it is "
          "slow on purpose.\n")
    missing, blocked, unknown = [], [], []
    for index, (_pid, platform, entity, url) in enumerate(rows):
        state, detail = verdict(url, timeout)
        mark = {"ok": "  ok     ", "blocked": "  ~      ",
                "MISSING": "  MISSING", "error": "  ?      "}[state]
        print(f"{mark} {platform:<14} {entity:<20} {detail}")
        if state != "ok":
            print(f"           {url}")
        if state == "MISSING":
            missing.append((platform, entity, url))
        elif state == "blocked":
            blocked.append((platform, entity, url))
        elif state == "error":
            unknown.append((platform, entity, url, detail))
        if index < len(rows) - 1:
            time.sleep(args.delay)

    print()
    if missing:
        print(f"{len(missing)} do not exist. Fix these in config/sources.yaml - a dead "
              "page is ticked off every week like a real one, and a dead feed leaves "
              "its channel swept by nobody:")
        for platform, entity, url in missing:
            print(f"  {platform} / {entity}: {url}")
    if blocked:
        print(f"{len(blocked)} page(s) refused a script. That is expected on Glassdoor, "
              "AmbitionBox and LinkedIn and says nothing about whether the page is "
              "right - open those in a browser once, by hand.")
    if unknown:
        # The whole point of this script is to stop a page nobody checked
        # reading as a page that was fine. Printing "every page answered"
        # because the request never got out would be the same bug wearing a
        # different hat.
        print(f"{len(unknown)} page(s) COULD NOT BE CHECKED - that is not the same as "
              "checked and fine. Network, proxy or DNS, not the page:")
        for platform, entity, url, detail in unknown:
            print(f"  {platform} / {entity}: {detail}")
    if not missing and not blocked and not unknown:
        print("Every configured page answered.")
    return 1 if missing or unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
