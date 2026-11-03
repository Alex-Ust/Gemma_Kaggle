"""Build the runtime notebook (.ipynb) with the timing CSV embedded."""
import sys, nbformat as nbf
W = sys.argv[1]
csv_text = open(f"{W}/task_times.csv").read()
V27_NOTE = sys.argv[2] if len(sys.argv) > 2 else "pending"

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = []

cells.append(md(f"""# One Bundle, Three Outcomes: 0.24, 0.17, No Score

The public notebook [Gemma 4 Baseline | LB 0.24](https://www.kaggle.com/code/honghanhhh/gemma-4-baseline-lb-0-24) scored 0.24 for its author. We submitted its bundle **byte for byte** and got no score at all:

> *Your submission notebook exceeded the allowed runtime.*

Score noise between identical submissions is already well documented (see [Same Bytes, Two Scores](https://www.kaggle.com/code/victorzhong0110/same-bytes-two-scores) and [Most-Run Public Config Averages 10/58](https://www.kaggle.com/code/dariushafshar/gemma-4-most-run-public-config-averages-10-58)). This notebook is about the other failure: **the same bytes can also run out of time.**

**TL;DR**
- The 12-hour limit covers all ~120 hidden tasks, sandbox setup included, patch validation excluded. A bundle can only cap each task (`max_time_minutes`, `max_tool_calls`); there is no global deadline.
- We timed 101 local runs of this exact bundle. Scaled to a scorer that runs 1.6-1.7x slower than our setup, the 8-minute cap lands at about **12 h for 120 tasks**: right at the limit, so some draws finish and some do not.
- A **7-minute cap** buys about 40 minutes of margin there and costs at most one solved task in 30. A 6-minute cap buys about 1.5 h but costs three to five.
- Our 7-minute submission: {V27_NOTE}
"""))

cells.append(md("""## What happened

All rows are our own submissions unless marked. "28 / 8" means `max_tool_calls: 28`, `max_time_minutes: 8`.

| Submission | Caps (calls / min) | Public LB |
|---|---|---|
| honghanhhh, *Gemma 4 Baseline \\| LB 0.24* (author's draw) | 28 / 8 | 0.24 |
| The same bundle byte for byte (zip sha256 `205a677f…`), 2026-10-30 | 28 / 8 | **no score: exceeded the allowed runtime** |
| The same bundle with `max_time_minutes: 7` and the prompt line changed to match, 2026-11-02 | 28 / 7 | **0.15, finished in time** |
| The same bundle + one prompt line about scratch files, 2026-10-27 | 28 / 8 | 0.17 |
| Same caps, a prompt that saves tool calls, 2026-10-29 | 28 / 8 | 0.12 |
| 40 tool calls, 8 minutes, 2026-10-22 | 40 / 8 | **no score: exceeded the allowed runtime** |
| 40 tool calls, 6 minutes, thinking budget 1024 (two draws) | 40 / 6 | 0.12, 0.10 |

Two things follow. One file set gives 0.24, 0.17 or nothing, so a single draw says little. And the bundles that timed out were the ones whose caps allow the most time per task.
"""))

cells.append(md("""## How the timings were measured

- **Setup:** RTX PRO 6000 96 GB, vLLM 0.19.1, `gemma-4-31b-it-qat-w4a16-ct` with `max_model_len` 32768, `swegemma` 0.2.11 with the bundle's own `eval_config.yaml`, three tasks at a time. Running three tasks at once makes each model call about 1.4x slower than running one.
- **Tasks:** 101 tasks from the competition's training data (fastapi 59, rich 42).
- **Bundles:** `public_8min` is the LB-0.24 bundle unchanged. `callsaver_8min` is the same caps with a prompt that spends fewer tool calls.
- **`agent_s`:** seconds from the start of the task to its last tool call, read from the trace timestamps. The model's final turn after the last call is not included, so this slightly underestimates.
- **`last_edit_s`:** time of the last source edit (`edit_file`, `write_file`, or a shell command that writes files).

The data is embedded below, so the notebook needs no inputs.
"""))

cells.append(code(f'''import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

CSV = """{csv_text}"""
df = pd.read_csv(io.StringIO(CSV))
pub = df[df.bundle == "public_8min"].reset_index(drop=True)
cs = df[df.bundle == "callsaver_8min"].reset_index(drop=True)

summary = df.groupby("bundle").agg(
    tasks=("task", "size"),
    resolved=("resolved", "sum"),
    hit_28_calls=("tool_calls", lambda s: int((s >= 28).sum())),
    agent_mean_s=("agent_s", "mean"),
    agent_p90_s=("agent_s", lambda s: s.quantile(0.9)),
).round(0)
summary'''))

cells.append(md("""Locally the 28-call cap stops most long tasks before the 8-minute cap does. Only a handful of tasks get near 8 minutes on our hardware:"""))

cells.append(code('''# Colors: validated light-mode reference palette (ordinal blue ramp for the caps)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE = "#2a78d6"
CAP_COLOR = {8: "#104281", 7: "#2a78d6", 6: "#86b6ef"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})

fig, ax = plt.subplots(figsize=(9, 3.8))
bins = np.arange(0, 541, 30)
ax.hist(pub.agent_s, bins=bins, color=BLUE, edgecolor=SURFACE, linewidth=2)
ax.grid(axis="x", visible=False)
for m in (6, 7, 8):
    ax.axvline(m * 60, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
    ax.text(m * 60 + 4, ax.get_ylim()[1] * 0.92, f"{m} min", color=INK2, fontsize=10)
ax.set_xlabel("agent time per task on our setup (seconds)")
ax.set_ylabel("tasks")
ax.set_title("LB-0.24 bundle: agent time per task, 101 local tasks", loc="left", color=INK, fontsize=12)
plt.tight_layout()
plt.show()
print(f"median {pub.agent_s.median():.0f} s, mean {pub.agent_s.mean():.0f} s, "
      f"above 6 min: {(pub.agent_s > 360).sum()}, above 7 min: {(pub.agent_s > 420).sum()}")'''))

