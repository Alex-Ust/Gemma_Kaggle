"""Per-task view of a two-agent (coder + analyst agent_tool) run.

  team_report.py runs/v08-analyst-smoke16 [--vs runs/v05-skills-sound]
"""
import argparse
import glob
import json
import os


def summarize(trace):
    seq = []
    reports = []
    for s in trace["steps"]:
        if s["source"] != "agent":
            continue
        author = (s.get("extra") or {}).get("author", "?")
        for tc in s.get("tool_calls") or []:
            name = tc["function_name"]
            obs = (s.get("observation") or {}).get("content", "")
            tag = {"analyst": "A", "edit_file": "e", "write_file": "w", "submit_patch": "S", "read_file": "r",
                   "run_command": "c", "get_status": "g"}.get(name, "?")
            if name == "run_skill_script":
                fp = str((tc.get("arguments") or {}).get("file_path", ""))
                tag = "L" if "locate" in fp else ("K" if "check" in fp else "X")
                if "INVALID_ARGUMENTS" in obs or "not found" in obs:
                    tag = "X"
            if name in ("edit_file", "write_file") and '"status": "ok"' not in obs:
                tag = tag.upper()  # failed edit
            seq.append(tag if author != "analyst" else tag.lower() if tag not in "LX" else tag)
            if name == "analyst":
                reports.append(obs)
    return "".join(seq), reports


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--vs", default=None)
    ap.add_argument("--show-reports", action="store_true")
    a = ap.parse_args()
    rows = {json.loads(l)["instance_id"]: json.loads(l)
            for l in open(os.path.join(a.run, "output/results/task_results.jsonl"))}
    base = {}
    if a.vs:
        base = {json.loads(l)["instance_id"]: json.loads(l)
                for l in open(os.path.join(a.vs, "output/results/task_results.jsonl"))}
    print("legend: A analyst call (coder), lower-case = analyst's own calls, L locate, K check, X broken skill call,"
          " e/E edit ok/failed, S submit")
    for f in sorted(glob.glob(os.path.join(a.run, "output/results/traces/*.json"))):
        iid = os.path.basename(f)[6:-5]
        r = rows.get(iid, {})
        seq, reports = summarize(json.load(open(f)))
        b = base.get(iid)
        btxt = "" if b is None else f" base={'R' if b['resolved'] else ('-' if b['agent_patch_size'] == 0 else 'x')}"
        res = "R" if r.get("resolved") else ("-" if r.get("agent_patch_size", 0) == 0 else "x")
        fmt = sum("CURRENT" in x and "NEW" in x for x in reports)
        print(f"{iid:16s} {res}{btxt} {r.get('duration_seconds', 0):4.0f}s calls={r.get('tool_calls')} "
              f"reports={len(reports)} formatted={fmt}  {seq}")
        if a.show_reports:
            for x in reports[:1]:
                print("     REPORT:", x[:600].replace("\\n", "\n     "))
    n = len(rows)
    solved = sum(r["resolved"] for r in rows.values())
    print(f"resolved {solved}/{n}, empty {sum(r['agent_patch_size'] == 0 for r in rows.values())}")
    if base:
        common = [i for i in rows if i in base]
        print(f"base on same tasks: resolved {sum(base[i]['resolved'] for i in common)}/{len(common)}, "
              f"empty {sum(base[i]['agent_patch_size'] == 0 for i in common)}")


if __name__ == "__main__":
    main()
