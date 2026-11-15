# BEAM variance runs

`scripts/bench_variance.sh` writes the raw stdout of each run here.

The five BEAM-10M runs are about 11.7 MB each and are no longer in the tree
(issue #705: the plugin tree is the repository, so every tracked file is installed).
They stay in the history; read one with
`git show 1bfbc459:benchmarks/beam/variance/<name>`:

- `assembler_10m.txt`
- `assembler_10m_fixed.txt`
- `assembler_10m_stagefixed.txt` (BEAM-10M oracle, MRR 0.429)
- `assembler_10m_temporal.txt` (BEAM-10M temporal, MRR 0.471)
- `baseline_10m_fixed.txt` (BEAM-10M flat, MRR 0.353)

`.gitignore` keeps a new `*_10m*.txt` run out of the tree. The BEAM-100K runs
(under 0.4 MB each) stay here.
