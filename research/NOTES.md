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

## Update 2026-10-19 evening
- Kaggle bills 4xL4 GPU time at 2x against the 30 h weekly quota.
- v02 sound-set endings: submitted 31 (18 resolved), call cap 17 (2), time cap 19 (0). Time-capped tasks:
  31% of their time is long-thinking steps; hung commands in 2 tasks (240 s each).
- OOD-45 (rodrigospalma/ood45-bugfix-split, 45 tasks / 17 unseen repos): `locate` top-1 82-87%, top-5 96%.
  `check` picks the hidden-test file in 18/21. Fake-model gold replay of v05 in the scorer sandbox:
  public sound 69/71 (2 stand issues), OOD 44/44.
- `check` now re-runs failing tests on the untouched HEAD in a temporary `git worktree` and labels each as
  pre-existing or caused by the edit (gold patches: 14 changed-behaviour, 11 pre-existing on public sound).
- v05 = v02 + budget_warning edit rule, /tmp heredoc, single reproduction with `timeout 20`, sibling-group fix,
  edit escaping rules, brevity rule, thinking 2048, command timeout 90 s, `locate` (first call, shows code),
  `check` (before submit). GPU eval on sound 71 started 17:35.

## Update 2026-10-20: v05 results and what the model actually sees
- v05 on sound 71: 26/71 (v02 24/71; paired +6/-4), 23 empty patches, mean 358 s/task (v02 393 s).
- **Broken skill calls**: 100 of 200 run_skill_script calls (v03: 123) were corrupted the same way:
  `"file_path": "scripts/locate.py`,skill_name:"` - the model closes the string with a backtick (copied from the
  prompt's markdown), the parser swallows the rest, skill_name goes missing; the model then repeats the identical
  call (fastapi_14419: 47 times). Invalid skill calls do not count toward the tool budget but cost ~5-10 s each.
  read_file/edit_file are hit too, rarely (3/506, 7/137).
- Gemma 4's chat template renders tool parameters with `dictsort`, so the model writes arguments alphabetically
  (args, file_path, skill_name): the corruption point sits right before skill_name.
- **Empty patches = code drafted in thoughts but never applied**: 22/23 v05 empty-patch tasks (v03 25/26) had code
  blocks in thoughts before any edit (median ~7 times). budget_warning was followed in 3/44 cases.
  Code blocks in thoughts are ~21% of all completion tokens.
- **Time is decode**: model time is 98-99% of task wall time; ~4.5 s per 100 completion tokens (22 tok/s at
  concurrency 4). An 8-minute cap is about 10k output tokens.
- **Double-encoded tool results**: swegemma tools return a JSON string, ADK wraps it as {"result": str}, LiteLLM
  json.dumps it again, and the template inserts it raw. The model reads code as `environ.get(\\\"X\\\", \\\"\\\")`
  with `\\n` line breaks. Skill results (dicts) are encoded once. 25% of v05 edits needed the `unescaped` fallback;
  34/137 old_strings contained literal \n or \".
- Thinking is enabled via extra_body.chat_template_kwargs.enable_thinking and extra_body.thinking_token_budget,
  attached by adk_submission to a clone of the LiteLlm at compile time. Past thoughts are sent back as
  reasoning_content and rendered (all turns after the single user message).
- Multi-agent configs (Sequential/Loop/agent_tool) are allowed, but the tool budget is session-wide and the
  harness stops the session when it is exhausted, so a forced "explore then fix" split is not possible.
  No user callbacks are registered by swegemma.
- Hidden set: ~120 tasks run sequentially; over 12 h the whole submission errors. v02 (mean 394 s locally at
  concurrency 4) scored fine, so a candidate must not be slower than that.

## Next-action probes (scripts/make_probes.py, probe_runner.py, make_probe_kernel.py, probe_report.py)
- Replays a recorded session with the real ADK stack (compile_submission, real tool declarations, real history
  encoding; recorded model turns from a replay model, recorded tool results from a plugin) and samples one more
  turn from the real model under a candidate prompt. Points: first turn, first code-in-thought turn (>=5),
  turn 12 without an edit. Cost: vLLM startup + one turn per point, instead of whole sessions.
