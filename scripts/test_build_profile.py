"""Tests for the CTF layer of the profile generator.

Run from the repository root:  python -m unittest scripts.test_build_profile
"""

import base64
import codecs
import unittest

from scripts import build_profile as bp

FLAG = "FLAG{ALPHA_BRAVO_CHARLIE_DELTA}"
KEYS = ("QUARANTINE", "BUILDPROVENANCE", "MERGETREE", "TOOMANYREQUESTS")


class Vigenere(unittest.TestCase):
    def test_round_trip(self):
        for piece, key in zip(["ALPHA", "BRAVO", "CHARLIE", "DELTA"], KEYS):
            enc = bp.vigenere(piece, key)
            self.assertNotEqual(enc, piece)
            self.assertEqual(bp.vigenere(enc, key, -1), piece)

    def test_known_vector(self):
        self.assertEqual(bp.vigenere("ATTACKATDAWN", "LEMONLEMONLE"),
                         "LXFOPVEFRNHR")


class Pieces(unittest.TestCase):
    def test_outer_encodings_wrap_the_ciphertext(self):
        hexa, b32, rot, plain = bp.pieces(FLAG, KEYS)
        a = bytes.fromhex(hexa.replace(" ", "")).decode()
        b = base64.b32decode(b32).decode()
        c = codecs.decode(rot, "rot13")
        got = [bp.vigenere(x, k, -1) for x, k in zip([a, b, c, plain], KEYS)]
        self.assertEqual(got, ["ALPHA", "BRAVO", "CHARLIE", "DELTA"])

    def test_no_piece_survives_in_the_clear(self):
        out = " ".join(bp.pieces(FLAG, KEYS))
        for word in ["ALPHA", "BRAVO", "CHARLIE", "DELTA"]:
            self.assertNotIn(word, out)

    def test_short_keys_are_refused(self):
        with self.assertRaises(SystemExit):
            bp.pieces(FLAG, ("QUA", "B", "M", "T"))

    def test_keys_are_letters_only_and_need_four(self):
        self.assertEqual(bp.parse_keys("tag:quarantine,Build provenance,"
                                       "merge-tree,429 too many requests"),
                         ("TAGQUARANTINE",) + KEYS[1:])
        for bad in ["", "a,b,c", "a,b,c,", "a,b,c,d,e"]:
            with self.assertRaises(SystemExit):
                bp.parse_keys(bad)



class Fit(unittest.TestCase):
    def test_a_piece_too_wide_for_its_tile_is_refused(self):
        too_long = " ".join(["41"] * 8)          # 8 letters of hex
        with self.assertRaises(SystemExit):
            bp.tile_security(too_long)

    def test_the_documented_maximums_fit(self):
        hexa, b32, rot, plain = bp.pieces(
            "FLAG{%s_%s_%s_%s}" % ("W" * 7, "W" * 10, "W" * 9, "W" * 15),
            KEYS)
        bp.tile_security(hexa)
        bp.tile_secdevops(b32)
        bp.tile_agents(rot)
        bp.tile_automation(plain)

if __name__ == "__main__":
    unittest.main()
