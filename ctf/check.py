#!/usr/bin/env python3
"""Verify a capture-the-flag submission and update the hall of fame.

Runs inside GitHub Actions on `issues: opened`. Everything a visitor controls
-- the issue title and body -- is untrusted. This script is the only thing that
reads it, and it treats it strictly as data:

* It is read from the event payload file, never interpolated into a shell
  command or a workflow expression, so there is nothing to inject into.
* The only thing taken from the body is a 64-character lowercase hex string.
  Anything else is ignored; nothing from the body is echoed, executed or
  written anywhere.
* Visitors never post the flag. They post sha256("<flag>:<their login>"), so
  a correct answer in a public issue is useless to anyone else, and the flag
  itself only exists in an Actions secret. A body or title that carries the
  flag anyway, with or without FLAG{}, is reported as 'leaked'.
* The comparison is constant-time.
* The login comes from GitHub's own payload, and is still checked against
  GitHub's username rules before it is written into the README.

Standard library only: no third-party package can be swapped underneath it.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import pathlib
import re
import sys

PROOF = re.compile(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
START, END = "<!-- HALL:START -->", "<!-- HALL:END -->"
EMPTY = "_Nobody yet. Be the first._"
MAX_ENTRIES = 200


def expected(flag: str, login: str) -> str:
    """The proof a given user must submit for a given flag."""
    return hashlib.sha256(("%s:%s" % (flag, login.lower())).encode()).hexdigest()


def extract_proof(body: str | None) -> str | None:
    """The first standalone 64-hex string in the body, or None."""
    if not body:
        return None
    found = PROOF.search(body.lower())
    return found.group(1) if found else None


def leaks(flag: str, text: str | None) -> bool:
    """Whether text carries the flag, wrapped or not."""
    if not text:
        return False
    low = text.lower()
    inner = flag[flag.find("{") + 1:flag.rfind("}")].lower()
    return "flag{" in low or (len(inner) >= 4 and inner in low)


def verdict(flag: str, login: str, body: str | None,
            title: str | None = None) -> str:
    """'correct', 'wrong', 'invalid' (no proof found) or 'leaked'.

    'leaked' means the visitor pasted the flag itself, in the body or the
    title, wrapped in FLAG{} or not; the workflow redacts and locks the issue.
    """
    if leaks(flag, body) or leaks(flag, title):
        return "leaked"
    proof = extract_proof(body)
    if proof is None:
        return "invalid"
    if hmac.compare_digest(proof, expected(flag, login)):
        return "correct"
    return "wrong"


def add_to_hall(readme: str, login: str, date: str) -> tuple[str, bool]:
    """Append a solver between the hall-of-fame markers.

    Returns the new text and whether anything changed. A solver already listed
    is not added twice; the list is capped so a flood cannot grow the README
    without bound.
    """
    if not LOGIN.match(login):
        raise ValueError("refusing to write a login GitHub would not allow")
    start, end = readme.find(START), readme.find(END)
    if start < 0 or end < start:
        raise ValueError("hall-of-fame markers missing from README")
    inner = readme[start + len(START):end]
    entries = [ln for ln in inner.strip().splitlines()
               if ln.startswith("| ") and "@" in ln]
    if any("[@%s]" % login.lower() in ln.lower() for ln in entries):
        return readme, False
    if len(entries) >= MAX_ENTRIES:
        return readme, False
    rank = len(entries) + 1
    entries.append("| %d | [@%s](https://github.com/%s) | %s |"
                   % (rank, login, login, date))
    table = "\n".join(["| # | Solver | Date |", "|---|---|---|"] + entries)
    return readme[:start + len(START)] + "\n" + table + "\n" + readme[end:], True


def _output(**pairs: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join("%s=%s\n" % kv for kv in pairs.items())
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(lines)
    else:
        sys.stdout.write(lines)


def main(argv: list[str] | None = None) -> int:
    """Verify only, or with --record also add a correct solver to README.md.

    The workflow verifies in a read-only job and records in a separate job
    that holds the write token, re-verifying there rather than trusting an
    output handed across.
    """
    record = "--record" in (sys.argv[1:] if argv is None else argv)
    flag = os.environ.get("CTF_FLAG", "")
    if not flag:
        print("CTF_FLAG secret is not configured", file=sys.stderr)
        return 1
    event = json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"])
                       .read_text(encoding="utf-8"))
    issue = event["issue"]
    login = issue["user"]["login"]
    result = verdict(flag, login, issue.get("body"), issue.get("title"))
    added = False
    if result == "correct" and record:
        readme = pathlib.Path("README.md")
        text, added = add_to_hall(readme.read_text(encoding="utf-8"), login,
                                  datetime.date.today().isoformat())
        if added:
            readme.write_text(text, encoding="utf-8")
    _output(result=result, added="true" if added else "false")
    print("result=%s added=%s" % (result, added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