- Probe p1 (161 points from v05 traces; v05 vs v06 vs v06b=thinking 1024), 64 min on 4xL4:
  - Mid-session decisions do not follow the system prompt: at the plan/late points the edit rate was ~5% for
    all three variants; "begin every thought with Call N" was followed 0 times; code-in-thought unchanged.
    Behaviour mid-session is driven by the history, not by rules.
  - The "Call N of 28" rule broke tool calls: the model wrote "Call 1 of 28:" as visible text and then the
    call as plain text without the tool-call token (11/71 first turns had no parsed call).
  - Without backticks, corrupted first calls dropped 7/71 -> 1/71, but "args containing one key, query"
    led to query being put at top level (29/71 locate calls without a query).
  - thinking_budget 1024 vs 2048: no clear change in tokens per turn (thoughts are usually shorter).
- Probe p2first (v07, 142 samples): locate called with positional_args (typed ARRAY of STRING in the declaration,
  unlike args whose anyOf renders with an empty type) - 124/142 valid, 0 corrupted, 0 unparsed; 18 started with
  grep/read instead. v05 control: 45/71 valid, 7 corrupted.
- locate now prints the two best symbols of the top file and the best of the second file (4500 chars):
  printed source contains a gold hunk in 45% of public tasks (was 34%); OOD unchanged 54%.
  check appends a compact git diff of the change (1500 chars). Fake-gold v07 on sound: 69/71 (as before).
- Full v07 sound eval started (v07 = v06 minus counter rule, locate via positional_args, new locate/check).
- v08 two-agent smoke (16 tasks: 8 v05-empty + 8 v05-solved): 8/16 = same as v05 on these tasks
  (+fastapi_11194 +rich_3777, -fastapi_5077 -rich_3043). The analyst does not stop after ~8 calls (often 20+),
  so it just moves the exploration loop into the sub-agent; mean 407 s, 7/16 time-capped, projected ~13.6 h
  (over the 12 h limit). Not a candidate in this form.
- **v07 full sound eval: 28/71** (v05 26, v02 24), 20 empty, mean 339 s (v02 393 s), projected <= 11.3 h.
  Paired: vs v02 +6/-2, vs v05 +4/-2. locate calls clean; check calls still corrupted the old way
  (file_path "check.py`,skill_name:") 59 times in 3 tasks -> next version: call check with positional_args too.
  Submitted v07 to the LB on 2026-10-20.

## 2026-10-21: v07 on the LB = 0.10 (6/58), v02 = 0.15 (9/58)
- Re-submitted bundles vary by ~1.4-1.8 tasks per draw (community), so -3 is ~1.3 SD: not conclusive, but the
  local sound-71 set is only fastapi + rich, while the hidden set is ~120 tasks most likely from other repos.
  The local +4 (28 vs 24) does not transfer automatically.
- Found an OOD-only cost: `check` on OOD-45 (fake-gold replay, v05 check) took median 29 s, max 76 s
  (public: median 5 s). 20/44 tasks > 30 s; pytest timed out at 45 s in many (plotnine image tests, feast/kedro
  heavy imports, pyjanitor spark tests); one false "IMPORT FAILED ... timed out" (fixed in v07). v07 calls
  check ~1.5 times per task, so on unseen repos check eats 1-2 of the 8 minutes and often returns nothing useful.
- The harness writes conftest.py / pytest.ini (hermetic discovery hook) before the baseline commit; when they show
  up as changed, check used to warn "test/config files changed" -> now recognised as harness files and ignored.
- check v2 (v09): 45 s total budget; import checks run in parallel with pytest (temp-file output, own process
  group, killed on deadline); tests get <= 28 s; HEAD comparison only when the first run took <= 12 s; a timeout
  says "tests are slow here, do not run them again"; test targeting also uses the names of the changed functions
  (from the diff + names passed by the model): hidden-test file among the targets 41 -> 42/52 public,
  22 -> 23/26 OOD (limit 2 files = limit 3). Called with positional_args (names of changed functions) like locate,
  to avoid the file_path backtick corruption.
- OOD-44 split into two repo-stratified halves (data/task_sets.json: ood, ood_a, ood_b) so GPU runs can be spread
  over quota weeks and still be paired.
- GPU quota left this week: 2.16 h (refresh 2026-10-24 00:00).
