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
- v09 fake-gold: OOD 44/44, check median 22 s / max 30 s (v05 check: 29 / 76 s); about 26/44 OOD tasks get a
  real test result in <= 13 s, the rest get the "slow here" message. Public sound 70/71 (v07: 69/71), check
  median 4.5 s, verdicts identical to v07 per task; rich_4070 now targets the hidden-test file.
- Submitted v09 to the LB on 2026-10-21 (v07 0.10, v02 0.15). GPU run v09 on OOD half A (22 tasks) started.

## 2026-10-21 evening: v09 scorer exception, v09b
- v09 on the LB: "Notebook Threw Exception" (no score, the daily slot is used). Not reproducible from our side:
  the same bundle ran 22 OOD tasks on GPU and 115 fake-gold tasks on CPU in the official harness without a
  harness error, and every per-task exception in agent_runner is caught (only ContainerSetupError re-raises,
  which happens before the agent runs). Likely a scorer-side failure, but one v09-only risk existed:
  check started tests in their own session, so when the harness stopped check at its command timeout
  (`timeout -k 5s`, near the end of the 8 min budget) the tests kept running in the container during patch
  extraction.
- v09b = v09 + check that kills all its test/import processes and removes its temp worktree on SIGTERM / exit,
  reads outputs as bytes (utf-8 replace, last 200 KB), stdin from /dev/null. Local: SIGTERM after 8 s leaves no
  processes and no worktree; normal / failing-test / baseline paths unchanged.
- v09 GPU on OOD half A: **21/22 resolved**, 0 empty, mean 308 s (projected <= 10.3 h). OOD-45 is far easier
  than the hidden set (v02 local sound 24/71, LB 9/58), so it checks robustness on unseen repos, not ranking.
  check on real OOD: median 11 s, max 28 s; locate median 0.8 s.
  Still 10/48 skill calls corrupted by a backtick after the file name (`check.py\`,positional_args:[`), mostly
  repeated in two tasks (pyjanitor_1741, great_tables_869).
