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
- Fake-mode results: fake8 8/8 gold patches applied through the new tree (scouts ran in parallel, view
  worked, output_key reports returned), but the view budget leaked across tasks: on Kaggle tasks run in a
  SubprocessSandbox on the shared host filesystem, so /tmp is NOT per task. Fixed: budget file lives in
  <workspace>/.git/scout_budget.json keyed by HEAD commit + .git ctime. fake4 re-check: 4/4, budget fresh in
  every task. GPU run alexust/gemma-eval-v13-scouts-sound (sound-71, concurrency 2 so that 3 scouts x 2 tasks
  = 6 streams stay close to the usual 4) started 2026-10-25 17:00 UTC.
- **v13 sound-71: 16/71 (v12 31), 43 empty, 50 time-capped.** The scouts phase took mean 214 s / median 205 s
  (min 43, max 353) in the 41 tasks where it returned at all; in 29 tasks the 6-min cap fired inside the scouts
  tool (no agent steps in the trace). Scouts ignored "6 calls": ~20 view calls per task, and the final report
  step alone costs ~60 s (1024 thinking + 500-token report). Where the scouts did return, the fixer resolved
  16/42 = 38%, no better than v12's 44%. Parallel exploration is dead: Gemma's ~10 s per step makes any
  multi-step sub-agent cost minutes, and the slowest scout gates the fixer. Not a candidate.
- **Ceiling finding:** over 7 sound runs (v02..v13) the union of resolved tasks is 35/71; 36 sound tasks were
  never resolved by any version, 29 were resolved 3+ times, 11 in all runs. v12 (31) is already near the
  pass@7 union (35), so prompt/budget work cannot add more than ~3 tasks locally; the hidden-set gap is the
  model, not the harness. LB 0.20 = 12/58 needs a different model behaviour, i.e. a LoRA.

## 2026-10-25 evening: trace study of public runs -> context compaction is the hidden tax (v14)
- The scorer (and our eval kernel, same EventsCompactionConfig) compacts the ADK session when the prompt
  reaches 14,336 tokens: all but the last 5 events are replaced by a Gemma-written generic summary
  ("summarize the conversation...", LlmEventSummarizer default prompt), including the task prompt with the
  issue text. Detected in traces as a prompt_tokens drop > 2000 between consecutive steps.
- Frequency: v07 70/71 tasks, v12 69/71; 1.4 compactions per task. Cost: the step after a compaction takes
  a median 40 s instead of 5.5 s (the summarizer is an extra full-context LLM call) -> ~57 s per task, 16%
  of the 6-min budget. v07: when the first compaction came before the first edit, 2/17 resolved; after the
  first edit, 25/39. Median first edit at step 9, median first compaction at step 12 (p25 step 9).
- Token accounting (806 steps): prompt growth per step = tool output + previous completion tokens
  (corr 0.95): thoughts are re-sent every turn (include_thoughts true). Baseline prompt 4.8k tokens
  (system 2k + harness task prompt + tool schemas). Mean completion 277-305 tokens/step, tool output ~340,
  so ~750 tokens/step -> threshold at ~12 steps. locate output median 4.1k chars, read_file 1.9k.
- adk-submission supports include_thoughts: false explicitly (install_litellm_reasoning_patch: thinking stays
  on, thought parts are dropped from history and reasoning_content stripped from outgoing messages). The
  "include_thoughts essential" note was community hearsay, never measured by us.
- v14 = v12 + (a) issue text inside the system instruction via {problem_description} / {hints?} so the spec
  survives compaction, (b) include_thoughts false (~440 tokens/step -> compaction only after ~22 steps),
  (c) locate SHOW_CHARS 4500 -> 3000, (d) compact prompt (6.5k chars) with "edit within 8 calls, context is
  summarized after ~12". GPU run alexust/gemma-eval-v14-nocompact-sound started 2026-10-25 ~22:10 UTC.
