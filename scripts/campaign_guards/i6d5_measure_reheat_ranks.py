"""G-rangs INC6.6 (I6-D5): rang avant/apres re-heat, protocole exact de
l'audit (measure_rank.py) -- requete = premiere ligne significative
(~90 chars), embedding MiniLM production, recall_memories() non scope
(p_domain=NULL), intent 'general' (w_vector=1.0, w_fts=0.5, w_heat=0.3,
w_ngram=0.3, w_recency=0.0), min_heat=0.01, p_max_results=60.

"Avant": heat_base est temporairement remis a heat_base_before dans une
transaction annulee (ROLLBACK) -- jamais persiste, mesure seulement.
"Apres": etat reel courant de la DB (deja recalibre par la campagne).
"""

import sys

sys.path.insert(0, "/private/tmp/wt-reheat")

import psycopg
from sentence_transformers import SentenceTransformer

# 5 echantillons deliberes, choisis dans le journal du dry-run baseline
# (docs/campaigns/i6d5_memory_reheat_dry-run_20260710T151019Z.json),  # noqa: ERA001
# repartis sur toute la distribution eh_avant (min, p25, median, p75, max
# parmi les 544 lignes reheated de la mesure de reference).
SAMPLES = [
    (4198018, 0.033882845, "min (eh~0.015)"),
    (4196447, 0.081548996, "p25 (eh~0.10)"),
    (4253211, 0.054313455, "median (eh~0.10)"),
    (4201644, 0.3131332, "p75 (eh~0.159)"),
    (4196608, 0.25938746, "max/near-cliff (eh~0.25)"),
]

model = SentenceTransformer("all-MiniLM-L6-v2")


def _rank(cur, tid, query):
    emb = model.encode(query).tolist()
    vec = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
    cur.execute(
        "SELECT memory_id FROM recall_memories("
        " %s, %s::vector(384), 'general', NULL, NULL, NULL,"
        " 0.01::real, 60, 60,"
        " 1.0::real, 0.5::real, 0.3::real, 0.3::real, 0.0::real, TRUE)",
        (query, vec),
    )
    ids = [r[0] for r in cur.fetchall()]
    return ids.index(tid) + 1 if tid in ids else None


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_FIRST_LINE_CHARS = 20
# source: structural — the guard reports a top-10 (R@10) tally
_TOP_RANK_CUTOFF = 10

rows_out = []
conn = psycopg.connect("postgresql://cdeust@127.0.0.1:5432/cortex")
with conn.cursor() as cur:
    for tid, hb_before, label in SAMPLES:
        cur.execute("SELECT content FROM memories WHERE id=%s", (tid,))
        (content,) = cur.fetchone()
        first_line = next(
            (
                ln.strip()
                for ln in content.splitlines()
                if len(ln.strip()) > _MIN_FIRST_LINE_CHARS
            ),
            content[:90],
        )
        query = first_line[:90]

        # AFTER: current (already-recalibrated) DB state, no writes.
        rank_after = _rank(cur, tid, query)

        # BEFORE: temporarily roll heat_base back inside a transaction
        # that is always rolled back -- never persisted.
        cur.execute("BEGIN")
        cur.execute(
            "UPDATE memories SET heat_base = %s WHERE id = %s", (hb_before, tid)
        )
        rank_before = _rank(cur, tid, query)
        cur.execute("ROLLBACK")

        rows_out.append((tid, label, hb_before, rank_before, rank_after, query[:60]))

conn.close()

print(
    f"{'id':>8} {'label':<26} {'hb_avant':>9} "
    f"{'rang_avant':>11} {'rang_apres':>11}  requete"
)
for tid, label, hb, rb, ra, q in rows_out:
    rb_s = str(rb) if rb else ">60"
    ra_s = str(ra) if ra else ">60"
    print(f"{tid:>8} {label:<26} {hb:>9.4f} {rb_s:>11} {ra_s:>11}  {q}")

n_improved = sum(1 for _, _, _, rb, ra, _ in rows_out if (ra or 999) <= (rb or 999))
n_top10_after = sum(
    1 for *_, ra, _ in rows_out if ra is not None and ra <= _TOP_RANK_CUTOFF
)
print(f"\nAmeliore ou stable: {n_improved}/{len(rows_out)}")
print(f"Top-10 apres: {n_top10_after}/{len(rows_out)}")
