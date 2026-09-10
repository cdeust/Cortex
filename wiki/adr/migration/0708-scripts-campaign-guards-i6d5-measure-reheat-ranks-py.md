# ADR-0708: scripts/campaign_guards/i6d5_measure_reheat_ranks.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/campaign_guards/i6d5_measure_reheat_ranks.py`; original SHA-256 `beea5bc1e7dfc6d49051df635cfa58a11f20bc3e90943fb2b5d7a88c77e066b1`.

## Original comment, lines 21–22

````text
# repartis sur toute la distribution eh_avant (min, p25, median, p75, max
# parmi les 544 lignes reheated de la mesure de reference).
````

## Original comment, lines 48–49

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 51–51

````text
# source: structural — the guard reports a top-10 (R@10) tally
````