- v12 wrong patches (17): 14 touch a gold file. Near misses (gold +1..+4 lines) are underspecified by the issue
  text, not fixable by rules: fastapi_14479 (agent copied the old message from the issue traceback, the gold
  reworded it and the hidden test asserts the new wording), rich_3471 / rich_3944 ("Fixes #NNNN" only),
  fastapi_14258 (gold uses assert, agent raised FastAPIError; issue text does not say), fastapi_13920 (helper
  added but not wired into analyze_param). The sound-71 "never resolved" set is dominated by such tasks.

## v14 nocompact: 27/71 (v12 31/71) — thoughts dropped from history cause loops

sound-71, concurrency 4, 2026-10-25 20:30–22:40 UTC. Paired vs v12: +1 / -5 (net -4).
mean dur 292 s (v12 301), timeouts 30 (31), empty patches 26 (23), no-edit tasks 24 (22).

Compaction did fall: 0.54/task vs 0.92, tasks with a compaction 27 vs 55, prompt growth per
step 539 vs 753 tokens. But resolution fell with it. Cause found in the traces: with
include_thoughts: false the model repeats identical failed calls.

| run | tasks with >=3 identical consecutive calls | repeated calls / all calls |
|---|---|---|
| v12 | 8  | 60 / 1437 |
| v14 | 15 | 239 / 1507 |

Examples: rich_3067 ran the same broken python -c command (a backtick inside double quotes,
bash "unexpected EOF") 27 times in a row; rich_3676 the same repro heredoc 12 times;
fastapi_14258 19 times; rich_4070 24 times. 4 of the 5 lost tasks never edited at all.
Without its own thoughts in history the model has no record of "this failed, try differently":
the history is bare function calls with identical error results, and at temperature 0.2 the
next sample is the same call again. The prompt's "after a second failure use a different tool"
is not enough on its own.

Next (launched 2026-10-26 ~00:20 UTC, both on sound-71):
- v15_thoughts = v14 with include_thoughts: true (isolates the other v14 changes: issue text in
  the system prompt, compact prompt, locate SHOW_CHARS 3000).
- v16_temp07 = v14 with temperature 0.7 (loop-breaking without re-sending thoughts).

## v15 / v16 results (2026-10-26 ~01:30 UTC): the v14 family is worse than v12 on every axis

| run | change vs v14 | resolved | timeouts | no-edit | loop tasks | repeats | compactions/task | locate used |
|---|---|---|---|---|---|---|---|---|
| v12 | (baseline) | 31/71 | 31 | 22 | 8 | 60/1437 | 0.92 | 71/71 |
| v14 | issue in system prompt, compact prompt, locate 3000, thoughts dropped | 27/71 | 30 | 24 | 15 | 239/1507 | 0.54 | - |
| v15 | v14 + include_thoughts: true | 25/71 | 36 | 26 | 5 | 36/1438 | 0.86 | 48/71 |
| v16 | v14 + temperature 0.7 | 22/71 | 35 | 22 | 14 | 274/1624 | 0.45 | - |

Paired vs v12: v15 +1/-7, v16 +2/-7.

Findings:
1. Loops are caused by dropping thoughts from history, confirmed both ways: thoughts back (v15)
   -> 5 loop tasks / 36 repeats, the fewest of any run; temperature 0.7 without thoughts (v16)
   does not break the loops (14 tasks / 274 repeats). include_thoughts: false is dead.
2. The v14 prompt rewrite itself costs ~6 tasks (v15 vs v12, 7 losses / 1 win). The visible
   mechanism: locate was called in only 48/71 tasks (v12: 71/71). The compact PROCEDURE
   ("First call: locate") is weaker than v12's wording, and the model wanders instead; the lost
   tasks mostly never edited (5 of 7) while making fewer, slower steps.
3. Compaction is a cost, not the bottleneck: v14/v16 halved it and lost tasks anyway.

Decision: v12 stays the best validated bundle (31/71, LB 0.12 / pending redraw). The
"less context" direction is closed. GPU quota after tonight ~26.5 h of 30 (resets Saturday
00:00 UTC), not enough for another sound-71 run this week.

## LoRA plan (2026-10-26, user go-ahead received)

