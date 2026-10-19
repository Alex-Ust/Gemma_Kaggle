# Findings log

## Evaluation setup
- Local eval = official `swegemma` harness on Kaggle 4xL4 (`scripts/make_eval_kernel.py`), 129 public tasks, concurrency 4.
- Gold/empty oracle runs (CPU, no GPU quota): only **71/129 tasks are solvable** in the Kaggle sandbox
  (gold patch passes, empty patch fails). The rest fail for environment reasons: missing `inline_snapshot` /
  `dirty_equals` (fastapi), broken `httpbin` fixture and tests importing the installed `requests` instead of `src/`.
  3 tasks pass with an empty patch. Task sets in `data/task_sets.json`.
- Compare configs on the **sound 71** only (`pull_eval.py --set sound`).

## v02 baseline (public budget-fit prompt, 31B, 8 min / 28 calls / thinking 4096)
- LB 0.15 (9/58). Local 27/129, **24/71 sound**, 20/71 sound tasks with an empty patch.
- 56/61 failed patches edited the gold file: localization is not the main problem.
- Failure classes of the 61 failed patches (`research/failure_taxonomy/`): ENV 21, UNDERSPECIFIED 14,
  BROKEN_CODE 7, WRONG_LOCATION 6, INCOMPLETE 5, NARROW 2, WRONG_APPROACH 2, REGRESSION 2, OTHER 2.
- 21 edits were rejected with `BudgetExceeded`: the agent explored (search/read alternation) for all 28 calls.
- Time: 6% of steps (thinking > 3000 chars) take 35% of all time; single steps up to 290 s.
  One reproduction of an infinite-loop bug hung for the full 240 s command timeout.
- ~27% of successful `edit_file` calls used the `unescaped` fallback (model sends literal `\n`, `\"`);
  with real backslashes in code this corrupts the edit (e.g. rich_3063 `"\\"` -> `"\"`).
- `write_file` to `/tmp` fails (path traversal), but the prompt told the agent to put scratch files there.

## Skills (stdlib scripts run in the sandbox via run_skill_script; they count as tool calls)
- `locate`: BM25 over functions/classes. Offline on 128 tasks: gold file top-1 54%, top-5 77% (short query);
  prints the best symbol's source; it contains a gold hunk in 34% of tasks.
- `check`: compile + import changed modules, warn on stray/test files, run related existing tests.
  Replay of v02 failed patches (rich): caught all 4 broken/regression patches, no false alarm on correct ones.
  Picks the existing test file that the hidden tests modify in 42/52 sound tasks.
  Caveat: in 5/71 tasks the correct fix makes an old test fail by design -> prompt says keep the fix.

## Local stand (no GPU)
- `scripts/fake_llm_server.py` (scripted model) + `scripts/local_eval.py` (official harness, Docker sandbox).
- Docker mode installs the newest wheel of each package, so old fastapi snapshots break locally
  (starlette 1.x); use rich tasks for local checks.

## Community evidence (public notebooks / discussions)
- One public score is noisy: identical bundles drew 7-13 of 58. Judge by means or by local eval.
- Thinking on + include_thoughts is essential; thinking 2048 vs 4096 ~equal (50 vs 48 /129).
- Graph tools: no measured benefit.