- v09b fake-gold (CPU, scorer harness): OOD 44/44 (= v09), sound 69/71: rich_3930 (stand) and rich_4070
  (Pygments guesses "IPython" instead of "Python" in the hidden test; same gold patch also failed this way in the
  v05 and v07 fake runs and passed in v09's: environment flake). v09b queued for submission after the daily reset
  (scripts/submit_when_allowed.py retries every 10 min).

## 2026-10-22 night: offline analysis of v07 traces -> v10
- Time = tokens: 4.8 s per 100 completion tokens at concurrency 4; time-capped tasks produce ~9200 tokens, others
  ~5600. Steps above 1024 tokens are 7% of steps but 15% of all tokens (~48 s per task); thinking_budget is a hard
  cap on the thought (probe v06b: thoughts max ~4000 chars at 1024 vs 6500 at 2048), and truncated thoughts still
  ended in a tool call (4/4), edit rates unchanged -> thinking_budget 1024.
- **7 tasks of v07 sound made their first edit_file at call 29 and got "Tool call budget exhausted"**: 6 of them are
  exactly the 6 call-capped empty patches (fastapi_14306/14873/15800, rich_3470/4075/4076). v02 had 21 rejected
  edits. -> max_tool_calls 40. Time: if the 13 call-capped tasks ran to 8 min, mean 339 -> 365 s; with 15% fewer
  tokens ~310 s (v02 was 393 s and fit the 12 h).
- locate re-ranking experiments (path-mention boost, docs_src penalty, __init__ penalty, dotted-path boost):
  no change on the model-style query (public r1 72/128, r5 98/128; OOD r1 23/28, r5 27/28). Not pursued.
- Failed edits in v07: 13 "old_string not found" (literal \n from double-encoded reads), 8 budget-rejected,
  5 "identical old/new", 3 "occurs N times".
- v10 = v09b + max_tool_calls 40 + thinking_budget 1024 (+ prompt says 40 calls). Queued for the 00:00 UTC slot
  instead of v09b; fake-gold sound run on CPU pushed for mechanics. Needs a paired GPU run (OOD-B, sound) after
  the quota refresh on 2026-10-24 before trusting it.
- v10 fake-gold sound: 69/71, identical to v09b per task. Queued for the 00:00 UTC slot.
- Submitted v10 at 2026-10-22 11:48 UTC (ref 57523322); the overnight auto-submit never got a slot (gave up after 8 h).

## 2026-10-24: v10 exceeded the 12 h scoring limit -> v11 (6-minute cap)
- v10 (ref 57523322) finished COMPLETE with no score: "Your submission notebook exceeded the allowed runtime".
  Different failure from v09 (unhandled error). The rule (overview/code-requirements): 12 h for all patches,
  inclusive of sandbox setup, excluding patch validation. The user saw v07 take ~29 h end to end, so validation
  is roughly half of the wall time; v07 inference fit, v10 (40 calls, 8 min) did not. My own projection for
  v10 was 12.2 h at 365 s/task; the 15% token saving from thinking 1024 did not materialise.
- Cap simulation on recorded GPU runs (scratch cap_sim.py; a resolved task survives if its last edit_file
  was before the cap; duration = min(dur, cap + 25 s)):
  v07 sound-71 (28 resolved, mean 339 s): cap 360 s keeps 27/28, mean 301 s -> 10.0 h / 120 tasks;
  cap 300 s keeps 22/28, 272 s. v09 OOD-A (21): cap 360 keeps 19/21, mean 291 s. v05 sound: 24/26 at 360.
  v07 call-capped tasks reached call 28 at 175-374 s, so with a 360 s cap the extra calls (40) cost ~+8 s mean.
- v11_cap6 = v09b + max_time_minutes 6, max_tool_calls 40, thinking 2048 (v09b), prompt line "40 tool calls and
  6 minutes". Projected ~10.3 h on the hardest public set vs v07's 11.2 h projection that fit.
  GPU eval on sound-71 pushed (alexust/gemma-eval-v11-cap6-sound) to confirm duration and resolution before submitting.
- Full-129 composition (closest to the hidden set) explains v10: v02 full mean 394 s (projected 12.9 h at
  concurrency 4) scored, so the hidden run is a bit faster than the local projection. On the full set 33/129
  tasks were call-capped (28 calls) before the time cap; with 40 calls they run to the 8-min cap instead:
  v10-equivalent mean 435 s (+10% vs v02) -> over 12 h. v11-equivalent (40 calls, 6-min cap): v02 full 352 s,
  v03 full 358 s (-10% vs v02), v07 sound 310 s. Note: the user saw v02 also take > 12 h wall time; that wall
  time includes patch validation, which is excluded from the 12 h rule.
- v12 = v11 + thinking_budget 1024. v07 sound traces: 1582 agent steps, p50 125 / p90 749 / p95 1310 / p99 2101
  completion tokens; the 7% of steps above 1024 tokens hold 39% of all tokens, capping them at 1024 saves ~15%
  of tokens (= time) if the model does not compensate. Mean 6570 completion tokens/task = 328 s at 5 s/100 tok.
  GPU eval alexust/gemma-eval-v12-think1024-sound (sound-71) started 2026-10-24 15:05 UTC alongside v11.
  get_status (has time_seconds_remaining) was called once in 71 tasks; the harness budget_warning is call-based only.
- **v11 sound-71: 25/71, mean 311 s** (v07 28/71, 339 s; paired vs v07 +2/-5). 37 tasks hit the 6-min cap.
- **v12 sound-71: 31/71, mean 301 s** (paired vs v07 +4/-1, vs v11 +8/-2), projected 10.0 h on 120 tasks
  (v07 11.3 h fit the limit). Only 1 task ran past 380 s (664 s, a hung step). thinking 1024 did not hurt.
- Submitted v12 on 2026-10-24 19:09 UTC. Kaggle output download hung for 3 h on the full archive; use
  `kernels output --file-pattern ".*task_results\.jsonl"` first.
- **v12 on the LB = 0.12 (7/58)**, scored 2026-10-25 15:54 UTC (~21 h after submission, so inference fit the
  12 h limit). v02 0.15 (9/58), v07 0.10 (6/58): all three within the +-2-task noise band; local sound-71
  differences (24 / 28 / 31) do not show on the 58 public tasks.

## 2026-10-25: v12 LB 0.12 -> target 0.20; v13 = parallel scouts
- v12 sound-71 endings: 31 resolved (all submitted, median 14 calls, mean 244 s), 22 empty (ALL by the 6-min
  time cap, median 21 calls, no edit at all), 8 wrong submitted, 9 wrong time-capped, 1 call-capped. So a
  third of the tasks spend the whole 6 minutes reading and never edit; on the harder hidden set that share is
  probably larger. The scorer runs tasks sequentially, so vLLM serves one stream at a time: parallel
  sub-agents get extra tokens per wall-second almost for free.
- v13 design: root fixer (= v12 agent) whose first call is the AgentTool `scouts`, a ParallelAgent of three
  LlmAgents (issue-driven, test-driven, data-flow/siblings). Scouts have only run_skill_script with `locate`
  and a new `view` skill (file region / def name / grep) that keeps a shared budget in /tmp/.scout_budget.json
  (18 calls or 150 s, then every call returns a stop message). Each scout writes its report to state via
  output_key; the fixer's instruction ends with `{scout_a?}` `{scout_b?}` `{scout_c?}` (ADK templating,
  optional placeholders), re-rendered on every LLM call, so the reports appear in its system prompt after the
  tool returns. AgentTool (skip_summarization) returns only the last scout's text. ADK branch filtering keeps
  scout events out of the fixer's context; scouts see `{problem_description}` from session state.
  Budget: 60 calls, 6 min, 150 turns. v08 lesson (analyst ran 20+ calls): here the tools themselves refuse after
  the budget, which is the only hard bound available (no per-agent call limit exists in ADK/adk-submission).
- Harness facts: budget_warning is call-based only (fires at <=10 calls left when max_tool_calls >= 20);
  get_status exposes time_seconds_remaining but was called once in 71 tasks; the runner nudges a root agent
  up to 3 times when it stops without submit_patch; session state has problem_description and hints.
- Fake-mode CPU kernel alexust/gemma-eval-v13-scouts-fake8 checks the plumbing (compile, AgentTool over
  ParallelAgent, view skill inside sub-agents, output_key -> templating, patch extraction).
