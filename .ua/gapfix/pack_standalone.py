"""Pack the Understand-Anything dashboard build + this graph into ONE offline HTML file.

Opened from disk (file://) a browser refuses module chunks, fetch() of JSON and
workers, so: the single-chunk build (inline worker) and its CSS are inlined, the
graph files are embedded as JSON script blocks, and fetch() is answered from them.
Impact overlays (diff-overlay-<label>.json) are embedded too; a selector reloads the
page with ?impact=<label>, and the dashboard's own Diff mode shows changed (red) and
affected nodes for that change set.

usage: python3 pack_standalone.py <dashboard build dir> <.ua dir> <overlays dir>
<out.html>
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

build, ua, overlays, out = sys.argv[1:5]
html = open(f"{build}/index.html").read()
js = open(glob.glob(f"{build}/assets/*.js")[0]).read().replace("</script", "<\\/script")
css = open(glob.glob(f"{build}/assets/*.css")[0]).read()


def compact(path):
    return json.dumps(
        json.load(open(path)), separators=(",", ":"), ensure_ascii=False
    ).replace("</", "<\\/")


files = {
    n: compact(f"{ua}/{n}")
    for n in ("knowledge-graph.json", "meta.json", "config.json", "domain-graph.json")
}
labels = []
for p in sorted(glob.glob(f"{overlays}/diff-overlay-*.json")):
    d = json.load(open(p))
    label = d["label"]
    labels.append((label, d["summary"], d.get("entryPoints", [])))
    files[f"diff-overlay-{label}.json"] = compact(p)
blobs = "".join(
    f'<script type="application/json" data-ua-file="{n}">{v}</script>\n'
    for n, v in files.items()
)
options = "".join(
    f'<option value="{label}">{label.upper()} — {s["changed"]} changed, '
    f"{s['affected']} affected, {s['tests']} tests"
    f"{', entry: ' + ', '.join(e[:4]) if e else ''}</option>"
    for label, s, e in labels
)

shim = (
    "<script>"
    + open(f"{HERE}/standalone_shim.js", encoding="utf-8").read()
    + "</script>"
).replace("__OPTIONS__", options)

html = re.sub(r'<script type="module" crossorigin src="[^"]+"></script>', "", html)
html = re.sub(r'<link rel="stylesheet" crossorigin href="[^"]+">', "", html)
html = re.sub(r'<link rel="icon"[^>]*>', "", html)
html = html.replace(
    "<title>Understand Anything</title>", "<title>Cortex knowledge graph</title>"
)
html = html.replace("</head>", f"<style>{css}</style>\n</head>")
html = html.replace(
    "</body>", blobs + shim + f'\n<script type="module">{js}</script>\n</body>'
)
open(out, "w").write(html)
print(out, len(html) // 1_000_000, "MB;", len(labels), "impact views")
