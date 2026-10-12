#!/usr/bin/env python3
"""Animated pixel-art header and four area tiles for the profile README.

Each tile is its own SVG so the README can wrap it in a link. Each tile also
flashes one piece of the capture-the-flag answer for about a second and a half
per loop, and every piece uses a different encoding:

    1 cybersecurity   hex      in a packet-capture line
    2 secdevops       base32   as a build artifact name
    3 agent infra     ROT13    in a memory lookup
    4 automation      plain    in an API response body

The pieces are drawn as pixels, never as text, so they cannot be found by
searching the SVG source -- you have to watch. They are derived from the flag
at build time, so the art and the answer cannot drift apart, and the flag
itself is never committed: pass it in CTF_FLAG when building, and store the
same value as the repository's CTF_FLAG Actions secret.

    CTF_FLAG='FLAG{A_B_C_D}' python scripts/build_profile.py

Craft notes, because each of these is the thing that breaks naive builds:

* Pixel art on integer grids scaled up by the README, with
  shape-rendering="crispEdges" so pixels stay sharp.
* All lettering is a hand-built 3x5 bitmap font drawn as pixel rects.
* Pure declarative CSS. GitHub strips <script> from SVG and serves README
  images through its camo proxy.
* Every story beat in a tile shares that tile's cycle and encodes its timing
  as keyframe percentages. animation-delay is avoided: it applies only before
  the first iteration and desyncs the loop.
* Discrete changes (a log line appearing, a stage going green) use
  steps(1,end), which holds each keyframe's value until the next one.
"""

from __future__ import annotations

import base64
import codecs
import os
import pathlib
import re
import sys

P = {
    "bg": "#0e0a20", "bg2": "#141030", "bar": "#090616", "grid": "#17122e",
    "edge": "#2e2652", "edge2": "#463c74", "host": "#0a0718",
    "dark": "#07051a", "screen": "#061016",
    "cyan": "#58e0ff", "green": "#5ef2a0", "mag": "#ff5fa2",
    "orange": "#E77D22", "amber": "#ffb347", "red": "#ff5a6a",
    "white": "#f4f1ff", "title": "#f0ede4", "sub": "#b5a8db", "dim": "#7d71a3",
    "bot": "#c9c3dc", "bot2": "#8f88a8", "card": "#f0ede4",
}

FONT = {
    "A": [".#.", "#.#", "###", "#.#", "#.#"],
    "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"],
    "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"],
    "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"],
    "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"],
    "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#"],
    "N": ["#..#", "##.#", "#.##", "#..#", "#..#"],
    "O": [".#.", "#.#", "#.#", "#.#", ".#."],
    "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": [".#.", "#.#", "#.#", "##.", ".##"],
    "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": [".##", "#..", ".#.", "..#", "##."],
    "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"],
    "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#...#", "#...#", "#.#.#", "##.##", "#...#"],
    "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."],
    "Z": ["###", "..#", ".#.", "#..", "###"],
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["##.", "..#", ".#.", "#..", "###"],
    "3": ["##.", "..#", ".#.", "..#", "##."],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "##.", "..#", "##."],
    "6": [".##", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "##."],
    ".": [".", ".", ".", ".", "#"],
    ",": [".", ".", ".", "#", "#"],
    ":": [".", "#", ".", "#", "."],
    "-": ["...", "...", "###", "...", "..."],
    "_": ["...", "...", "...", "...", "###"],
    "=": ["...", "###", "...", "###", "..."],
    "+": ["...", ".#.", "###", ".#.", "..."],
    "/": ["..#", "..#", ".#.", "#..", "#.."],
    "#": ["#.#", "###", "#.#", "###", "#.#"],
    "%": ["#.#", "..#", ".#.", "#..", "#.#"],
    ">": ["#..", ".#.", "..#", ".#.", "#.."],
    "{": [".##", ".#.", "##.", ".#.", ".##"],
    "}": ["##.", ".#.", ".##", ".#.", "##."],
    " ": ["..", "..", "..", "..", ".."],
}