cells.append(md("""## Projecting the hidden run

The scorer is slower than our setup, and its speed is not published. Call the slowdown **k**: one second of agent work here takes k seconds there. For a cap of C minutes, each task costs `min(k * agent_s, 60 * C)` plus sandbox setup (10 s assumed), and the total is scaled from 101 to 120 tasks. A resolved task is kept if `k * last_edit_s` is still inside the cap.

The same bytes have both finished (0.24) and run out of time on the scorer, so for this bundle the projected total must sit near 12 h. The cell below finds the k where that happens."""))

cells.append(code('''N_HIDDEN, SETUP_S, LIMIT_H = 120, 10, 12.0

def project(sub, cap_min, k):
    cap = 60 * cap_min
    hours = (np.minimum(k * sub.agent_s, cap) + SETUP_S).sum() / len(sub) * N_HIDDEN / 3600
    edit = sub.last_edit_s.fillna(0)
    kept = int((sub.resolved.astype(bool) & (k * edit <= cap)).sum())
    return hours, kept

ks = np.round(np.arange(1.0, 2.31, 0.01), 2)

def k_at_limit(sub, cap_min):
    for k in ks:
        if project(sub, cap_min, k)[0] >= LIMIT_H:
            return k
    return None

for name, sub in [("public_8min", pub), ("callsaver_8min", cs)]:
    print(name, {f"{c} min": k_at_limit(sub, c) for c in (8, 7, 6)})'''))

cells.append(code('''fig, ax = plt.subplots(figsize=(9, 4.6))
for cap in (8, 7, 6):
    hrs = [project(pub, cap, k)[0] for k in ks]
    ax.plot(ks, hrs, color=CAP_COLOR[cap], linewidth=2, label=f"{cap}-minute cap")
    ax.text(ks[-1] + 0.02, hrs[-1], f"{cap} min", color=INK2, va="center", fontsize=10)
ax.axhline(LIMIT_H, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
ax.text(1.01, LIMIT_H + 0.15, "12 h limit", color=INK2, fontsize=10)
# dots mark where each cap's total reaches 12 h
for cap, dx, dy, ha in ((8, -0.03, 0.25, "right"), (7, 0.03, -0.3, "left")):
    kc = k_at_limit(pub, cap)
    ax.plot([kc], [project(pub, cap, kc)[0]], "o", markersize=8, color=CAP_COLOR[cap],
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    ax.text(kc + dx, LIMIT_H + dy, f"k = {kc:.2f}", color=INK, fontsize=10, ha=ha, va="center")
ax.set_xlim(1.0, 2.42)
ax.set_ylim(7.8, 14.4)
ax.set_xlabel("scorer slowdown k (scorer seconds per second on our setup)")
ax.set_ylabel("projected hours for 120 tasks")
ax.set_title("LB-0.24 bundle: projected runtime by time cap (dots: where each cap hits 12 h)", loc="left", color=INK, fontsize=12)
ax.legend(frameon=False, loc="lower right")
plt.tight_layout()
plt.show()'''))

cells.append(code('''rows = []
for k in (1.45, 1.6, 1.7, 1.8):
    for cap in (8, 7, 6):
        h, kept = project(pub, cap, k)
        h2, kept2 = project(cs, cap, k)
        rows.append({"k": k, "cap (min)": cap, "hours / 120": round(h, 1),
                     "margin to 12 h (min)": round((LIMIT_H - h) * 60),
                     "resolved kept (of 33)": kept,
                     "call-saving prompt: hours": round(h2, 1)})
pd.DataFrame(rows).set_index(["k", "cap (min)"])'''))

cells.append(md("""## What to take from it

- **The 8-minute public config runs at the edge of the limit.** Near k = 1.6-1.7 its projected total is about 12 h. Small changes in scorer speed, or a hidden task set slightly slower than ours, decide whether a draw scores.
- **7 minutes is cheap insurance.** At k = 1.6-1.7 it saves 40-45 minutes and loses at most one solved task in 30: only tasks whose last edit comes after the cap are lost. The 7-minute total reaches 12 h only at k = 1.83.
- **6 minutes is safer still but costs three to five solved tasks in 30** at the same k.
- **Saving tool calls also saves time.** The call-saving prompt projects about 0.9 h shorter at every cap, which fits it finishing on the scorer with 8 minutes.
- **Raising `max_tool_calls` above 28 adds time.** At 40 calls, tasks that used to stop at 28 calls run on to the time cap instead; our 40-call / 8-minute bundle timed out.

**Applying it:** set `max_time_minutes: 7` in `eval_config.yaml`. If your prompt states the budget ("28 tool calls and 8 minutes"), change that number too, so the prompt agrees with the budget the harness appends.

## Caveats
- The hidden tasks come from other repositories. Their setup and test times differ from fastapi and rich, so treat k as a sizing knob, not a measurement of the scorer.
- `agent_s` stops at the last tool call, so the projection is slightly low. Each k shown is therefore a little optimistic.
- Each configuration has one or two draws on the LB, and two timeouts is a small sample.
"""))

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nb.metadata["language_info"] = {"name": "python"}
nbf.write(nb, f"{W}/one-bundle-three-outcomes.ipynb")
print("written", len(cells), "cells")