Data: successful trajectories from our own runs (rejection-sampling SFT). scripts/sft_extract.py turns
ATIF traces into OpenAI-style messages (reasoning_content = thought parts, tool_calls, role tool
results); 95 trajectories over 37 tasks after keeping the 3 shortest per task. Rendering with the
real Gemma 4 chat template (research/lora/hf_tokenizer, from the unsloth mirror) and the exact tool
declarations the harness sends (scripts/dump_tools.py -> research/lora/tools.json, 10 tools incl.
the SkillToolset's list_skills/load_skill/load_skill_resource/run_skill_script):
- one model turn per trajectory: <|channel>thought ... <channel|><|tool_call>call:NAME{json}<tool_call|>
  <|tool_response>response:NAME{value:<|"|>...<|"|>}<tool_response|> ... <turn|>
- loss mask: 1 inside the model turn except tool_response spans (research/lora/sft_render.py)
- tokens median 11.3k, 82/95 <= 16k
- THINK=1 (thoughts kept, enable_thinking on): 41 examples (v14/v16 rows have no thoughts; 17 too long)
- THINK=0 (thoughts stripped, enable_thinking off): 91 examples. Choice depends on v17 (no-think) result.
Training: research/lora/kernel/train.py, HF Transformers + PEFT on the bf16 google/gemma-4-31b-it
(Kaggle Transformers/gemma-4-31b-it/1), 4x L4 device_map=auto, gradient checkpointing, chunked
CE (262k vocab), rank 16 alpha 32 lr 1e-4 cosine, 2 epochs, accum 4, max_len 16384.
Data on Kaggle: dataset alexust/gemma-sft-traj. Serving check first: v18_lora_smoke = v12 + a
zero-effect rank-8 q_proj adapter named with HF PEFT keys (base_model.model.model.language_model.
layers.N...), 2 tasks, to verify vLLM loads a LoRA onto the qat-w4a16 base. Quota: train on
Saturday after the weekly reset (training est. 3-4 h wall = 6-8 h quota, then OOD-45 + sound-71 evals).

## v17 nothink: 18/71 — thinking off is dead

v12 with thinking_budget 0 and "write one or two sentences before each call" as memory. Fast (mean
191 s, median 28 calls, 12 tasks hit the 80-turn budget) but 1633 of 2758 calls repeat the previous
call verbatim; the visible notes were mostly empty. Paired vs v12: +1/-14. Thoughts are the model's
working memory; neither hiding them (v14) nor removing them (v17) works. Final config stays v12
(thinking on, thoughts in history) and the LoRA data is rendered in that mode.

LoRA data v2: thinking-on runs only (v02, v03, v05, v07, v11, v12, v15), up to 6 trajectories per
task: 170 trajectories over 38 tasks; 133 fit in 20,480 tokens (median 14.3k). Dataset
alexust/gemma-sft-traj updated. Training moves to RunPod (user budget $20/week): QLoRA (nf4 base,
QUANT=1) on a 48 GB card, est. $2-4 per run; research/lora/runpod/bootstrap.sh.

## LoRA serving smoke (v18_lora_smoke, 2026-10-26 12:21 UTC): vLLM loads a PEFT adapter on the qat-w4a16 base

v12 + zero-effect rank-8 q_proj adapter `zero` (HF PEFT key names
base_model.model.model.language_model.layers.N.self_attn.q_proj.lora_{A,B}.weight, bf16), 2 tasks.
vLLM started (adapter discovered, max_lora_rank 8), traces show model_name "zero" for every step,
14 + 25 tool calls served without an error. Both tasks timed out at 6 min as they usually do.
So: the harness routes the agent to the adapter, and vLLM accepts the HF-style key names on the
compressed-tensors base. Adapter weights travel to the eval kernel via the dataset
alexust/gemma-lora-adapters as flat <name>.adapter_config.json / <name>.adapter_model.safetensors
(make_eval_kernel --adapters-dataset). For the real submission they go into submission.zip under
adapters/<name>/ (size budget 3 GiB; rank 16 on all 7 projections ~ 250 MB).

## RunPod training, day 1 (2026-10-26 evening UTC): memory on 48 GB, chunked attention

L40 48 GB, QLoRA: every example OOMed. Diagnosis with memtests (research/lora/kernel scratch):
4-bit base is 17 GB, but attention on Gemma 4 goes through the sdpa *math* path (global layers
have head_dim 512 with 4 KV heads, sliding layers head_dim 256 with bool masks), materializing
32 x T x T scores in fp32 per layer: ~16 GB at 8k, 100 GB at 20k. flash-attn 2.8.3 refuses
head_dim 512; flex_attention fails on L40 (triton resource limit). A bigger GPU alone would not fix 20k.
Fix: research/lora/kernel/chunked_attn.py registers attn_implementation "chunked": queries in
chunks of 1024, each chunk's sdpa recomputed in backward (torch checkpoint), keys sliced to the
causal/sliding range. Verified: identical to transformers' sdpa_attention_forward on synthetic
masks (max diff 1e-3 bf16), layer-0 divergence on a real trajectory 0.0003 growing only by bf16
accumulation (two sdpa runs are bit-identical, sdpa vs sdpa-math differ as much as chunked).
Plus torch.autograd.graph.save_on_cpu for the checkpointed activations. Result on L40 QLoRA:
8k 26.5 GB / 36 s, 20k 39.8 GB / 116 s per example.
User then allowed pricier GPUs: moved to RTX PRO 6000 Blackwell 96 GB ($2.49/h, Secure) to train
in bf16 (QUANT=0), no nf4-vs-QAT mismatch and faster. L40 pod deleted (~$1.3 spent).

## Training run 1 started (2026-10-26 19:40 UTC), pod sy7dbb0o0g5l77 (RTX PRO 6000 Blackwell 96 GB, EUR-IS-2, $2.49/h)

Second pod (zz6zvlh22nqcf7) had broken egress (pypi.org and every mirror unreachable, HF flaky) and was
deleted; the third pod with dataCenterIds preference EUR-IS-2 has a clean network (pypi 0.25 s).
Config: bf16 base, LoRA r16 a32 on q/k/v/o/gate/up/down of the 60 text layers (122M params),
lr 1e-4 cosine, 2 epochs over 133 trajectories (think-on, <= 20,480 tokens), accum 4, chunked
attention + CPU-offloaded checkpoints. Speed: 11k tokens 26 s, 16.5k 43 s -> ~2.5 h, ~$6.5.
First losses 0.30, 0.26 (the model already likes its own successful trajectories; SFT sharpens them).

## Scorer stack (from the Kaggle wheelhouse, 2026-10-26): vllm 0.19.1, transformers 5.13.1, torch 2.10 (cu128), google-adk 1.36.1, swegemma 0.2.11, adk-submission 0.2.13
RunPod eval env mirrors it: /workspace/evalenv (venv) with those wheels force-installed by run.py, plus
litellm, pytest, pytest-timeout==2.1.0, typer and build backends (the Kaggle image has them; the task
sandbox venvs inherit the host python, so gold mode failed with "No module named pytest" until added).
Gold mode on the pod: 2/2 resolved, tests run in 4 s. Eval scripts: /workspace/run_v12.py and
/workspace/run_lora.py (sound-71, concurrency 6); the adapter is staged as
/kaggle/input/datasets/alexust/gemma-lora-adapters/v1.* by /workspace/after_train.sh.

## v12 redraw scored 0.10 (2026-10-26 ~17:30 UTC)
v12 public draws: 0.12, 0.10. v02's 0.15 stays the best public. v12's true public rate is ~6-7/58.

## Night of 2026-10-26: three pods in parallel (user topped up the balance)
- pod A sy7dbb0o0g5l77: training run 1 (2 epochs) -> then LoRA epoch-2 arm on sound-71 (run_lora.py)
- pod B coezet1g2dhgfb: baseline v12 on sound-71, same GPU (run_v12.py); env copied pod-to-pod
- pod C hebvtfqk06rjyz: LoRA epoch-1 checkpoint arm on sound-71 (adapter_ep1 copied from pod A)
All three on RTX PRO 6000 Blackwell 96 GB, concurrency 6, so timing conditions match across arms.
Per-task-10 data variant prepared (research/lora/sft_messages_c10.jsonl: 142 usable examples vs 133),
not trained yet.

### 2026-10-26 evening: three-pod plan collapsed to one pod

- Pods B/C (RTX PRO 6000, same DC as A) could not be fed from pod A: RunPod pods cannot reach each other's
  public IP:port (TCP connect times out in both directions, no shared private network between pods), so the
  58 GB environment copy never started. Copying through the Mac would take hours; a fresh bootstrap on each pod
  needs the Kaggle token (user-only) and ~1 h of paid time per pod. Deleted B and C (~15 min idle each, ~$1.3).
  Also: zsh does not word-split an unquoted `$SSH` variable, so driver loops must be bash scripts, not inline zsh.
- Balance after deletion: $19.30, burn $2.51/h (pod A only). Pod A: training ex ~110/266 at 20:45 UTC,
  loss 0.09-0.15, 81 GB, finish ~22:15 UTC, then `after_train.sh` runs the epoch-2 LoRA arm on sound-71
  (concurrency 6, ~2.5-3 h, ~$7). Baseline reference = Kaggle v12 draws (31/71 sound, 25-31 band) unless budget
  allows a pod baseline afterwards (~$7). v12 resubmission scored 0.10 (LB: v02 0.15, v12 0.12/0.10).
- 22:11 UTC training done (266 examples, 2 epochs, final losses 0.05-0.15; adapter 467 MB, 820 tensors, sha256 2ebf6780...).
  Fetched to research/lora/adapters/v1/adapter and copied into submissions/v19_lora_v1/adapters/v1; packed zip 452 MB.
- First LoRA arm on pod A failed silently: every model call raised `cannot import name 'CacheableResult' from mcp.types`
  (litellm 1.106.4 vs mcp 1.30.0 pinned by google-adk). Gold mode never calls the model, so the earlier 2/2 gold check did
  not cover this. Fix: `pip install -U mcp` (2.3.0) in evalenv; harness imports still fine. Arm restarted 22:27 UTC.

### 2026-10-26 late: adapter v1 is broken by a rendering bug (root cause found)

- The pod LoRA arm (restarted 22:27 UTC) resolved 0/63 before I killed it: every task timed out with 0 tool calls.
  Traces show the adapter's tool calls arrive with quotes inside keys and values, e.g.
  `{"\"file_path\"": "\"locate.py\""}` — the tools then reject the arguments ("Argument 'skill_name' is required"),
  the model retries until the 6-minute timeout, and swegemma counts none of it as tool calls.
- Raw probe via /v1/completions (skip_special_tokens=false), same prompt, three models:
  base emits `call:run_skill_script{file_path:<|"|>locate.py<|"|>,positional_args:[<|"|>...<|"|>],skill_name:<|"|>locate<|"|>}`;
  v1 and ep1 emit `call:run_skill_script{"file_path": "locate.py", "positional_args": [...], "skill_name": "locate"}` (JSON).
  Thoughts, tool choice and timing of the adapters look healthy otherwise.
- Cause: sft_extract stores `function.arguments` as an OpenAI JSON string; the Gemma 4 chat template renders a *mapping*
  in the native DSL but passes a *string* through verbatim (template comment: "Prefer passing arguments as a mapping").
  So all 133 training trajectories taught JSON-quoted arguments. Fix in sft_render.prepare_messages: json.loads the
  string into a dict. Re-rendered calls now match the base model's format byte for byte, and all 15 calls of the first
  trajectory round-trip through vLLM's `_parse_gemma4_args` (vllm 0.19.1) to the original dicts.
- Kaggle submission 57680204 (v19 with the broken v1) will score ~0; nothing to do about it (slot used on 10-26).
- Training run 2 started ~23:55 UTC on pod A (same hyper-parameters, OUT=/workspace/adapter2, log train2.log).
  Balance $11.3 at start, $2.51/h: training ~$6.3, leaving ~$5 (~2 h) for the eval of v2; a $10 top-up would fund
  the full 71-task eval plus a pod baseline.
- Side finding: vLLM's chat endpoint returns empty `reasoning_content` for the base model too (reasoning parser), so
  ADK sees thoughts only via the content/thought channel it already uses; unchanged from Kaggle behaviour.

### 2026-10-27 night: adapter v2 (run 2, DSL arguments fixed) — 12/71 on the pod, second rendering bug found

- Training run 2 finished 02:34 UTC (135 examples ≤20480 tokens, 2 epochs, 68 optimizer steps, losses 0.06-0.13,
  2 h 36 min). Adapter fetched to research/lora/adapters/v2/adapter (489,840,816 bytes). LoRA arm on sound-71
  (concurrency 6, RTX PRO 6000) ran 02:36-03:37 UTC: **12/71 resolved (0.169)**. Results in
  runs/v20-lora-v2-pod/results (task_results.jsonl + 71 traces).
- Tool-call format is fixed: calls arrive as proper dicts, 23/71 tasks produced a patch, 12 resolved
  (fastapi_14794, 14786, 14492, 14372, 5077, rich_3718, 3882, 3894, 3676, 3454, 3067, 3006).
- Failure split: 30 tasks `litellm.ContextWindowExceededError` with tool_calls=40 after only 2-4 LLM calls,
  20 session timeouts, 4 tool-call budget, 17 clean finishes.
- **Root cause 2: the `<|tool_response>` stop token was masked out of the loss.** generation_config.eos_token_id is
  [1, 106, 50]; after `<tool_call|>` the model must emit `<|tool_response>` (id 50) and the server stops there.
  sft_render masked the whole `<|tool_response>…<tool_response|>` span including the opening token, so the adapter got
  no supervision on the one token that ends a tool-call turn. Symptom in traces: one response with 283 identical
  `read_file` calls, completion_tokens 8192 (max_output_tokens), 258 s. Raw probe on a real second-turn prompt
  (fastapi_15661 after the first grep, n=6 samples, temperature 0.2): adapter v2 → 2/6 run away (68 and 15 calls,
  finish=length), 3/6 emit an empty thought; base → 6/6 stop after one call with a 440-620-char thought.
  The runaway generations also hog the GPU, which explains many of the 20 timeouts in the concurrent tasks.
- Fix: sft_render.render now keeps mask=1 on the opening `<|tool_response>` token (verified on 40 rows: 744/744
  stop tokens trained, previous token `<tool_call|>` trained, following token masked). Needs training run 3.
- First-turn behaviour of v2 is clean (DSL call, finish=stop, 159 tokens); with the prior thought removed from the
  history both base and adapter answer with an empty thought, so the harness-side history rendering is not the
  difference.
- Pod A deleted 03:46 UTC after fetching results and probing; RunPod balance $1.53, no pods. Kaggle 57680204
  (v19, broken v1) still pending; it blocks the next submission until it scores (~19:30 UTC). v2 (12/71) is not
  worth a submission slot; v12 remains the best validated bundle.
- Cost of a v3 cycle on one RTX PRO 6000 ($2.51/h): fresh bootstrap ~0.7 h, training ~2.6 h, LoRA arm ~1.1 h,
  optional v12 baseline arm ~1.1 h (fair comparison on the same hardware; v12 Kaggle = 31/71) → ~$14-17;
  without the baseline ~$11-12.
- Ready for the v3 cycle: bundle skeleton submissions/v21_lora_v3 (v12 + `adapter: v3`), pod eval script
  runs/v21-lora-v3-pod/kernel/run.py (sound-71, concurrency 6, adapter staged as v3.*), driver
  research/lora/runpod/run3_chain.sh <ip> <port> (training bootstrap + eval bootstrap in parallel, then train → fetch →
  LoRA arm → results in runs/v21-lora-v3-pod/results). Needs: pod create, `runpod_lora.py upload`, user-copied Kaggle token.

## 2026-10-27 — adapter v3 (stop-token fix) on the pod: 31/71, equal to v12

`runs/v21-lora-v3-pod`: 31/71 = 0.437, exactly v12's 31/71 on Kaggle (28 tasks in common, 3 each way: v3-only
fastapi_5077, rich_3278, rich_4075; v12-only fastapi_14616, rich_3454, rich_3676). The stop-token fix works: no runaway
(tool_calls median 19; the six 40-call tasks have ≤4 repeats of any call) and no ContextWindowExceeded. v3 is more
efficient than v12 on the same budget: 23 six-minute timeouts vs 31, 16 empty patches vs 23, mean task duration
261 s vs 301 s, 55.7 min wall for 71 tasks at concurrency 6. Pre-check (`runs/v21-lora-v3-pod/precheck.txt`): 6/6
clean stops. Conclusion: self-distillation on 38 unique tasks reproduces v12 but does not beat it; more unique
tasks are needed (harvest: OOD-45 at t0.2 + the 36 unsolved sound tasks ×3 at t0.7 → `h01-harvest-t07-podhard`).
Submission `submissions/v21_lora_v3` packed (453 MB zip) for the LB after 57680204 scores.

