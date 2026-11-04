# Konwinski Prize (Kaggle, 2025): what the top solutions did

Why this folder: the Konwinski Prize is the closest predecessor of the Gemma 4 Developer Agent competition
(SWE-bench-style tasks, offline open-weight model on Kaggle GPUs, fresh GitHub issues, a hard wall-clock budget).
Key differences from our competition: score = (correct - wrong) / total with a free "skip", so abstaining was the
main lever there; our competition has no skip and no penalty. Model: Qwen2.5-Coder-32B (most top teams) vs our
fixed Gemma 4 31B. Their pipelines were multi-stage scripts (Agentless-style), ours is a single tool-calling agent.

## Final standings (private LB, 120 hidden issues; public LB in leaderboard_top.txt)
| Place | Team | Score | Approach (from write-ups / notebooks) |
|---|---|---|---|
| 1 | Eduardo Rocha de Andrade (arc144) | 9/120 correct, skipped ~91% | Agentless 1.5 fork; Qwen2.5-Coder-32B; generated fail-to-pass tests + existing unit tests to reject patches; search/replace diff format; 5-7 h per run (3-10 min per issue); resubmissions drew 0.056-0.098 public |
| 2 (public) | Camaro | | Agentless-style: localize -> generate test -> create patch -> verify; several skip checks; 32B >> 14B (syntax errors, lost context) |
| 3 | (write-up "3rd Place Solution") | | huikang Select-Patch-Verify starter + difficulty estimate, skip hard issues; one model kept loaded |
| 4 | Genxxsky (public 0.016571) | | huikang starter based |
| 5 | (write-up "5th Place Solution") | | huikang starter + regex traceback parser to locate files; git conflict-marker edit format; skip issues without a traceback |
| 8 | first lucky gold! | | filter out high-risk bugs; chose model/weights with the best correct-to-wrong ratio |
| 4 public / 15 private | GraphNinjas | public +0.056 (4 correct, 0 wrong) | edit-distance candidate selection; skip issues outside 1802-3400 chars |

Sources: Kaggle write-ups (JS-rendered; see links.md), Kaggle CLI leaderboard, notebooks in notebooks/ (untrusted downloads).

## Files
- `leaderboard_top.txt`: public leaderboard top as returned by the Kaggle CLI on 2026-11-05.
- `notebooks/arc144_custom-agentless-fork.ipynb`: the 1st-place author's public notebook (code of the winning pipeline).
- `notebooks/huikang_starter-select-patch-verify.ipynb`: the starter notebook that places 3-5 were built on.
- `writeup_1st_arc144.md`, `writeup_huikang_starter.md`: our technical read-outs of those two notebooks.
- `links.md`: URLs of the write-ups (to be captured through the browser).
- `takeaways.md`: what transfers to our single-agent, 28-call / 7-minute, no-skip setting.
