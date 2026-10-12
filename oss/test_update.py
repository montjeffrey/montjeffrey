"""Tests for the open-source section generator, against a fake API.

Run from the repository root:  python -m unittest oss.test_update
"""

import io
import unittest
import urllib.error

from oss import update

API = update.API
LOGIN = "montjeffrey"
README = "intro\n<!-- OSS:START -->\nold\n<!-- OSS:END -->\noutro\n"


class FakeApi(update.GitHub):
    """Answers from a table keyed by (path, page, query); unknown is a 404."""

    def __init__(self, routes):
        super().__init__(token=None)
        self.routes = routes

    def get(self, path, **params):
        key = (path, params.get("page", 1), params.get("q"))
        answer = self.routes.get(key, (None, ""))
        if isinstance(answer, Exception):
            raise answer
        return answer


def repo(name, **kw):
    r = {"name": name, "owner": {"login": LOGIN}, "fork": False,
         "archived": False, "private": False, "license": {"key": "mit"},
         "description": name + " does things", "stargazers_count": 0}
    r.update(kw)
    return r


def pr(full):
    return {"repository_url": "%s/repos/%s" % (API, full)}


def link(path, last):
    return '<%s%s?per_page=100&page=%d>; rel="last"' % (API, path, last)


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


class Text(unittest.TestCase):
    def test_hostile_descriptions_cannot_inject_markup(self):
        evil = ('[click](javascript:alert(1)) <img src=x onerror=1> | cell '
                '<!-- OSS:END --> ![x](http://t/x.png) `code` @someone')
        out = update.text(evil, limit=500)
        for ch in "<>[]()|`!@":
            self.assertNotIn(ch, out)
        self.assertNotIn(update.END, out)

    def test_newlines_collapse_and_long_text_truncates(self):
        self.assertEqual(update.text("a\n\n| b"), "a &#124; b")
        self.assertEqual(len(update.text("x" * 500, limit=10)), 10)

    def test_repo_names(self):
        self.assertTrue(update.valid_repo("affaan-m/ECC"))
        self.assertTrue(update.valid_repo("a/b.c_d-e"))
        for bad in ["a", "a/", "/b", "-a/b", "a/..", "a/b/c", "a/b c", "a/b)"]:
            self.assertFalse(update.valid_repo(bad), bad)

    def test_count(self):
        self.assertEqual(update.count(0), "0")
        self.assertEqual(update.count(1000), "1k")
        self.assertEqual(update.count(1234), "1.2k")
        self.assertEqual(update.count(277030), "277k")


class Own(unittest.TestCase):
    def test_only_public_licensed_originals_count(self):
        repos = [repo("landfirst", stargazers_count=3), repo("compute-pool"),
                 repo("a-fork", fork=True), repo("old", archived=True),
                 repo("secret", private=True), repo("site", license=None),
                 repo(LOGIN), repo("hidden"),
                 repo("theirs", owner={"login": "someone"})]
        api = FakeApi({
            ("/users/%s/repos" % LOGIN, 1, None): (repos, ""),
            ("/repos/%s/landfirst/releases/latest" % LOGIN, 1, None):
                ({"tag_name": "v0.3.0"}, ""),
            ("/repos/%s/compute-pool/releases/latest" % LOGIN, 1, None):
                ({"tag_name": "v1](http://evil)"}, ""),
        })
        own = update.own_projects(api, LOGIN, ["Hidden"])
        self.assertEqual([p["name"] for p in own], ["landfirst", "compute-pool"])
        self.assertEqual(own[0]["release"], "v0.3.0")
        self.assertEqual(own[1]["release"], "", "a hostile tag is dropped")


