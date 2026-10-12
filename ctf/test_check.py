"""Tests for the CTF verifier, including hostile issue bodies.

Run from the repository root:  python -m unittest ctf.test_check
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from ctf import check

FLAG = "FLAG{TEST}"
README = "intro\n<!-- HALL:START -->\n_Nobody yet. Be the first._\n<!-- HALL:END -->\noutro\n"


class Proof(unittest.TestCase):
    def test_expected_is_per_user_and_case_insensitive_on_login(self):
        self.assertEqual(check.expected(FLAG, "OctoCat"),
                         check.expected(FLAG, "octocat"))
        self.assertNotEqual(check.expected(FLAG, "octocat"),
                            check.expected(FLAG, "hubot"))

    def test_correct_wrong_invalid(self):
        good = check.expected(FLAG, "octocat")
        self.assertEqual(check.verdict(FLAG, "octocat", "### Proof\n\n" + good),
                         "correct")
        self.assertEqual(check.verdict(FLAG, "octocat", "0" * 64), "wrong")
        self.assertEqual(check.verdict(FLAG, "octocat", "no proof here"),
                         "invalid")
        self.assertEqual(check.verdict(FLAG, "octocat", None), "invalid")

    def test_uppercase_proof_is_accepted(self):
        good = check.expected(FLAG, "octocat").upper()
        self.assertEqual(check.verdict(FLAG, "octocat", good), "correct")

    def test_someone_elses_correct_proof_does_not_work(self):
        stolen = check.expected(FLAG, "octocat")
        self.assertEqual(check.verdict(FLAG, "copycat", stolen), "wrong")

    def test_posting_the_raw_flag_is_not_accepted(self):
        self.assertEqual(check.verdict(FLAG, "octocat", FLAG), "leaked")
        good = check.expected(FLAG, "octocat")
        self.assertEqual(check.verdict(FLAG, "octocat", good + " " + FLAG.lower()),
                         "leaked")

    def test_hex_embedded_in_a_longer_run_is_ignored(self):
        good = check.expected(FLAG, "octocat")
        self.assertEqual(check.verdict(FLAG, "octocat", "a" + good), "invalid")

    def test_hostile_bodies_are_only_ever_data(self):
        good = check.expected(FLAG, "octocat")
        for body in ['$(touch /tmp/pwned) ' + good,
                     '`id` "; rm -rf / #\n' + good,
                     '${{ secrets.CTF_FLAG }}\n' + good,
                     '<!-- HALL:END --> injected\n' + good]:
            self.assertEqual(check.verdict(FLAG, "octocat", body), "correct")


class Hall(unittest.TestCase):
    def test_first_solver_replaces_placeholder(self):
        text, added = check.add_to_hall(README, "octocat", "2026-10-12")
        self.assertTrue(added)
        self.assertIn("| 1 | [@octocat](https://github.com/octocat) | 2026-10-12 |",
                      text)
        self.assertNotIn("Nobody yet", text)
        self.assertTrue(text.startswith("intro\n") and text.endswith("outro\n"))

    def test_ranks_increase_and_duplicates_are_skipped(self):
        text, _ = check.add_to_hall(README, "octocat", "2026-10-12")
        text, added = check.add_to_hall(text, "hubot", "2026-10-13")
        self.assertTrue(added)
        self.assertIn("| 2 | [@hubot]", text)
        again, added = check.add_to_hall(text, "OctoCat", "2026-10-14")
        self.assertFalse(added)
        self.assertEqual(again, text)

    def test_logins_github_would_reject_are_refused(self):
        for bad in ["-lead", "trail-", "dou--ble", "a" * 40, "x](javascript:1)",
                    "has space", ""]:
            with self.assertRaises(ValueError):
                check.add_to_hall(README, bad, "2026-10-12")

    def test_missing_markers_fail_loudly(self):
        with self.assertRaises(ValueError):
            check.add_to_hall("no markers", "octocat", "2026-10-12")

    def test_list_is_capped(self):
        text = README
        with mock.patch.object(check, "MAX_ENTRIES", 2):
            text, _ = check.add_to_hall(text, "a1", "d")
            text, _ = check.add_to_hall(text, "a2", "d")
            text, added = check.add_to_hall(text, "a3", "d")
        self.assertFalse(added)


class Main(unittest.TestCase):
    def run_main(self, login, body, flag=FLAG):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "README.md").write_text(README, encoding="utf-8")
            event = tmp / "event.json"
            event.write_text(json.dumps(
                {"issue": {"number": 7, "user": {"login": login},
                           "body": body}}), encoding="utf-8")
            out = tmp / "out.txt"
            env = {"GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(out),
                   "CTF_FLAG": flag}
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with mock.patch.dict(os.environ, env):
                    code = check.main()
            finally:
                os.chdir(cwd)
            return (code, out.read_text(encoding="utf-8") if out.exists() else "",
                    (tmp / "README.md").read_text(encoding="utf-8"))

    def test_correct_submission_updates_readme(self):
        code, out, readme = self.run_main(
            "octocat", check.expected(FLAG, "octocat"))
        self.assertEqual(code, 0)
        self.assertIn("result=correct", out)
        self.assertIn("added=true", out)
        self.assertIn("@octocat", readme)

    def test_wrong_submission_leaves_readme_alone(self):
        code, out, readme = self.run_main("octocat", "f" * 64)
        self.assertIn("result=wrong", out)
        self.assertEqual(readme, README)

    def test_missing_secret_fails_closed(self):
        code, out, readme = self.run_main("octocat", "f" * 64, flag="")
        self.assertEqual(code, 1)
        self.assertEqual(readme, README)


if __name__ == "__main__":
    unittest.main()
