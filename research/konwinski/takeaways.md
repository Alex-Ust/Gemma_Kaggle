# Takeaways for the Gemma 4 agent (2026-11-05)

## What made the Konwinski top-10 score, in one line each
1. Abstain. Score = (correct − wrong)/total with a free skip, so every top solution is a cascade of gates that ships a patch only when hard evidence says it works (1st: ~91% skipped; GraphNinjas: 4 correct, 0 wrong). Not available to us: our metric has no penalty for a wrong patch and no credit for skipping.
2. Execution-based verification, not self-assessment. 1st place generated `reproduce_bug.py` scripts with sentinel strings ("Issue reproduced" / "Issue resolved"), validated them on the unpatched repo, and kept only patches that flipped a validated test AND did not worsen the existing test files' pass/fail counts.
3. Test-first localisation. Winner starts from the relevant existing test files (model picks them from the repo skeleton), then localises source from there at temperature 0. 5th place: regex traceback parser to find the files.
4. Multi-sample + select. 2 localisations x 3 repairs = 6 candidates; huikang starter: 6 samples at T=0.6; GraphNinjas: pick the candidate with the smallest total edit distance to the others (a consensus proxy).
5. Compressed context. Agentless skeleton (files/classes/functions, 30-line bodies), grep windows of ±12 lines, hard char caps. Never whole files.
6. Model choice dominated everything else: 32B coder >> 14B (2nd place), the 8th place "breakthrough" was picking the weights with the best correct-to-wrong ratio. We cannot choose: Gemma 4 31B is fixed.
7. Runtime engineering: parallel threads for install / test generation / repair, per-stage timeouts, llama.cpp with three servers on 4x L4, 5–7 h total runs.

## What transfers to a single tool-calling agent, 28 calls / 7 min, no skip
Ordered by expected value per cost. Each must be tested paired on our 71 tasks; the public LB cannot see ±3 tasks.

A. Test-first locate (free, prompt only). "Find the test file for the feature first (`grep -rl <keyword> tests/`), read the closest test, then open the source it imports." Converts vague issues into exact symbols. Our traces: tasks that edited early resolve 52%, late 11%; most late tasks were lost in locating.

B. Sentinel reproduction check (2–3 calls, prompt only). After the edit: `python -c` that imports the changed symbol and asserts the issue's expected behaviour, printing RESOLVED. The winner's whole edge was replacing "I think this is right" by an executed check. Costs ~20–40 s per task; must be paired-tested for runtime.

C. Before/after count gate on ONE test file (2 calls). `timeout 60 python -m pytest tests/x.py -x -q --tb=no | tail -3` before and after; if the after-run is worse, revert that edit (`git checkout -- file`) and try the second-best idea. Inverts the winner's veto into a tie-breaker, which is what a no-skip metric needs.

D. Consensus-by-cheap-candidates (0 extra calls). Ask the model for 2–3 candidate locations in one message and grep them all in one `run_command`. Mimics multi-sample localisation without multi-sample budget.

E. Zero-call repo skeleton. Not possible from our bundle (the harness builds the task prompt), and the harness already injects a 3-level tree. Skip.

Not transferable: skipping, 6x patch sampling, separate reasoner model, 2-minute P2P runs per candidate, parallel servers.

## Order of experiments (one Kaggle run each, ~3.5–7 h quota)
1. v31 = v30 + A + D (locating only; runtime-neutral or faster).
2. v32 = v31 + B (sentinel check; measure runtime).
3. v33 = v32 + C (count gate with revert) only if v32 holds the 12 h projection.
Decision rule as before: paired delta ≥ −2 and mean duration ≤ the parent's; a change is "real" only at about +14/−5.