## 2026-10-27 — harvest for v4: OOD-45 38/44 with v12, unsolved-36 at t0.7 gives 1+2

- `runs/v12-think1024-podood` (OOD-45, v12, t0.2, pod): **38/44** (urllib3_5279 skipped on py3.12), 1 timeout. The
  OOD tasks are much easier than sound-71 (small repos, short patches: median 9 calls). First attempt died because the
  copy staged from the Mac lacked `wheels/` (2 GB) and 15 snapshots; `ood_fetch.sh` downloads the full 5.3 GB dataset
  on the pod (needs the user's token) and checks SHA256SUMS minus dataset-metadata.json.
- `runs/h01-harvest-t07-podhard` (36 never-solved sound tasks, t0.7): s1 1/36 (rich_4075, already solved by v3),
  s2 2/36 (rich_3180, rich_3506). s3 cancelled: ~1 new task per $1.5 pass is not worth it.
- Dataset v4 = sft_extract over all real-agent runs (incl. v09 OOD-A, v13-v17, v20, v21, s1, s2, OOD pass) with
  `scripts/sft_filter.py` (thought-only rows, then the N shortest per task). v3's set had 38 unique tasks / 135 usable.

## 2026-10-27 — adapter v4 (70-task dataset): 30/71. LoRA self-distillation is at its ceiling

`runs/v22-lora-v4-pod`: 30/71 (v3 31, v12 31; 28 in common with v3; union of the three = 35). Pre-check 6/6 clean.
The adapters change behaviour (empty patches 9 vs 16 vs 23, mean duration 250 vs 261 vs 301 s) but not the number
of correct patches. Adding 32 OOD-45 tasks (16 unseen repos) did not help on the sound-71 set. Conclusion: training
on the model's own successful trajectories (rejection-sampling SFT) reproduces v12's level and no more; stop here.

**Public LB distribution (2026-10-27, 3941 teams):** 0.24 x5, 0.22 x47, 0.20 x209, 0.18 x551, 0.17 x669,
0.15 x568, 0.13 x395, 0.12 x323. The 1220-team mass at 0.17-0.18 is almost certainly the unmodified public
baseline. We never submitted it (v01_public_baseline: graph tools, 8 min / 28 calls / thinking 4096); all our
submissions were modified bundles and scored 0.10-0.15. The local sound-71 ranking (v12 31 vs v02 24) does not
transfer to the hidden set. Next: submit v01 unchanged as the anchor, then small changes on top of it with its
budgets kept.

**Correction (2026-10-27 evening):** v01_public_baseline is NOT the organizers' baseline; it is the public
"budget-fit" bundle (flexonafft v2 / verracodeguacas, 8 min / 28 calls / thinking 4096). The organizers' sample
submission (data/sample_submission) is a 1-minute / 10-call dummy with sample LoRA adapters. The public notebook
honghanhhh/gemma-4-baseline-lb-0-24 ("v6, prompt-only edits on the 0.22 config", LB 0.24) ships a bundle that is
byte-identical to our v01 except one prompt line (`git status --short && git diff` before submit_patch); its author
reports that lowering the budgets scored 0.13, matching our v12 draws (0.12/0.10 at 6 min). Our v02 (v01 minus the
graph tools in agent.yaml) scored 0.15 on 2026-10-18. Conclusion: keep the 8-min/28-call/thinking-4096 budgets;
the 6-min cap we adopted to fit 12 h cost ~5 tasks on the hidden set. Bundle copied as submissions/v23_public_lb024
(submit after 57680204 scores).

**LB submission errors found via the API (2026-10-27):** 57487659 (v09, 2026-10-21) "unhandled error while
rerunning" (never scored); 57523322 (v10, 2026-10-22) "exceeded the allowed runtime" (12 h). So the scored
history is: v02 0.15 (8 min / 28 calls / thinking 4096, no skills), v07 0.10 (8 min / 28 calls, thinking 2048,
timeout 90 s, locate+check skills, first-call prompt), v12 0.12 / 0.10 (6 min / 40 calls / thinking 1024).
Every modification we made scored below v02 on the LB, while the local sound-71 numbers went up (24 → 28 → 31).
The public bundle equal to v01 (v02 + the three graph tools listed) reports 0.22-0.24.

## 2026-10-27 — audits (two passes) of the whole pipeline: what misled us

1. **Concurrency.** Local kernels ran 4-8 tasks in parallel on one GPU; the scorer (starter notebook, inference.py)
   runs tasks one at a time. The per-task time budget is agent wall-clock, so vLLM queueing inflated local
   timeouts (31-37/71 time-capped). The 6-min cap, thinking 1024 and "edit early" prompts were tuned to that
   artefact. Benchmarks must run at low concurrency, or with a measured inflation factor (12-task calibration).
2. **LB noise.** Identical bundles draw 7-13/58 (NOTES "Community evidence"); our 0.10/0.12/0.15 draws and the
   public 0.22/0.24 are within noise of one config family. Never rank on a single draw.
3. **12 h limit** is all-or-nothing (v10 died). pull_eval.py projects from duration_seconds (includes setup and
   Phase 2 verification, measured under concurrency) — wrong quantity twice. Project agent-only time + capped share.
4. **Oracle labels** (sound 71) came from a subprocess stand on Kaggle host python 3.12; Stage 2 on the scorer is
   docker python 3.13-slim, 2 vCPU / 4 GiB, 300 s. Membership may differ by a few tasks (unverifiable without docker).
5. **sound105 fix**: in the subprocess backend the sandbox venv inherits the harness env (`_host_env.pth`), so
   installing inline_snapshot + dirty_equals into evalenv made 30 fastapi tasks sound (gold 30/34, empty 0/30).
   On the official scorer those tasks stay unsolvable (the wheelhouse lacks the packages).
6. **Prompt facts wrong in the anchor v23**: "scratch files in /tmp" (write_file rejects /tmp: path traversal;
   v12 fixed it, v23 did not), "automatic failure" for touching tests (actually stripped silently), graph tools
   declared but forbidden. Candidate small change for v24: scratch via run_command heredoc under /tmp.
7. **v12/v07 prompt claim "tool results are JSON-encoded twice" is false** (one layer; trace JSON added the second).
8. **check.py orphans**: under the subprocess backend a SIGKILLed check leaves its start_new_session jobs alive
   (CPU for the next sequential task). Drop start_new_session if skills return.
9. **SFT**: trained on uncompacted contexts while serving compacts at 14,336 tokens (46/170 rows); nudge user
   turns trained as model output (3/170). Fix before any further LoRA.

- 2026-10-27 20:54 UTC: submitted **v24_tmpfix** (57712978) = public 0.24 config with the /tmp write_file
  instruction corrected; scoring ≈ 21 h. v19 (adapter v1) scored 0.00 as expected. Local: v23 baseline on
  sound105 running on the pod (concurrency 3), then a 12-task concurrency-1 calibration, then v24 on sound105.
