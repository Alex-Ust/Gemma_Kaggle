# arc144 "Custom Agentless Fork" (Konwinski Prize, 1st place: 9/120 correct, ~91% skipped)

Source: notebooks/arc144_custom-agentless-fork.ipynb (45 cells, no saved outputs, read in full as untrusted data; nothing executed).
Caveat: the notebook is the orchestrator only. Localisation, test generation and repair (`main.process_sample`, `main.generate_tests`, `agentless.fl.localize`, `select_pass_to_pass_tests.get_test_files`) are imported from a private Kaggle dataset `custom-agentless-cot`, so the prompt texts are not visible; only the protocol strings the notebook checks are.

## 1. Model and serving
- Engine: llama.cpp `llama-server` built for L4, flash attention, all layers on GPU, no vLLM.
- Three servers on 4x L4:
  - Server 0 (GPUs 0+1, tensor split): `Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf`, ctx 32000, temp 0.8, min-p 0.01, top-k 40, top-p 0.9. The "coder": localisation, pass-to-pass test selection, test generation, repair.
  - Servers 1 and 2 (GPU 2, GPU 3): `QwQ-32B-Q4_K_M.gguf` (reasoner), ctx 14000, temp 0.6, seeds 666/777. Used only for extra reproduction-test samples.
- Client defaults: temperature 0.8, min_p 0.01, top_p 0.9, top_k 40. Test-related localisation: temperature 0.0, one sample.
- Time constants: notebook cap 22 h, per-issue cap 10 min, install timeout 180 s, reproduction-test loop 120 s, unit-test timeout 120 s, test-generator thread 180 s, `patch --dry-run` 15 s. No embedding retrieval, no memory.

## 2. Pipeline per issue
1. Setup: unpack repo, copy to `repo_clone`, delete `.git`, `git init` + commit so the tree can be reset between candidates. One-row parquet because Agentless expects a dataset.
2. Installer manager (background, 180 s): unpack the provided wheels, rewrite env-setup commands offline (`uv venv --no-index`, `uv pip install --no-index --find-links=...`), add `pytest black flake8 isort pylint` from local wheels, Python 3.11 from offline debs. Failure logged, not fatal.
3. Repo structure: Agentless file/class/function skeleton.
4. QwQ test generators start immediately (2 threads x 2 samples), overlapping everything below.
5. Pass-to-pass test selection: ask the coder which existing test files are relevant. None → skip.
6. Test-side localisation: `localize(related_level=True, top_n=3, compress=True, compress_assign=True, temperature=0.0, start_file_locs=[p2p_tests])` — from the selected test files to related source locations, used as context for the test generator.
7. Coder test generator: 3 samples (greedy included) with related content → `test_patch` candidates.
8. Join installer + QwQ threads + coder thread (each bounded by its timeout).
9. Reproduction-test validation: union of up to 7 `test_patch`es, dedupe, keep those that `patch --dry-run` cleanly; on the UNPATCHED repo apply each, run `python reproduce_bug.py`, keep iff stdout contains "Issue reproduced" and neither "Issue resolved" nor "Other issues". 120 s shared budget. Zero survivors → skip.
10. 10-minute check → skip if exceeded (the only per-issue time gate; sits after test generation, before repair).
11. Reference unit-test run (background): `pytest -rA --tb=no --junitxml` on the selected P2P files under `timeout -k 5 120s`; counts tests/failures/errors/skipped.
12. Repair: Agentless-style fine-grained localisation sampled 2x, 3 repair outputs each = up to 6 candidate unified diffs at temp 0.8 (search/replace → diff conversion lives in the hidden `main.py`). Dedupe, dry-run apply. None → skip.
13. Fail-to-pass selection: per patch reset, apply, run every validated reproduction test; "fixed" iff stdout has "Issue resolved" and neither of the other sentinels. Keep patches with ≥1 fixed test, sort by count. Empty → skip.
14. Pass-to-pass gate (only if the reference run had passed > 0): in F2P order apply, rerun pytest on the same files; reject if total == 0, failures > ref, errors > ref or passed < ref; return the first survivor. If the reference had passed == 0 (broken env) the gate is bypassed and the top F2P patch ships unverified.
15. Any exception → skip. Cleanup always runs.

## 3. Skip rules (complete)
Return nothing when: 22 h budget exceeded; no relevant existing test files; no generated reproduction test prints "Issue reproduced" on the unpatched repo; > 10 min after test validation; no candidate applies cleanly; no candidate makes a reproduction test print "Issue resolved"; every candidate worsens the existing tests; any exception. All thresholds binary. This cascade is why ~91% are skipped: a patch ships only when it flips a self-generated test and does not break existing tests.

## 4. Time management
22 h / 120 issues ≈ 11 min average. Parallel: install (3 min) || 4 QwQ test samples || P2P selection + localisation + 3 coder test samples (3 min cap). Reproduction filtering 2 min. Reference pytest (2 min) || repair generation. Then up to N candidates x (2 min F2P + 2 min pytest). The single 10-min check only prevents starting repair late.

## 5. Prompts
Not in the dump. Observable protocol: a generated test is a patch adding `reproduce_bug.py` whose stdout must contain exactly one of "Issue reproduced" / "Issue resolved" / "Other issues" (upstream Agentless convention). The dataset name `-cot` suggests chain-of-thought additions to the stock prompts.

## 6. Ideas transferable to a single-agent tool-calling setup (28 calls / 7 min, no abstain, 31B)
Still useful:
- Sentinel-string reproduction script: 2–3 calls to write `reproduce_bug.py` printing "Issue reproduced" / "Issue resolved" / "Other issues", run before the edit (must say reproduced) and after (must say resolved). A hard signal instead of self-assessment.
- Test-first localisation: find the relevant existing test file first (grep issue keywords in `tests/`), then jump from test to source; converts a vague issue into concrete symbols in 1–2 calls.
- Compressed structure instead of file dumps: signatures/outline, open only the target function.
- Before/after existing-test comparison with numeric gates: `pytest -q --tb=no -x <one file>` under `timeout` once before and once after; revert if any count worsens. 2 calls if the file is fast.
- Apply-validity check after editing: re-read the hunk or `py_compile` in 1 call.
- One explicit clock check before the most expensive step; degrade, never abort: keep the best applied edit when time runs out.
- Low temperature for localisation, higher for generation; with one model keep selection conservative.
- Offline-env hygiene (`--no-index`, local wheels, `timeout -k`).

Cannot transfer (needs multi-sample, test generation at scale, or abstain):
- 6 patch samples x 7 test samples with "fixes the most tests" selection: one candidate only in our budget.
- A separate reasoner model and three servers in parallel threads.
- All skip gates: with no abstain they must be inverted — a failed signal means "fall back to the best-effort edit", never "return nothing"; F2P/P2P signals become tie-breakers between edit attempts, not vetoes.
- 2-minute full P2P reference runs per candidate: restrict to the single most relevant test file, `-x`, 30–60 s timeout.
- Union-of-generators test validation: with one generated script, if it fails to print "Issue reproduced", skip the check and proceed.