def pc(v: float) -> str:
    return ("%.2f" % v).rstrip("0").rstrip(".") + "%"


def text_width(s: str, scale: int = 1) -> int:
    return sum((len(FONT.get(ch, FONT[" "])[0]) + 1) * scale
               for ch in s) - scale


class Svg:
    """A tiny builder for one animated pixel-art SVG."""

    def __init__(self, w: int, h: int, cycle: float):
        self.w, self.h, self.cycle = w, h, cycle
        self.out: list[str] = []
        self.css: list[str] = []
        self.n = 0

    # drawing ---------------------------------------------------------
    def rect(self, x, y, w, h, c, extra=""):
        if w > 0 and h > 0:
            self.out.append('<rect x="%s" y="%s" width="%s" height="%s" '
                            'fill="%s"%s/>' % (x, y, w, h, c, extra))

    def outline(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def dither(self, x, y, w, h, c, step=2, off=0):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if (xx + yy + off) % step == 0:
                    self.rect(xx, yy, 1, 1, c)

    def line(self, x1, y1, x2, y2, c, every=1):
        """Bresenham, keeping every Nth pixel for a dotted look."""
        dx, dy = abs(x2 - x1), -abs(y2 - y1)
        sx, sy = (1 if x1 < x2 else -1), (1 if y1 < y2 else -1)
        err, i = dx + dy, 0
        while True:
            if i % every == 0:
                self.rect(x1, y1, 1, 1, c)
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x1 += sx
            if e2 <= dx:
                err += dx
                y1 += sy
            i += 1

    def text(self, x, y, s, color, scale=1):
        cx = x
        for ch in s:
            g = FONT.get(ch, FONT[" "])
            w = len(g[0])
            for ry, row in enumerate(g):
                rx = 0
                while rx < w:
                    if row[rx] == "#":
                        end = rx
                        while end < w and row[end] == "#":
                            end += 1
                        self.rect(cx + rx * scale, y + ry * scale,
                                  (end - rx) * scale, scale, color)
                        rx = end
                    else:
                        rx += 1
            cx += (w + 1) * scale

    # animation -------------------------------------------------------
    def anim(self, seq, prefix="k"):
        self.n += 1
        name = "%s%d" % (prefix, self.n)
        self.css.append("@keyframes %s{%s}" % (
            name, "".join("%s{%s}" % (pc(t), d) for t, d in seq)))
        return name

    def group(self, seq, dur=None, easing="steps(1,end)", base=""):
        name = self.anim(seq)
        self.out.append('<g style="%sanimation:%s %ss %s infinite">'
                        % (base, name, dur or self.cycle, easing))

    def window(self, start, end):
        """Open a group visible only from start to end percent."""
        if start <= 0:
            seq = [(0, "opacity:1"), (end, "opacity:0"), (100, "opacity:0")]
        elif end >= 100:
            seq = [(0, "opacity:0"), (start, "opacity:1"), (100, "opacity:1")]
        else:
            seq = [(0, "opacity:0"), (start, "opacity:1"), (end, "opacity:0"),
                   (100, "opacity:0")]
        self.group(seq)

    def move(self, path, dur=None, easing="linear"):
        """Open a group travelling through [(t, x, y, opacity), ...]."""
        seq = [(t, "transform:translate(%spx,%spx);opacity:%s" % (x, y, o))
               for t, x, y, o in path]
        self.group(seq, dur, easing)

    def close(self):
        self.out.append("</g>")

    def render(self, title, desc, scale=4):
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
                'width="%d" height="%d" shape-rendering="crispEdges" '
                'role="img" aria-labelledby="t d"><title id="t">%s</title>'
                '<desc id="d">%s</desc><style>%s</style>%s</svg>'
                % (self.w, self.h, self.w * scale, self.h * scale, title, desc,
                   "".join(self.css), "\n".join(self.out)))


