"""Knowledge layer (article / topic / source nodes) from the ADR wiki, without
generation.

article   one per wiki/adr/**/*.md page: name = frontmatter title; summary = the first
          sentence of its `## Decision` section, else of its first preserved excerpt
          (migration pages quote the original rationale verbatim), else its first prose
          line
topic     frontmatter tags; for migration pages, the code area of `source:` (e.g. core)
source    scientific references written "Name et al. YYYY", "Name & Name YYYY" or
          "Name (YYYY)" in ADR pages or Python docstrings/comments
edges     categorized_under article->topic; cites article->code file (`source:` and
          backticked repo paths), article->article (ADR-NNNN mentions), article->source,
          code file->source; builds_on article->article when the sentence mentioning the
          other ADR says supersede/amend/extend/replace (description keeps the verb)
usage: python3 build_knowledge_layer.py <repo> <graph>
"""

import collections
import glob
import json
import os
import re
import subprocess
import sys

# source: the analysis date (2026-10-20): a later year is not a publication year
LAST_YEAR = 2026

REPO, GP = sys.argv[1:3]
g = json.load(open(GP))
g["nodes"] = [n for n in g["nodes"] if n["type"] not in ("article", "topic", "source")]
ids = {n["id"] for n in g["nodes"]}
g["edges"] = [e for e in g["edges"] if e["source"] in ids and e["target"] in ids]
by_path = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n["type"] not in ("function", "class", "table")
}
pages = json.load(open(f"{REPO}/wiki/manifest.json"))["pages"]
adr_page = {k: f"wiki/{v['path']}" for k, v in pages.items()}
REF = re.compile(
    r"\b([A-Z][a-zA-Z\-]+(?: et al\.| (?:&|and) [A-Z][a-zA-Z\-]+)),?"
    r" \(?((?:19|20)\d{2})[a-z]?\)?"
    r"|\b([A-Z][a-zA-Z\-]+) \(((?:19|20)\d{2})\)"
)
NOT_NAMES = {
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
    "Python",
    "Claude",
    "Cortex",
    "Phase",
    "Issue",
    "Release",
    "Version",
    "Section",
    "Table",
    "Figure",
    "Step",
    "Since",
    "Before",
    "After",
    "In",
    "From",
    "Until",
    "The",
    "See",
    "Measured",
    "Architecture",
    "Items",
    "Neurodynamics",
}
nodes, edges = [], []
have = set()


def edge(s, t, typ, w, desc=None, ev=None):
    if s == t or (s, t, typ) in have:
        return
    have.add((s, t, typ))
    e = {"source": s, "target": t, "type": typ, "direction": "forward", "weight": w}
    if desc:
        e["description"] = desc
    if ev:
        e["evidence"] = ev
    edges.append(e)


