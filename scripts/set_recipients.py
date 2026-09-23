#!/usr/bin/env python3
"""Set a recipient's address everywhere it appears, in one go.

The same four people are listed twice in config/recipients.yaml - once for the
weekly digest and once for red-flag alerts. Editing by hand, the digest block
is the one you see first and the one whose warning you are chasing, so it is
the one that gets filled. The red_flag block is then still TODO, and nothing
stops a send: the digest goes out looking finished while an escalation - the
output the same-day protocol exists for - has nowhere to go.

So set them by name and let this touch every block:

    python3 scripts/set_recipients.py Mahendra mahendra@rkgroup.biz
    python3 scripts/set_recipients.py --show

Comments and layout are preserved; only the address on a matching line moves.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hrintel as H  # noqa: E402

RECIPIENTS_YAML = os.path.join(os.path.dirname(HERE), "config", "recipients.yaml")

# Deliberately loose. It is here to catch a typo - a missing @, a stray space,
# a name pasted into the address column - not to adjudicate what a valid
# address is. Anything that reaches a mail server can be typed in by hand.
LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def blocks() -> dict[str, list[dict]]:
    return H.load_yaml("recipients") or {}


def show() -> int:
    data = blocks()
    for block in ("digest", "red_flag", "escalation_only"):
        people = data.get(block) or []
        print(f"\n{block}")
        if not people:
            print("  (nobody)")
            continue
        for person in people:
            email = str(person.get("email") or "")
            mark = "TODO" if (not email or H.is_todo(email)) else "ok  "
            print(f"  {mark}  {person.get('name', '?'):<12} {email}")

    names = {p.get("name") for p in (data.get("digest") or [])}
    missing = [n for n in names
               if any(H.is_todo(str(p.get("email") or "")) or not p.get("email")
                      for block in ("digest", "red_flag")
                      for p in (data.get(block) or []) if p.get("name") == n)]
    print()
    if missing:
        print(f"{len(missing)} still to set: {', '.join(sorted(m for m in missing if m))}")
        print("  python3 scripts/set_recipients.py <name> <email>")
    else:
        print("Every recipient has an address in every block.")
    return 0


def apply(name: str, email: str) -> tuple[int, list[str]]:
    """Rewrite every `email:` that follows a `- name: <name>`. Returns (count, blocks)."""
    with open(RECIPIENTS_YAML, encoding="utf-8") as fh:
        lines = fh.readlines()

    out, changed, where, block, pending = [], 0, [], "", False
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-") and not line[:1].isspace():
            block = stripped[:-1]
        if re.match(r"^\s*-\s*name:\s*", line):
            found = re.sub(r"^\s*-\s*name:\s*", "", line).strip().strip("\"'")
            pending = found.lower() == name.lower()
        elif pending and re.match(r"^\s*email:\s*", line):
            indent = line[:len(line) - len(line.lstrip())]
            out.append(f'{indent}email: "{email}"\n')
            changed += 1
            where.append(block)
            pending = False
            continue
        out.append(line)

    if changed:
        with open(RECIPIENTS_YAML, "w", encoding="utf-8") as fh:
            fh.writelines(out)
    return changed, where


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", nargs="?", help="the recipient's name as it appears in the file")
    parser.add_argument("email", nargs="?")
    parser.add_argument("--show", action="store_true", help="who is set and who is not")
    args = parser.parse_args()

    if args.show or not args.name:
        return show()
    if not args.email:
        print("Need an address: set_recipients.py <name> <email>", file=sys.stderr)
        return 2
    if not LOOKS_LIKE_EMAIL.match(args.email):
        print(f"{args.email!r} does not look like an address. Nothing written.", file=sys.stderr)
        return 2

    known = {p.get("name") for block in ("digest", "red_flag", "escalation_only")
             for p in (blocks().get(block) or [])}
    if not any((n or "").lower() == args.name.lower() for n in known):
        print(f"No recipient named {args.name!r}. One of: "
              f"{', '.join(sorted(n for n in known if n))}", file=sys.stderr)
        return 2

    changed, where = apply(args.name, args.email)
    print(f"Set {args.name} to {args.email} in {changed} place(s): {', '.join(where)}.")
    if "red_flag" not in where:
        print("NOTE: not set in the red_flag block - escalations would not reach them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
