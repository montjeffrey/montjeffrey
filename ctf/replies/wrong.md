**Not quite.** That hash doesn't match.

Check that each piece is decoded, that the pieces are in order, and that you hashed exactly `FLAG{...}:your-login` with your GitHub login in lowercase and no trailing newline (`printf '%s'`, not `echo`).
