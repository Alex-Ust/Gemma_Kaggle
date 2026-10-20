"""Summarize next-action probe results per variant and kind.

  probe_report.py runs/probe-p1/output/probe.jsonl [--show v06:late]
"""
import argparse
import collections
import json
import re
import statistics

BT = re.compile(r"`")


def first_call(r):
    resp = r.get("response") or []
    for x in resp:
        if x["calls"]:
            return x["calls"][0], x
    return None, (resp[0] if resp else {})


def classify(r):
    c, x = first_call(r)
    if r.get("error"):
        return "error"
    if c is None:
        return "no_call"
    name, args = c["name"], c["args"]
    if any(isinstance(v, str) and BT.search(v) for v in args.values()):
        return f"{name}:CORRUPT"
    if name == "run_skill_script":
        if not args.get("skill_name") or not args.get("file_path"):
            return "skill:MISSING_ARG"
        sk = args["skill_name"]
        q = args.get("args")
        has_query = (isinstance(q, dict) and q.get("query")) or (isinstance(q, list) and q) or args.get("positional_args")
        if sk == "locate" and not has_query:
            return "locate:NO_QUERY"
        return f"skill:{sk}"
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--show", default="", help="variant:kind to print sample thoughts")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.path)]
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["kind"], r["variant"])].append(r)
    for (kind, var), rs in sorted(groups.items()):
        cls = collections.Counter(classify(r) for r in rs)
        toks = [x.get("completion_tokens") or 0 for r in rs for x in (r.get("response") or [])[:1]]
        lat = [r.get("latency", 0) for r in rs]
        thoughts = [(first_call(r)[1] or {}).get("thought", "") for r in rs]
        counted = sum(bool(re.match(r"\s*Call \d+", t)) for t in thoughts)
        code = sum("```" in t for t in thoughts)
        edit = cls.get("edit_file", 0) + cls.get("write_file", 0)
        esc = 0
        for r in rs:
            c, _ = first_call(r)
            if c and c["name"] == "edit_file":
                o = c["args"].get("old_string") or ""
                esc += isinstance(o, str) and ("\\n" in o or '\\"' in o)
        print(f"== {kind:5s} {var:6s} n={len(rs):3d}  edit {edit:3d} ({edit / len(rs):.0%})  "
              f"tokens med {statistics.median(toks) if toks else 0:.0f} mean {statistics.mean(toks) if toks else 0:.0f}  "
              f"latency med {statistics.median(lat):.1f}s  'Call N' {counted}  code-in-thought {code}  "
              f"edits with literal escapes {esc}")
        print("   ", dict(cls.most_common()))
    # paired view: same point, two variants
    by_point = collections.defaultdict(dict)
    for r in rows:
        if r["sample"] == 0:
            by_point[(r["iid"], r["kind"], r["cut"])][r["variant"]] = classify(r)
    vs = sorted({r["variant"] for r in rows})
    E = ("edit_file", "write_file")
    for b0 in vs[1:]:
        a0 = vs[0]
        for kind in ("plan", "late"):
            pairs = [(v[a0], v[b0]) for k, v in by_point.items() if k[1] == kind and a0 in v and b0 in v]
            ea = sum(x in E for x, _ in pairs)
            eb = sum(y in E for _, y in pairs)
            only_b = sum(x not in E and y in E for x, y in pairs)
            only_a = sum(y not in E and x in E for x, y in pairs)
            print(f"paired {kind}: {a0} edits {ea}/{len(pairs)}, {b0} edits {eb}/{len(pairs)}  "
                  f"(only {b0}: {only_b}, only {a0}: {only_a})")
    if a.show:
        var, kind = a.show.split(":")
        for r in rows:
            if r["variant"] == var and r["kind"] == kind:
                c, x = first_call(r)
                print(f"\n--- {r['iid']} cut {r['cut']} -> {classify(r)}")
                print("THOUGHT:", (x.get("thought") or "")[:700].replace("\n", " "))
                if c:
                    print("CALL:", c["name"], json.dumps(c["args"])[:300])


if __name__ == "__main__":
    main()