# ------------------------------------------------------------------ tiles
TW, TH, TC = 128, 72, 12.0
END = 92          # every tile's story clears here and the loop restarts


def tile(num, title, tag, accent):
    s = Svg(TW, TH, TC)
    s.rect(0, 0, TW, TH, P["bg"])
    for gx in range(0, TW, 8):
        s.rect(gx, 10, 1, TH - 10, P["grid"])
    s.rect(0, 0, TW, 10, P["bar"])
    s.text(3, 3, "%02d %s" % (num, title), accent)
    s.text(TW - 3 - text_width(tag), 3, tag, P["dim"])
    return s


def finish(s, accent):
    for yy in range(0, s.h, 2):
        s.rect(0, yy, s.w, 1, "#000000", ' opacity=".08"')
    s.outline(0, 0, s.w, s.h, accent)


def log(s, y, entries):
    for start, end, line, colour in entries:
        s.window(start, end)
        s.text(4, y, line, colour)
        s.close()


def bot(s, x, y, visor):
    s.rect(x + 2, y, 1, 1, visor)
    s.rect(x, y + 1, 6, 3, P["bot"])
    s.rect(x + 1, y + 2, 4, 1, visor)
    s.rect(x, y + 4, 6, 3, P["bot2"])
    s.rect(x, y + 7, 2, 1, P["dark"])
    s.rect(x + 4, y + 7, 2, 1, P["dark"])


def tile_security(piece_hex):
    s = tile(1, "CYBERSECURITY", "SECURITY+", P["cyan"])
    hosts = [(8, 15), (32, 13), (56, 17), (80, 13), (104, 16),
             (20, 29), (68, 30), (94, 28)]
    links = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 4),
             (2, 6), (1, 5), (3, 7)]
    bad, cut = 6, 45

    def mid(i):
        return hosts[i][0] + 3, hosts[i][1] + 2

    for a, b in links:
        (x1, y1), (x2, y2) = mid(a), mid(b)
        if bad in (a, b):
            s.window(0, cut)
            s.line(x1, y1, x2, y2, P["edge2"], 2)
            s.close()
            s.window(cut, END)
            s.line(x1, y1, x2, y2, P["red"], 5)
            s.close()
        else:
            s.line(x1, y1, x2, y2, P["edge2"], 2)

    # the scan sweeps left to right, classifying hosts as it passes
    s.move([(0, 0, 0, 0), (1, 0, 0, .9), (40, 120, 0, .9), (41, 120, 0, 0),
            (100, 120, 0, 0)])
    s.rect(2, 11, 2, 34, P["cyan"], ' opacity=".35"')
    s.rect(4, 11, 1, 34, P["cyan"], ' opacity=".15"')
    s.close()

    for i, (hx, hy) in enumerate(hosts):
        s.rect(hx, hy, 7, 5, P["host"])
        s.outline(hx, hy, 7, 5, P["edge2"])
        seen = 1 + 39 * (hx + 3) / 120
        if i == bad:
            s.window(seen, cut)
            s.rect(hx + 1, hy + 1, 5, 3, P["amber"])
            s.close()
            s.window(cut, END)
            s.outline(hx - 2, hy - 2, 11, 9, P["red"])
            s.rect(hx + 1, hy + 1, 5, 3, P["red"])
            s.text(hx - 6, hy + 8, "ISOLATED", P["red"])
            s.close()
        else:
            s.window(seen, END)
            s.rect(hx + 1, hy + 1, 5, 3, P["green"])
            s.close()

    # The lines mirror real `sentry scan` / `sentry isolate` output from
    # github.com/montjeffrey/tailnet-sentry: an inventory of the tailnet
    # through the Tailscale API, never a subnet scan.
    log(s, 46, [(3, END, "> SENTRY SCAN TAILNET", P["cyan"])])
    log(s, 52, [(22, END, "> 7 HEALTHY. 1 ANOMALY", P["amber"])])
    log(s, 58, [(46, END, "> HOST-7 QUARANTINED", P["green"])])
    log(s, 64, [(56, 70, "> PCAP %s  1/4" % piece_hex, P["white"]),
                (70, END, "> CASE CLOSED", P["dim"])])
    finish(s, P["cyan"])
    return s.render(
        "Cybersecurity",
        "A tailnet-sentry scan inventories eight devices on the tailnet and "
        "marks seven healthy against a known-good baseline; one is flagged as "
        "an anomaly and quarantined, its links cut. A log narrates the scan, "
        "and for a moment a packet-capture line shows one encoded piece of "
        "the profile's capture-the-flag.")


