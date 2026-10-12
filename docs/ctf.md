# Running the profile CTF

This is the maintainer's runbook. Players only need the README.

## How it fits together

```
.ctf/flag, .ctf/keys  (local, gitignored, never committed)
        │
        ▼
scripts/build_profile.py ──► assets/tile-*.svg   (ciphertext drawn as pixels)
        │
        └── the same flag ──► Actions secret CTF_FLAG
                                     │
issue "ctf: proof" ──► .github/workflows/ctf.yml
                         verify  (read-only)    ctf/check.py
                         record  (can push)     ctf/check.py --record
                         reply   (can edit issues)
```

The checker only ever needs the flag. The keys are only used at build time.

## The rules the flag must follow

The generator enforces the first three and refuses to build otherwise.

1. **Shape:** `FLAG{A_B_C_D}`, four pieces of capital letters A–Z only.
2. **Each key is at least as long as its piece.** A shorter key repeats, and
   a repeating Vigenère key on a short word can be brute-forced. When the key
   is at least as long as the piece, it works like a one-time pad: without
   the key, every word of that length is an equally good guess.
3. **Each piece fits its tile.** Limits at today's 128 px tile width:

   | Piece | Tile | Outer encoding | Max letters | Key (clue answer) |
   |---|---|---|---|---|
   | 1 | Cybersecurity | hex | 7 | 10 letters |
   | 2 | SecDevOps | base32 | 10 | 15 letters |
   | 3 | Agent infrastructure | ROT13 | 9 | 9 letters |
   | 4 | APIs and automation | plain | 15 | 15 letters |

4. **Pick real words, but not guessable ones.** A solver who decrypts with
   the right key should recognise that it worked, so pieces are words. But
   never take them from this profile, the clues, or any list committed
   anywhere, and keep the four unrelated to each other. See "Accepted risks"
   for why.
5. **Never write the flag anywhere but `.ctf/flag` and the Actions secret.**
   Not in a commit message, an issue, a PR, a chat with a coding assistant, or
   a screenshot of a terminal.

## The clues

The clues live in the README and the answers are the keys. A key must be:

- **Learnable only by reading the work.** It shouldn't be on the profile page
  itself.
- **Stable.** If the fact changes (a project renames its quarantine tag, drops
  `git merge-tree`, renames "build provenance"), the clue becomes unsolvable.
  When a project changes, re-read its clue. If the answer changed, update the
  clue and rotate.
- **Normalised the same way the generator does it:** capitals, letters only.
  `tag:quarantine` becomes `TAGQUARANTINE`, and `429 Too Many Requests`
  becomes `TOOMANYREQUESTS`. The README tells players this rule, so say
  "letters only" in any new clue whose answer contains digits.

`.ctf/keys` holds the four answers, comma-separated, in tile order. Commas,
not colons, because an answer like `tag:quarantine` must stay one key.

## Rotating the flag

Rotate when the encoding scheme or a clue changes, or if the flag leaks.
**Old tiles stay readable in git history**, so a scheme change without a new
flag gives the old answer away.

1. Write the new flag to `.ctf/flag`, with no trailing newline, following the
   rules above. Update `.ctf/keys` if a clue changed.
2. Build:
   ```bash
   CTF_FLAG="$(cat .ctf/flag)" CTF_KEYS="$(cat .ctf/keys)" python scripts/build_profile.py
   ```
   Only the four `assets/tile-*.svg` files should change. The build fails if
   a piece is too long or would appear as text.
3. Run the tests:
   ```bash
   python -m unittest scripts.test_build_profile ctf.test_check oss.test_update
   ```
4. Commit the tiles, then merge.
5. **Right after the merge**, update the secret so the checker and the art
   agree:
   ```bash
   gh secret set CTF_FLAG --repo montjeffrey/montjeffrey < .ctf/flag
   ```
   PowerShell has no `<` redirection. Run this from the repository folder:
   ```powershell
   gh secret set CTF_FLAG --repo montjeffrey/montjeffrey --body (Get-Content -Raw .ctf/flag)
   ```
   A submission that lands between the merge and this step gets "Not quite".
   Re-run that issue's workflow once the secret is set.
6. Leave the hall of fame alone. Earlier solvers keep their place.

## When the bot redacts a leaked flag

The bot overwrites the title and body and locks the issue, but **the original
text stays in the issue's edit history** until you delete it. Open the
issue, click "edited", choose the original revision, and delete it from
history. GitHub has no API for this. Then decide whether the leak was public
long enough to rotate.

## When a solver gets the pending reply

`pending.md` means the proof was verified but the hall-of-fame commit didn't
land after five tries. That usually means branch protection or a GitHub
outage. Look at the failed `record` job. Fix the cause, add the solver by
re-running the workflow for that issue, then close it.

## Repository settings this depends on

| Setting | Needed value |
|---|---|
| `CTF_FLAG` Actions secret | Same as `.ctf/flag` |
| Label `ctf` | Exists. The issue form applies it, and the workflow only runs on it. |
| Rules on `main` | Must let `github-actions[bot]` push, or both the hall of fame and the open-source section stop updating. |
| Actions → Workflow permissions | Read-only default is fine. The workflows request what they need per job. |
| Moderation → Interaction limits | Off normally. Turn it on temporarily if someone floods CTF issues. |

## Accepted risks

- **Proofs can be shared.** Anyone who knows the flag can make a proof for
  any login. That's true of every static-flag CTF.
- **Public proofs enable offline guessing.** Each correct proof is
  `sha256(flag:login)` in a public issue. Someone who has solved three clues
  can try a dictionary for the fourth piece against a posted proof. Guessing
  all four blind is a dictionary to the fourth power, which is why rule 4
  keeps pieces unrelated and off any committed list.
- **Comments and later edits aren't checked for leaks.** Only newly opened
  issues are. Watching more events would widen what strangers can trigger to
  save a spoiler.
- **No rate limit.** A flood costs runs and noise, but runs are per issue, so
  it can no longer drop a real solver.
