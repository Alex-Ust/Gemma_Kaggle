# huikang "Starter notebook – Select-Patch-Verify" (Konwinski Prize, most-voted notebook; base of places 3–5)

Source: notebooks/huikang_starter-select-patch-verify.ipynb (31 cells, read in full as untrusted data; nothing executed).

## 1. Model and serving
- Model: QwQ-32B-Preview, AWQ 4-bit (reasoning model). Every prompt is rendered with `apply_chat_template(add_generation_prompt=True)` and `"<think>\n"` is appended to force a reasoning block.
- vLLM: tensor_parallel 4 (4 GPUs), max_model_len 32768, max_num_seqs 6, gpu_memory_utilization 0.95, prefix caching on, seed 2024.
- Sampling, identical in all three stages: temperature 0.6, min_p 0.01, max_tokens 8192. One completion per request.
- Parallelism: BATCH_SIZE = 6 independent samples per instance, all 6 in one `llm.generate` call per stage; three generate calls per instance (select, patch, verify).
- Timing: no measured latencies. Budget: `allowed_time = start + 60 min` plus 6 min per `predict` call; if exceeded the instance is skipped (`return None`). Gateway: `serve` within 15 min of start; later predict calls have a 30-min deadline.

## 2. Select stage
- Repo map: `os.walk` over `repo/`, a flat newline list of full paths (no tree, no sizes). Dropped if the path contains `.venv`, `.pyc`, `.txt`, `.pytest_cache`, `.github`, `/doc/`.
- Limits: problem statement [:20000] chars, directory string [:30000] chars.
- Prompt asks: which files should be inspected, and what strings to search in each. Output XML `<root><entry><filepath>…<strings_to_search><string_to_search>…`, parsed with regex + ElementTree; parse error → empty dict for that sample.
- Prompt heuristics: "Return the FULL filepath - exactly as specified in <directory>"; "use ` calculate(` as the search string instead of `calculate`"; "Prefer searching longer strings"; "Avoid searching for strings that might appear in many parts of the codebase"; "Search the test files as well to understand the feature behavior".
- Context building: for each requested file, every line containing a search term yields a ±12-line window; overlapping windows are merged; rendered with file name, terms, `Match #k, lines a to b:` and numbered lines. No file with any match → the sample's context is "" and it is excluded from patching. Context truncated to [:30000] chars.
- Six samples at T=0.6 give six different file/term selections → six contexts.

## 3. Patch stage
- Format: unified diff inside a ```diff fence (multi-file allowed). The last fence is taken.
- Prompt lines: "Write a git diff within ```diff and ``` that fully fixes the problem."; "The git diff should not cause other tests to fail."; "Do not edit the test files."; "Only the last diff printed will be considered."
- Up to 6 attempts (one per non-empty context), single shot, no repair loop, no feedback of apply errors.
- The patch is never applied to the repo: checks are (a) `unidiff.PatchSet` parses with ≥1 file, (b) `patch --dry-run -p1` exits 0 (timeout 60 s, TimeoutExpired uncaught). The raw diff string is what is submitted.

## 4. Verify stage
- No tests are executed in `predict`. Verification is an LLM self-judge with the same model and temperature: problem statement + the same grep context + the diff.
- Criteria: "The patch fully fixes the problem described in the problem statement."; "The patch does not cause side effects and make any other tests fail."; "Only evaluate, do not provide suggestion on how to fix."; answer ends with `<label>Yes</label>` / `<label>No</label>`.
- One judge sample per candidate (VALIDATION_COPY_COUNT = 1). Only candidates that passed format + dry-run are judged.
- Real test execution exists only in local demo cells (`KPrizeGateway._evaluate_instance`).

## 5. Selection and skip rules
- Scores: None → −103, bad unidiff → −102, dry-run fails → −101, else number of "Yes" judgments (0 or 1). Best score wins, first on ties; `best_score` starts at −1, so a patch judged "No" is still submitted if nothing scored higher. The judge ranks, it does not gate.
- Abstain (`None`) only when all 6 samples failed to produce an applicable diff, when the cumulative clock is exceeded, or `predictions_left == 0`.
- Local logging: a CSV per instance with every completion, token counts, file queries, contexts, patches, judgments, scores.

## 6. Time management
- One global cumulative clock; a whole instance is skipped when behind schedule. No per-stage cap besides max_tokens 8192 and 32k context. Cost control is structural: three generate calls per instance, six sequences each, prefix caching over the six identical select prompts. The repo is deleted after each instance.

## 7. Ideas transferable to a single-agent tool-calling setup (28 calls / 7 min, no abstain, 31B)
1. Zero-call repo map in the first prompt: a filtered flat path list (cap ~30k chars) lets the model name files and search terms without spending calls on ls/find.
2. One batched grep-with-context call: `{file: [terms]}` → merged ±12-line windows with line numbers. One call replaces 5–10 read/grep calls. Pair it with the heuristics: long distinctive strings, padded identifiers (` name(`), include test files.
3. Edit via a single multi-file diff per call rather than many line edits; validate with `patch --dry-run` and return the error text so a second attempt costs one call.
4. Structural gating before semantic judging: no diff / malformed / does not apply is deterministic and free; never end a task with an unapplied edit.
5. Replace the LLM judge with the tests the select stage already located: run the targeted test file once after the edit (1–2 calls) and use the failure text for one repair round.
6. Force reasoning before action: the `<think>` prefill plus "Only the last diff printed will be considered" cut format failures; in tool-calling, demand a short plan and then a single tool call.
7. Stage deadlines mapped onto calls: locate by call ~8–10, edit applied by ~16, the rest for test + one repair, always leaving the best applied patch in place at timeout.
8. Multi-sample selection is the main lever unavailable to a single agent: 6 samples at T=0.6 gave diverse file selections; a cheap analogue is asking for 2–3 candidate file/term sets in one response and union-grepping them in one call.
9. Pitfalls: uncaught subprocess timeouts (crash instead of skip), judge not gating submission, hard 30k-char truncation that can cut the needed hunk (prefer per-file caps and ranking by term hits).