def tile_secdevops(piece_b32):
    s = tile(2, "SECDEVOPS / CI-CD", "PIPELINE", P["green"])
    names = ["PUSH", "TEST", "SCAN", "SIGN", "SHIP"]
    runs = {i: [] for i in range(5)}
    for i in range(5):                               # run 211: clean
        a = 4 + 7 * i
        runs[i] += [(a, a + 4, P["amber"]), (a + 4, 46, P["green"])]
    runs[0] += [(50, 54, P["amber"]), (54, END, P["green"])]   # run 212
    runs[1] += [(54, 58, P["amber"]), (58, 63, P["red"]),
                (63, 67, P["amber"]), (67, END, P["green"])]
    for i, a in ((2, 67), (3, 71), (4, 75)):
        runs[i] += [(a, a + 4, P["amber"]), (a + 4, END, P["green"])]

    for i, name in enumerate(names):
        x, y = 3 + i * 25, 14
        s.rect(x, y, 22, 11, P["host"])
        s.outline(x, y, 22, 11, P["edge2"])
        for start, end, colour in runs[i]:
            s.window(start, end)
            s.rect(x + 1, y + 1, 20, 9, colour, ' opacity=".22"')
            s.outline(x, y, 22, 11, colour)
            s.close()
        s.text(x + (22 - text_width(name)) // 2, y + 3, name, P["white"])
        if i < 4:
            s.rect(x + 22, y + 5, 3, 1, P["edge2"])

    log(s, 30, [(2, 46, "RUN #211  MAIN  7F3A9C1", P["dim"]),
                (50, END, "RUN #212  MAIN  A1F3C9E", P["dim"])])
    log(s, 36, [(12, 46, "TEST  GO TEST ./... OK", P["green"]),
                (58, 67, "TEST  1 FAILED. RETRY", P["red"]),
                (67, END, "TEST  GO TEST ./... OK", P["green"])])
    log(s, 42, [(19, 46, "SCAN  GITLEAKS 0  VULNS 0", P["green"]),
                (71, END, "SCAN  GITLEAKS 0  VULNS 0", P["green"])])
    log(s, 48, [(26, 46, "SIGN  BUILD PROVENANCE", P["green"]),
                (75, END, "SIGN  BUILD PROVENANCE", P["green"])])
    log(s, 54, [(33, 46, "SHIP  RELEASE + SHA256SUMS", P["green"]),
                (79, END, "SHIP  RELEASE + SHA256SUMS", P["green"])])
    log(s, 62, [(36, 50, "> BLOB %s 2/4" % piece_b32, P["white"])])
    finish(s, P["green"])
    return s.render(
        "SecDevOps and CI/CD",
        "A five-stage pipeline: push, test, scan, sign, ship. The first run "
        "passes cleanly; the second fails a test, retries and then ships. A "
        "run log shows zero leaked secrets, a signed provenance attestation "
        "and a full rollout, and for a moment a build artifact name carries "
        "one encoded piece of the profile's capture-the-flag.")


def tile_agents(piece_rot):
    s = tile(3, "AGENT INFRA", "AGENT-HARNESS", P["mag"])
    nodes = [(30, 15), (48, 12), (66, 17), (84, 13), (40, 26), (58, 28),
             (76, 25), (94, 29), (32, 37), (52, 38), (72, 37), (90, 38)]
    edges = [(0, 1), (1, 2), (2, 3), (0, 4), (4, 5), (5, 6), (6, 7), (1, 5),
             (2, 6), (4, 8), (8, 9), (9, 10), (10, 11), (5, 9), (6, 10),
             (3, 7), (7, 11)]
    lit = {4: 16, 5: 20, 6: 24, 9: 58, 10: 62}       # node -> lit at
    lit_edges = {(4, 5): 20, (5, 6): 24, (9, 10): 62}

    def c(i):
        return nodes[i][0] + 2, nodes[i][1] + 2

    for a, b in edges:
        s.line(*c(a), *c(b), P["edge"], 2)
    for (a, b), at in lit_edges.items():
        s.window(at, END)
        s.line(*c(a), *c(b), P["mag"], 1)
        s.close()
    for i, (nx, ny) in enumerate(nodes):
        s.rect(nx, ny, 4, 4, P["edge2"])
        if i in lit:
            s.window(lit[i], END)
            s.rect(nx, ny, 4, 4, P["mag"])
            s.rect(nx + 1, ny + 1, 2, 2, P["white"])
            s.close()

    visors = [P["cyan"], P["mag"], P["green"]]
    for k, by in enumerate((13, 24, 35)):
        bot(s, 6, by, visors[k])

    # queries out to the graph, budgeted context packets back
    s.move([(0, 12, 27, 0), (8, 12, 27, 0), (8.3, 12, 27, 1), (15, 40, 27, 1),
            (15.3, 40, 27, 0), (100, 40, 27, 0)])
    s.rect(0, 0, 2, 2, P["white"])
    s.close()
    s.move([(0, 76, 25, 0), (28, 76, 25, 0), (28.3, 76, 25, 1),
            (38, 13, 22, 1), (38.3, 13, 22, 0), (100, 13, 22, 0)])
    s.rect(0, 0, 4, 5, P["card"])
    s.rect(1, 1, 2, 1, P["mag"])
    s.close()
    s.move([(0, 12, 38, 0), (50, 12, 38, 0), (50.3, 12, 38, 1),
            (57, 52, 38, 1), (57.3, 52, 38, 0), (100, 52, 38, 0)])
    s.rect(0, 0, 2, 2, P["white"])
    s.close()
    s.move([(0, 72, 37, 0), (66, 72, 37, 0), (66.3, 72, 37, 1),
            (74, 13, 33, 1), (74.3, 13, 33, 0), (100, 13, 33, 0)])
    s.rect(0, 0, 4, 5, P["card"])
    s.rect(1, 1, 2, 1, P["green"])
    s.close()

    # context budget: each packet takes a slice, never the whole window
    s.text(108, 13, "CTX", P["dim"])
    s.outline(110, 19, 10, 24, P["edge2"])
    s.window(38, 74)
    s.rect(111, 34, 8, 8, P["mag"], ' opacity=".7"')
    s.close()
    s.window(74, END)
    s.rect(111, 30, 8, 12, P["mag"], ' opacity=".7"')
    s.close()

    log(s, 48, [(6, 48, "> QUERY CALLERS OF LOGIN", P["mag"]),
                (50, END, "> QUERY TESTS FOR BILLING", P["mag"])])
    log(s, 54, [(26, 48, "> 3 OF 412 FILES IN SCOPE", P["dim"]),
                (62, END, "> 2 OF 412 FILES IN SCOPE", P["dim"])])
    log(s, 60, [(38, 52, "> MEMORY %s  3/4" % piece_rot, P["white"]),
                (74, END, "> PACKET SENT. NEXT TASK", P["green"])])
    finish(s, P["mag"])
    return s.render(
        "Agent infrastructure",
        "Three agents query a code graph instead of reading whole files: each "
        "query lights only the few nodes that matter, and a small context "
        "packet travels back to the agent while a context-budget gauge stays "
        "low. For a moment a memory lookup shows one encoded piece of the "
        "profile's capture-the-flag.")


def tile_automation(piece_plain):
    s = tile(4, "REST + AUTOMATION", "APIS", P["orange"])
    s.rect(4, 14, 26, 16, P["host"])                 # the cron client
    s.outline(4, 14, 26, 16, P["edge2"])
    s.outline(7, 18, 7, 7, P["dim"])
    s.rect(10, 21, 1, 1, P["white"])
    for k, (dx, dy, w, h) in enumerate(((10, 19, 1, 2), (11, 21, 2, 1),
                                         (10, 22, 1, 2), (8, 21, 2, 1))):
        s.group([(0, "opacity:0"), (25 * k, "opacity:1"),
                 (25 * k + 25, "opacity:0"), (100, "opacity:0")]
                if k else [(0, "opacity:1"), (25, "opacity:0"),
                           (100, "opacity:0")], 2.0)
        s.rect(dx, dy, w, h, P["orange"])
        s.close()
    s.text(16, 20, "CRON", P["orange"])
    s.rect(98, 14, 26, 16, P["host"])                # the API
    s.outline(98, 14, 26, 16, P["edge2"])
    s.text(104, 18, "API", P["white"])
    for k in range(3):
        s.group([(0, "opacity:1"), (50, "opacity:.25"), (100, "opacity:.25")],
                .8 + k * .3)
        s.rect(104 + k * 4, 25, 2, 1, P["green"])
        s.close()
    for wx in range(31, 97, 2):
        s.rect(wx, 22, 1, 1, P["edge2"])

    def req(start, colour):        # left to right
        s.move([(0, 30, 21, 0), (start, 30, 21, 0), (start + .3, 30, 21, 1),
                (start + 8, 94, 21, 1), (start + 8.3, 94, 21, 0),
                (100, 94, 21, 0)])
        s.rect(0, 0, 3, 3, colour)
        s.close()

    def resp(start, colour):       # right to left
        s.move([(0, 94, 21, 0), (start, 94, 21, 0), (start + .3, 94, 21, 1),
                (start + 6, 30, 21, 1), (start + 6.3, 30, 21, 0),
                (100, 30, 21, 0)])
        s.rect(0, 0, 3, 3, colour)
        s.close()

    def label(start, end, line, colour, y=15):
        s.window(start, end)
        s.text(64 - text_width(line) // 2, y, line, colour)
        s.close()

    req(6, P["white"]); label(6, 16, "GET /JOBS", P["white"])
    resp(16, P["green"]); label(16, 28, "200 OK", P["green"])
    req(30, P["white"]); label(30, 40, "POST /JOBS", P["white"])
    resp(40, P["red"]); label(40, 46, "429 THROTTLED", P["red"])
    label(46, 49, "WAIT 1S", P["amber"], 25)
    label(49, 52, "WAIT 2S", P["amber"], 25)
    label(52, 56, "WAIT 4S", P["amber"], 25)
    req(56, P["white"]); label(56, 64, "POST /JOBS RETRY", P["white"])
    resp(64, P["green"]); label(64, 76, "201 CREATED", P["green"])
    resp(76, P["mag"]); label(76, 86, "HOOK JOB.DONE", P["mag"])

    log(s, 36, [(22, END, "GET  /JOBS   200   41MS", P["green"])])
    log(s, 42, [(46, END, "POST /JOBS   429", P["red"])])
    log(s, 48, [(70, END, "POST /JOBS   201   BACKOFF", P["green"])])
    log(s, 54, [(82, END, "HOOK JOB.DONE   ACK 200", P["mag"])])
    log(s, 62, [(80, END, "BODY {PART:4,V:%s}" % piece_plain, P["white"])])
    finish(s, P["orange"])
    return s.render(
        "REST APIs and automation",
        "A cron job calls an API: a GET returns 200, a POST is throttled with 429 and "
        "backs off for one, two and four seconds before retrying and getting "
        "201 Created, and then a webhook reports the job done. Near the end "
        "of each loop a response body carries one piece of the profile's "
        "capture-the-flag.")


def header():
    s = Svg(256, 40, 6.0)
    s.rect(0, 0, 256, 40, P["bg"])
    s.dither(0, 0, 256, 16, P["bg2"], step=4)
    name = "JEFFREY MONTOYA"
    s.text(7, 6, name, P["orange"], 2)
    s.text(6, 5, name, P["title"], 2)
    s.text(6, 19, "COMPTIA SECURITY+ / SECDEVOPS / AGENT INFRA / REST APIS",
           P["orange"])
    s.text(6, 27, "PLAN ONCE. AUTOMATE THE REST.", P["sub"])
    s.group([(0, "opacity:1"), (80, "opacity:1"), (85, "opacity:.2"),
             (90, "opacity:1"), (100, "opacity:1")], 3.0)
    hint1, hint2 = "A FLAG IS HIDDEN", "IN THIS PROFILE"
    s.text(236 - text_width(hint1), 6, hint1, P["amber"])
    s.text(236 - text_width(hint2), 13, hint2, P["amber"])
    s.close()
    s.rect(240, 5, 1, 13, P["dim"])                 # flag pole
    s.group([(0, "opacity:1"), (50, "opacity:0"), (100, "opacity:0")], .7)
    s.rect(241, 5, 7, 2, P["amber"])
    s.rect(241, 7, 6, 2, P["orange"])
    s.close()
    s.group([(0, "opacity:0"), (50, "opacity:1"), (100, "opacity:1")], .7)
    s.rect(241, 6, 6, 2, P["amber"])
    s.rect(241, 8, 7, 2, P["orange"])
    s.close()
    s.rect(0, 38, 256, 2, P["edge"])
    s.move([(0, -40, 0, 1), (100, 256, 0, 1)], 4.0)
    s.rect(0, 38, 40, 2, P["orange"])
    s.close()
    for yy in range(0, 40, 2):
        s.rect(0, yy, 256, 1, "#000000", ' opacity=".07"')
    return s.render(
        "Jeffrey Montoya",
        "Jeffrey Montoya. CompTIA Security+, SecDevOps, agent infrastructure, "
        "REST APIs. Plan once, automate the rest. A flag is hidden in this "
        "profile.")


def pieces(flag: str):
    m = re.fullmatch(r"FLAG\{([A-Z]+)_([A-Z]+)_([A-Z]+)_([A-Z]+)\}", flag)
    if not m:
        raise SystemExit("CTF_FLAG must look like FLAG{A_B_C_D}, uppercase")
    a, b, c, d = m.groups()
    return (" ".join("%02X" % ch for ch in a.encode()),
            base64.b32encode(b.encode()).decode(),
            codecs.encode(c, "rot13"),
            d)


def main():
    flag = os.environ.get("CTF_FLAG", "")
    hexa, b32, rot, plain = pieces(flag)
    assets = pathlib.Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    built = {
        "header.svg": header(),
        "tile-security.svg": tile_security(hexa),
        "tile-secdevops.svg": tile_secdevops(b32),
        "tile-agents.svg": tile_agents(rot),
        "tile-automation.svg": tile_automation(plain),
    }
    for name, svg in built.items():
        for secret in (flag, hexa, b32, rot, plain):
            if secret in svg:
                raise SystemExit("%s would contain a flag piece as text" % name)
        (assets / name).write_text(svg, encoding="utf-8")
        print("wrote %-20s %4d KB" % (name, len(svg) // 1024))


if __name__ == "__main__":
    sys.exit(main())
