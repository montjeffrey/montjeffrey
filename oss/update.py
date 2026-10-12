#!/usr/bin/env python3
"""Rebuild the README's open-source section from the GitHub API.

Runs daily in GitHub Actions (.github/workflows/oss.yml), so the section is
never maintained by hand:

* Maintaining: repos I own that are public, licensed, not forks and not
  archived, minus any listed under "exclude" in oss/config.json. Making a repo
  public with a license is what puts it here.
* Contributing: public repos owned by someone else where I have a merged pull
  request, with the merged count, PRs still in review, and where I rank among
  the project's contributors. A project where I only have PRs in review is
  listed too, so it shows up the day the work starts, not the day it lands.

Everything the API says about other people's repos is untrusted text. Repo
names must match GitHub's naming rules or the repo is dropped, links are built
only from those validated names, and descriptions are entity-escaped so they
cannot inject links, images, HTML or the section's own markers.

If the API fails, the script exits non-zero and leaves README.md untouched.
The date in the footer only moves when the content does, so a quiet day makes
no commit. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,39}$")
LAST_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="last"')
START, END = "<!-- OSS:START -->", "<!-- OSS:END -->"
FOOTER = "<sub>Updated "
SEARCH_PAGES = 10        # the search API stops at 1,000 results anyway
CONTRIBUTOR_PAGES = 5    # look for my rank among the top 500 contributors
HERE = pathlib.Path(__file__).resolve().parent

# Every character that can start markdown or HTML syntax becomes an entity.
_ENTITY = {c: "&#%d;" % ord(c) for c in "&<>\"'\\`*_[]()|#!~:@"}


def text(value: object, limit: int = 140) -> str:
    """Untrusted text made safe for one markdown table cell."""
    s = " ".join(str(value or "").split())
    s = "".join(c for c in s if c.isprintable())
    if len(s) > limit:
        s = s[:limit - 1].rstrip() + "…"
    return "".join(_ENTITY.get(c, c) for c in s)


def valid_repo(full: str) -> bool:
    """owner/name, both spelled the way GitHub allows."""
    owner, _, name = full.partition("/")
    return (bool(LOGIN.match(owner)) and bool(REPO_NAME.match(name))
            and name.strip(".") != "")


def count(n: int) -> str:
    """277030 -> 277k, 1234 -> 1.2k."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return ("%.1fk" % (n / 1000)).replace(".0k", "k")
    return "%dk" % (n // 1000)


class GitHub:
    """A minimal, read-only REST client."""

    def __init__(self, token: str | None = None, base: str = API):
        self.token, self.base = token, base

    def get(self, path: str, **params: object) -> tuple[object, str]:
        """(decoded JSON, Link header). A 404 or empty body is (None, "")."""
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "montjeffrey-profile"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body, link = resp.read(), resp.headers.get("Link", "")
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None, ""
            raise
        return (json.loads(body) if body else None), link


def own_projects(api: GitHub, login: str, exclude: list[str]) -> list[dict]:
    skip = {n.lower() for n in exclude} | {login.lower()}
    repos: list[dict] = []
    for page in range(1, 11):
        data, _ = api.get("/users/%s/repos" % login, type="owner",
                          per_page=100, page=page)
        batch = data if isinstance(data, list) else []
        repos.extend(batch)
        if len(batch) < 100:
            break
    out = []
    for r in repos:
        name = str(r.get("name") or "")
        owner = str((r.get("owner") or {}).get("login") or "")
        full = "%s/%s" % (login, name)
        if (owner.lower() != login.lower() or r.get("fork") or r.get("archived")
                or r.get("private") or not r.get("license")
                or name.lower() in skip or not valid_repo(full)):
            continue
        rel, _ = api.get("/repos/%s/releases/latest" % full)
        tag = str((rel or {}).get("tag_name") or "")
        out.append({"full": full, "name": name,
                    "about": r.get("description") or "",
                    "stars": int(r.get("stargazers_count") or 0),
                    "release": tag if TAG.match(tag) else ""})
    out.sort(key=lambda p: (-p["stars"], p["name"].lower()))
    return out


def search_prs(api: GitHub, query: str) -> dict[str, int]:
    """Pull requests matching a search, counted per repository."""
    prefix = api.base + "/repos/"
    counts: dict[str, int] = {}
    for page in range(1, SEARCH_PAGES + 1):
        data, _ = api.get("/search/issues", q=query, per_page=100, page=page)
        items = (data or {}).get("items") or []
        for item in items:
            url = str(item.get("repository_url") or "")
            full = url[len(prefix):] if url.startswith(prefix) else ""
            if valid_repo(full):
                counts[full] = counts.get(full, 0) + 1
        if len(items) < 100:
            break
    return counts


def standing(api: GitHub, full: str, login: str) -> tuple[int | None, int | None]:
    """(my rank, number of contributors). Either is None when unknown.

    GitHub refuses to list contributors for some very large repos, so an error
    here only drops the rank; it never fails the run.
    """
    path = "/repos/%s/contributors" % full
    try:
        first, link = api.get(path, per_page=100)
        if not isinstance(first, list):
            return None, None
        found = LAST_PAGE.search(link)
        pages = int(found.group(1)) if found else 1
        if pages == 1:
            total = len(first)
        else:
            last, _ = api.get(path, per_page=100, page=pages)
            total = (pages - 1) * 100 + len(last or [])
        batch, page = first, 1
        while True:
            for i, c in enumerate(batch):
                if str(c.get("login") or "").lower() == login.lower():
                    return (page - 1) * 100 + i + 1, total
            page += 1
            if page > min(pages, CONTRIBUTOR_PAGES):
                return None, total
            batch, _ = api.get(path, per_page=100, page=page)
            batch = batch if isinstance(batch, list) else []
    except urllib.error.HTTPError:
        return None, None


def upstream_projects(api: GitHub, login: str,
                      notes: dict[str, str]) -> list[dict]:
    base = "is:pr is:public author:%s -user:%s" % (login, login)
    merged = search_prs(api, base + " is:merged")
    in_review = search_prs(api, base + " is:open")
    notes = {k.lower(): v for k, v in notes.items()}
    out = []
    for full in sorted(set(merged) | set(in_review)):
        repo, _ = api.get("/repos/%s" % full)
        if not isinstance(repo, dict) or repo.get("private"):
            continue
        canonical = str(repo.get("full_name") or full)
        if not valid_repo(canonical):
            continue
        if canonical.split("/")[0].lower() == login.lower():
            continue
        n = merged.get(full, 0)
        rank, total = standing(api, canonical, login) if n else (None, None)
        out.append({"full": canonical,
                    "about": notes.get(canonical.lower(),
                                       repo.get("description") or ""),
                    "stars": int(repo.get("stargazers_count") or 0),
                    "merged": n, "open": in_review.get(full, 0),
                    "rank": rank, "total": total})
    out.sort(key=lambda p: (-p["merged"], -p["open"], -p["stars"],
                            p["full"].lower()))
    return out


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def render(login: str, own: list[dict], upstream: list[dict]) -> str:
    lines: list[str] = []
    if own:
        lines += ["**Maintaining** · %s" % _plural(len(own), "project"), "",
                  "| Project | What it does | Release |", "|---|---|---|"]
        for p in own:
            star = " ★ %s" % count(p["stars"]) if p["stars"] else ""
            rel = ("[%s](https://github.com/%s/releases/tag/%s)"
                   % (text(p["release"]), p["full"], p["release"])
                   if p["release"] else "—")
            lines.append("| [**%s**](https://github.com/%s)%s | %s | %s |"
                         % (p["name"], p["full"], star, text(p["about"]), rel))
        lines.append("")
    if upstream:
        prs = sum(p["merged"] for p in upstream)
        projects = sum(1 for p in upstream if p["merged"])
        lines += ["**Contributing** · %s merged across %s"
                  % (_plural(prs, "pull request"), _plural(projects, "project")),
                  "", "| Project | What it does | ★ | Merged | Standing |",
                  "|---|---|---|---|---|"]
        for p in upstream:
            prs_url = ("https://github.com/%s/pulls?q=is%%3Apr+author%%3A%s"
                       % (p["full"], login))
            work = ("[%d](%s+is%%3Amerged)" % (p["merged"], prs_url)
                    if p["merged"] else "—")
            if p["open"]:
                work += " · [%d in review](%s+is%%3Aopen)" % (p["open"], prs_url)
            if p["rank"] and p["total"]:
                rank = "#%d of %d contributors" % (p["rank"], p["total"])
            elif p["rank"]:
                rank = "#%d contributor" % p["rank"]
            else:
                rank = "—"
            lines.append("| [%s](https://github.com/%s) | %s | %s | %s | %s |"
                         % (p["full"], p["full"], text(p["about"], 300),
                            count(p["stars"]), work, rank))
        lines.append("")
    return "\n".join(lines).strip()


def splice(readme: str, body: str, today: str) -> tuple[str, bool]:
    """Put the body between the markers. Unchanged content changes nothing,
    not even the date, so a quiet day makes no commit."""
    start, end = readme.find(START), readme.find(END)
    if start < 0 or end < start:
        raise ValueError("open-source markers missing from README")
    inner = readme[start + len(START):end]
    old = "\n".join(ln for ln in inner.strip().splitlines()
                    if not ln.startswith(FOOTER)).strip()
    if old == body.strip():
        return readme, False
    new = ("\n%s\n\n%s%s · rebuilt daily from the GitHub API by "
           "[oss/update.py](oss/update.py)</sub>\n" % (body.strip(), FOOTER, today))
    return readme[:start + len(START)] + new + readme[end:], True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the section instead of writing it")
    args = ap.parse_args(argv)
    login = os.environ.get("GH_LOGIN") or "montjeffrey"
    if not LOGIN.match(login):
        print("GH_LOGIN is not a GitHub login", file=sys.stderr)
        return 1
    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    api = GitHub(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    own = own_projects(api, login, config.get("exclude", []))
    upstream = upstream_projects(api, login, config.get("notes", {}))
    if not own and not upstream:
        # Far likelier an API hiccup than a real loss of every project.
        print("refusing to empty the section: the API returned nothing",
              file=sys.stderr)
        return 1
    body = render(login, own, upstream)
    if args.dry_run:
        sys.stdout.buffer.write((body + "\n").encode("utf-8"))
        return 0
    path = pathlib.Path(args.readme)
    new, changed = splice(path.read_text(encoding="utf-8"), body,
                          datetime.date.today().isoformat())
    if changed:
        path.write_text(new, encoding="utf-8", newline="\n")
    print("changed=%s maintaining=%d contributing=%d"
          % (changed, len(own), len(upstream)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
