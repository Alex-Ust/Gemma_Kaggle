# Reference bundles (frozen 2026-10-28)

Both zips are in `submissions/frozen/`, byte-identical to the bundle folders and to the bundles embedded in the pod kernels that produced the local numbers below. Git tags: `bundle-v23-lb024`, `bundle-v25-callsaver`.

| Bundle | What it is | Local sound105 (101 tasks, pod, concurrency 3) | Public LB | sha256 of zip |
|---|---|---|---|---|
| v23_public_lb024 | Byte copy of the public notebook honghanhhh/gemma-4-baseline-lb-0-24 (8 min / 28 calls / thinking 4096 / temperature 0.2). Not ours, public. | 33/101 (fastapi 21/59, rich 12/42) | 0.24 for the notebook author (one draw) | 205a677fdcbd122f50ac3138b1cda0403aeb625453c93edf4c53b7b691926186 |
| v25_callsaver | v23 + /tmp scratch-file fix (= v24) + call-saving prompt: read_file only with line ranges after grep -n, search only the package dir, fallback to a Python heredoc when edit_file arguments get garbled. Config and sampling unchanged. | 36/101 (fastapi 24/59, rich 12/42) | 0.12 (57752068, one draw) | ecd7d41222b5e0e0f8501dd4a37f191dea40a3cf27fbd85abfa47be6409feddb |

## Observation (2026-10-28)
- v25 beats v23 on the same 101 tasks by 3 (36 vs 33). Tasks only v25 solved: 9, only v23 solved: 6. Alone that is ~0.8 sigma (about a 1-in-5 chance of being luck), but every efficiency metric moved the same way: 28-call cap 54 -> 46, 8-min timeouts 13 -> 8, wall time 160 -> 145 min.
- The public LB uses 58 tasks; one identical bundle draws 7-13/58 (0.12-0.22), so the notebook's 0.24 is most likely a lucky draw of a config whose typical score is ~0.17-0.22.
- Expected effect of v25 on the LB: about +1-2 tasks out of 58 (+0.02-0.03) over the same config on average, not a guaranteed score above 0.24 in a single submission.
- Weak spot of v25: 26 empty patches (v23: 21). All never reached an edit: ~11 small ranged reads per task, then the cap. Next fix target.
- 30 of the 101 tasks need inline_snapshot/dirty_equals that the official wheelhouse lacks; they are unsolvable on the scorer and count the same for both bundles.
- 2026-10-29: v24 (= v23 + one prompt line about /tmp scratch files) scored 0.17 on the public LB (57712978), against 0.24 for the byte-identical notebook config. One line of prompt cannot plausibly cost 4 tasks out of 58; this is the LB draw noise described above (0.17 = ~10/58). It confirms that the public 0.24 was a lucky draw and that the public LB cannot rank configs this close.
- 2026-10-30: v25 scored 0.12 (~7/58) vs v24 0.17 (~10/58). All our LB draws: near-public config v02 0.15, v24 0.17 (mean 0.16); bundles with more prompt changes v07 0.10, v12 0.12 and 0.10, v25 0.12 (mean 0.11). Each single gap is within noise, but the direction has now repeated every time while the local fastapi+rich benchmark said the changes help. Working conclusion: the local benchmark does not predict the hidden set (most likely other repos), and repo-tuned prompt rules may hurt there. Do not pick bundles by sound105 alone any more.