class Upstream(unittest.TestCase):
    def routes(self):
        merged = "is:pr is:public author:%s -user:%s is:merged" % (LOGIN, LOGIN)
        opened = "is:pr is:public author:%s -user:%s is:open" % (LOGIN, LOGIN)
        contrib = "/repos/affaan-m/ECC/contributors"
        return {
            ("/search/issues", 1, merged):
                ({"items": [pr("affaan-m/ECC")] * 3
                  + [{"repository_url": "https://evil.example/repos/x/y"},
                     pr("bad name/x")]}, ""),
            ("/search/issues", 1, opened):
                ({"items": [pr("affaan-m/ECC"), pr("other/lib")]}, ""),
            ("/repos/affaan-m/ECC", 1, None):
                ({"full_name": "affaan-m/ECC", "stargazers_count": 277030,
                  "description": "upstream text"}, ""),
            ("/repos/other/lib", 1, None):
                ({"full_name": "other/lib", "stargazers_count": 40,
                  "description": "A <b>library</b>"}, ""),
            (contrib, 1, None):
                ([{"login": "u%d" % i} for i in range(100)], link(contrib, 3)),
            (contrib, 2, None):
                ([{"login": "u"}] * 4 + [{"login": "MontJeffrey"}]
                 + [{"login": "v"}] * 95, ""),
            (contrib, 3, None): ([{"login": "w"}] * 12, ""),
        }

    def test_merged_and_in_review_projects_with_rank(self):
        up = update.upstream_projects(FakeApi(self.routes()), LOGIN,
                                      {"Affaan-M/ECC": "my note"})
        self.assertEqual([p["full"] for p in up], ["affaan-m/ECC", "other/lib"])
        ecc, lib = up
        self.assertEqual((ecc["merged"], ecc["open"]), (3, 1))
        self.assertEqual((ecc["rank"], ecc["total"]), (105, 212))
        self.assertEqual(ecc["about"], "my note")
        self.assertEqual((lib["merged"], lib["open"], lib["rank"]), (0, 1, None))

    def test_contributor_list_errors_only_drop_the_rank(self):
        routes = self.routes()
        routes[("/repos/affaan-m/ECC/contributors", 1, None)] = http_error(403)
        ecc = update.upstream_projects(FakeApi(routes), LOGIN, {})[0]
        self.assertEqual((ecc["merged"], ecc["rank"]), (3, None))

    def test_private_and_self_owned_repos_are_skipped(self):
        routes = self.routes()
        routes[("/repos/other/lib", 1, None)] = ({"private": True}, "")
        routes[("/repos/affaan-m/ECC", 1, None)] = (
            {"full_name": "%s/ECC" % LOGIN}, "")
        self.assertEqual(update.upstream_projects(FakeApi(routes), LOGIN, {}), [])

    def test_render(self):
        up = update.upstream_projects(FakeApi(self.routes()), LOGIN, {})
        own = [{"full": "%s/landfirst" % LOGIN, "name": "landfirst",
                "about": "merge planner", "stars": 0, "release": "v0.3.0"}]
        out = update.render(LOGIN, own, up)
        self.assertIn("**Maintaining** · 1 project", out)
        self.assertIn("[**landfirst**](https://github.com/%s/landfirst) |" % LOGIN,
                      out, "no star badge at zero stars")
        self.assertIn("releases/tag/v0.3.0", out)
        self.assertIn("**Contributing** · 3 pull requests merged across "
                      "1 project", out)
        self.assertIn("| 277k | [3](", out)
        self.assertIn("1 in review", out)
        self.assertIn("#105 of 212 contributors", out)
        self.assertNotIn("<b>", out)


class Splice(unittest.TestCase):
    def test_writes_between_markers_with_a_date(self):
        text, changed = update.splice(README, "**new**", "2026-10-12")
        self.assertTrue(changed)
        self.assertTrue(text.startswith("intro\n<!-- OSS:START -->\n**new**\n"))
        self.assertIn("<sub>Updated 2026-10-12", text)
        self.assertTrue(text.endswith("<!-- OSS:END -->\noutro\n"))

    def test_unchanged_content_keeps_the_old_date(self):
        text, _ = update.splice(README, "**new**", "2026-10-12")
        again, changed = update.splice(text, "**new**", "2026-10-13")
        self.assertFalse(changed)
        self.assertEqual(again, text)

    def test_missing_markers_fail_loudly(self):
        with self.assertRaises(ValueError):
            update.splice("no markers", "x", "2026-10-12")


class Main(unittest.TestCase):
    def test_empty_api_answer_never_wipes_the_section(self):
        empty = FakeApi({})
        orig = update.GitHub
        update.GitHub = lambda token=None: empty
        try:
            self.assertEqual(update.main(["--readme", "does-not-exist.md"]), 1)
        finally:
            update.GitHub = orig


if __name__ == "__main__":
    unittest.main()
