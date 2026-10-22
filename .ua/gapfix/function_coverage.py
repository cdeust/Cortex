import json
import collections
import sys

# source: legacy length proxy kept for comparison with the first report
SUMMARY_MIN_CHARS = 60

g = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "knowledge-graph.json"))
fn = [n for n in g["nodes"] if n["type"] in ("function", "class")]
out = collections.Counter()
inn = collections.Counter()
for e in g["edges"]:
    if e["type"] == "calls":
        out[e["source"]] += 1
        inn[e["target"]] += 1
rows = collections.defaultdict(collections.Counter)
for n in fn:
    a = n["filePath"].split("/")[0]
    r = rows[a]
    r["n"] += 1
    r["out"] += out[n["id"]] > 0
    r["in"] += inn[n["id"]] > 0
    r["any"] += (out[n["id"]] + inn[n["id"]]) > 0
    r["sum"] += len(n.get("summary", "")) >= SUMMARY_MIN_CHARS
    r["tested"] += bool(n.get("exercisedByTests"))
for a, r in sorted(rows.items(), key=lambda x: -x[1]["n"])[:4]:
    print(
        f"{a:11} n={r['n']:6}"
        f" calls-out={100 * r['out'] / r['n']:3.0f}%"
        f" called-by={100 * r['in'] / r['n']:3.0f}%"
        f" in-call-graph={100 * r['any'] / r['n']:3.0f}%"
        f" summary>=60c={100 * r['sum'] / r['n']:3.0f}%"
        f" exercised-by-tests={100 * r['tested'] / r['n']:3.0f}%"
    )