def first_sentence(text):
    text = re.sub(r"`{3,}\w*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.{25,400}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:300]).strip()


def refs_in(text):
    out = set()
    for m in REF.finditer(text):
        name, year = (
            (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        )
        first = name.split()[0]
        if first in NOT_NAMES or first.isupper() or int(year) > LAST_YEAR:
            continue  # initials (e.g. "AJ") are not surnames
        out.add(f"{name} {year}")
    return out


topics, sources, src_cites = {}, collections.Counter(), collections.defaultdict(set)


def topic(name):
    tid = f"topic:{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
    if tid not in topics:
        topics[tid] = {
            "id": tid,
            "type": "topic",
            "name": name,
            "summary": f"ADRs about {name}.",
            "tags": ["topic"],
            "complexity": "simple",
            "filePath": "wiki/adr",
        }
    return tid


def source(ref):
    sid = f"source:{re.sub(r'[^a-z0-9]+', '-', ref.lower()).strip('-')}"
    sources[sid] += 1
    src_cites.setdefault(sid, set())
    src_cites[sid].add(ref)
    return sid


page_files = sorted(p for p in glob.glob(f"{REPO}/wiki/adr/**/*.md", recursive=True))
num_of = {}
for p in page_files:
    rel = os.path.relpath(p, REPO)
    text = open(p, encoding="utf-8").read()
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = fm.group(1) if fm else ""
    title = re.search(r'^title:\s*"?(.+?)"?\s*$', meta, re.M) or re.search(
        r"^# (.+)$", text, re.M
    )
    title = title.group(1) if title else os.path.basename(rel)
    num = re.search(r"ADR-(\d{4})", title) or re.match(
        r"(\d{4})-", os.path.basename(rel)
    )
    key = f"ADR-{num.group(1)}" if num else None
    aid = f"article:{key or rel}"
    num_of[aid] = key
    body = text[fm.end() :] if fm else text
    dec = re.search(r"^## Decision\s*\n(.+?)(?=^## |\Z)", body, re.S | re.M)
    exc = re.search(r"^````text\n(.+?)^````", body, re.S | re.M)
    prose = next(
        (
            ln
            for ln in body.splitlines()
            if ln.strip() and not ln.startswith(("#", "`", "|", "-"))
        ),
        title,
    )
    summary = first_sentence(dec.group(1) if dec else exc.group(1) if exc else prose)
    status = (re.search(r"^status:\s*(\S+)", meta, re.M) or [None, "unknown"])[1]
    tags = [
        t.strip()
        for t in (re.search(r"^tags:\s*\[(.*)\]", meta, re.M) or [None, ""])[1].split(
            ","
        )
        if t.strip()
    ]
    srcfile = (re.search(r"^source:\s*(\S+)", meta, re.M) or [None, None])[1]
    nodes.append(
        {
            "id": aid,
            "type": "article",
            "name": title,
            "summary": summary,
            "filePath": rel,
            "tags": ["adr", f"status:{status}"] + tags,
            "complexity": "moderate",
            "knowledgeMeta": {
                "adr": key,
                "status": status,
                "kind": "migration" if "/migration/" in rel else "decision",
            },
        }
    )
    for t in tags:
        edge(aid, topic(t), "categorized_under", 0.5)
    if srcfile:
        area = (
            srcfile.split("/")[1]
            if srcfile.startswith("mcp_server/") and srcfile.count("/") > 1
            else srcfile.split("/")[0]
        )
        edge(aid, topic(f"code: {area}"), "categorized_under", 0.5)
        if srcfile in by_path:
            edge(
                aid,
                by_path[srcfile],
                "cites",
                0.9,
                "rationale of this file",
                f"{rel} frontmatter source:",
            )
    for pth in set(
        re.findall(r"`([A-Za-z0-9_./\-]+\.(?:py|md|json|toml|sh|yml|yaml|sql))`", body)
    ):
        if pth in by_path and pth != srcfile:
            edge(aid, by_path[pth], "cites", 0.6, None, f"{rel} mentions `{pth}`")
    for sent in re.split(r"(?<=[.!?])\s+|\n", body):
        for other in set(re.findall(r"ADR-(\d{4})", sent)):
            okey = f"ADR-{other}"
            if okey == key or okey not in adr_page:
                continue
            verb = re.search(
                r"\b(supersed\w*|amend\w*|extend\w*|replac\w*)\b", sent, re.I
            )
            target = f"article:{okey}"
            if verb:
                edge(
                    aid,
                    target,
                    "builds_on",
                    0.8,
                    verb.group(1).lower(),
                    f"{rel}: {sent.strip()[:160]}",
                )
            else:
                edge(aid, target, "cites", 0.5)
    for r in refs_in(body):
        edge(aid, source(r), "cites", 0.7)

# scientific references cited from code (docstrings and comments)
for p in subprocess.run(
    ["git", "-C", REPO, "ls-files", "mcp_server/*.py"], capture_output=True, text=True
).stdout.split():
    if p not in by_path:
        continue
    for r in refs_in(open(f"{REPO}/{p}", encoding="utf-8", errors="ignore").read()):
        edge(by_path[p], source(r), "cites", 0.7)

article_ids = {n["id"] for n in nodes}
edges = [
    e
    for e in edges
    if not e["target"].startswith("article:") or e["target"] in article_ids
]
for sid, refs in src_cites.items():
    cited_by = sum(1 for e in edges if e["target"] == sid)
    nodes.append(
        {
            "id": sid,
            "type": "source",
            "name": sorted(refs)[0],
            "summary": (
                f"Scientific reference {sorted(refs)[0]}, "
                f"cited by {cited_by} ADR page(s) or module(s)."
            ),
            "tags": ["reference"],
            "complexity": "simple",
            "filePath": "wiki/adr",
        }
    )
nodes += topics.values()
g["nodes"] += nodes
g["edges"] += edges
json.dump(g, open(GP, "w"), indent=2, ensure_ascii=False)
c = collections.Counter(n["type"] for n in nodes)
ce = collections.Counter(e["type"] for e in edges)
print(dict(c), dict(ce))
print(
    "most cited references:",
    [
        (n["name"], sum(1 for e in edges if e["target"] == n["id"]))
        for n in sorted(
            (n for n in nodes if n["type"] == "source"),
            key=lambda n: -sum(1 for e in edges if e["target"] == n["id"]),
        )[:15]
    ],
)
