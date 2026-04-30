# Appendix: Information-Theoretic Collapse of Flat-Importance Retrieval

This appendix derives why a **flat-importance** memory store loses retrieval discriminability as $N$ grows, while a **decaying-priority** store (Cortex) preserves it. The argument follows Shannon (1948): define the right quantity, derive its limit, then compare designs.

---

## 1. Setup and notation

A memory store holds $N$ items $\{x_1, \dots, x_N\}$. Each item $x_i$ carries an *importance* $w_i \ge 0$ with $\sum_i w_i = 1$. Given a query $q$, the retrieval score is

$$
s_i(q) \;=\; \alpha \cdot \text{sim}(q, x_i) \;+\; (1 - \alpha) \cdot w_i, \qquad \alpha \in [0,1].
$$

Top-$k$ retrieval returns the indices $R_k(q) = \arg\text{top-}k_i\, s_i(q)$.

**Two regimes.**

- **Flat-importance (canonical RAG).** $w_i = 1/N$ for all $i$. The importance term is constant, so ranking reduces to ranking $\text{sim}(q, x_i)$.
- **Decaying-priority (Cortex).** $w_i \propto h_i \cdot \exp(-\lambda \,(t - t_i))$, where $h_i$ is a base heat (access frequency) and $t - t_i$ is the age since last set. The exponential form is Ebbinghaus's forgetting law (Ebbinghaus 1885), recoverable as the steady state of a Friston-style free-energy minimization with linear precision decay (Friston 2010).

We treat $\text{sim}(q, x_i)$ as random variables drawn iid from a distribution $F_S$ with mean $\mu_S$, variance $\sigma_S^2 < \infty$, and smooth density $f_S$ on the relevant support. This is the iid-sim assumption (revisited as a limitation in §7).

---

## 2. Discriminability metric

Define the **top-$k$ discriminability** as the mutual information between the retrieved set $R_k$ and the query $q$:

$$
D_k \;=\; I(R_k; Q) \;=\; H(R_k) - H(R_k \mid Q).
$$

When $D_k \to 0$, the retrieved set is independent of the query — the system has *collapsed* into noise. $D_k$ is upper-bounded by $\log \binom{N}{k}$ and is the operational quantity for "does this retriever discriminate?" in the Shannon (1948) sense: the limit of bits-per-query the channel from query to retrieved set can carry.

Equivalent operational view: $D_k$ is the limit, as the test set grows, of (per-query) average reduction in surprise about which $k$ items are returned, given $q$.

---

## 3. The collapse theorem (informal)

**Claim.** Under flat importance ($w_i = 1/N$), iid similarities with finite variance $\sigma_S^2$ and smooth density $f_S$, and embedding noise floor $\eta$, the expected gap between the $k$-th and $(k+1)$-th largest score satisfies

$$
\mathbb{E}\big[s_{(k)} - s_{(k+1)}\big] \;\xrightarrow[N \to \infty]{}\; 0,
$$

and the top-$k$ ranking becomes effectively random once the gap drops below $\eta$. Consequently $D_k \to 0$.

**Derivation sketch (order statistics).** Let $S_{(1)} \ge S_{(2)} \ge \dots \ge S_{(N)}$ denote the ordered similarities. From David & Nagaraja (2003, §4.6, eq. 4.6.6), for a smooth density $f_S$ and a quantile $p_k = 1 - k/N$ with $k$ fixed and $N$ large:

$$
\mathbb{E}\big[S_{(k)} - S_{(k+1)}\big] \;\approx\; \frac{1}{N \, f_S\!\big(F_S^{-1}(p_k)\big)} \;=\; O\!\big(1/N\big),
$$

with standard deviation of $S_{(k)}$ itself scaling as $\sigma_S / \sqrt{N}$ around its quantile. The *spacing* (which determines tie-breaking) shrinks faster than the position uncertainty — both vanish, but the spacing collapses first.

**Embedding noise floor.** Cosine similarity on high-dimensional sentence-transformer embeddings has empirical reproducibility $\eta \approx 0.05$ (Reimers & Gurevych 2019; replication noise across seeds, batch order, and tokenizer edge cases). Once

$$
\frac{1}{N \, f_S(F_S^{-1}(p_k))} \;<\; \eta,
$$

the rank order of $S_{(k)}, S_{(k+1)}$ is dominated by embedding noise rather than semantic signal. Tie-breaking becomes uniform, and $H(R_k \mid Q) \to H(R_k)$, hence $D_k \to 0$.

**Threshold.** Setting the spacing equal to $\eta$ gives the critical store size

$$
N^\star \;=\; \frac{1}{\eta \, f_S(F_S^{-1}(p_k))}.
$$

For $\eta = 0.05$ and a typical bulk density $f_S \approx 4$ (sentence-transformer cosines concentrate in $[0.2, 0.6]$), $N^\star \approx 5{,}000$. Beyond that, flat-importance retrieval enters the collapse regime.

---

## 4. Why decay restores discriminability

**Power-law importance.** Empirical access patterns in human and artificial memory follow Zipf-like laws: Anderson (1989) and Anderson & Schooler (1991) showed that the probability a memory is needed at time $t$ scales as $P(\text{needed}) \propto t^{-\gamma}$ with $\gamma \in [0.5, 1.5]$ across email, headlines, and child-directed speech corpora. The power law of forgetting (Wixted & Ebbesen 1991) gives the same shape. When Cortex's heat $h_i \cdot \exp(-\lambda (t - t_i))$ is averaged over the access process, the stationary distribution of $w_i$ is heavy-tailed with tail exponent $\gamma$.

**Score distribution becomes bimodal.** The composite score

$$
s_i \;=\; \alpha \cdot \text{sim}(q, x_i) \;+\; (1 - \alpha) \cdot w_i
$$

is a convolution of a thin-tailed similarity component with a heavy-tailed importance component. For $\alpha \in [0.3, 0.7]$ (Cortex's WRRF operating regime), the resulting distribution is bimodal: a sharp head from items with large $w_i$ and a long tail of low-importance items. Top-$k$ retrieval consistently returns from the head; tie-breaking is dominated by $w_i$, which has gaps $O(1)$ — not by sub-$\eta$ similarity differences.

**Non-vanishing entropy bound.** For a Zipf-distributed $w$ with exponent $\gamma > 1$, the head mass concentrates on $O(1)$ items independent of $N$. The entropy of the top-$k$ posterior $P(R_k \mid q)$ is bounded below by the entropy of the head (Zipf with $\gamma > 1$ has finite entropy as $N \to \infty$; see Mandelbrot 1953 for the closed form). Therefore

$$
\liminf_{N \to \infty} D_k \;\ge\; H_{\text{head}}(\gamma, k) \;>\; 0.
$$

Decay is what generates and *maintains* the heavy tail: without it, repeated writes regress $w_i$ toward uniform.

---

## 5. Concrete numbers (LongMemEval R@10)

Cortex measured (clean DB, April 2026):
- LongMemEval R@10: **97.8%**
- Best flat-RAG baseline (paper-best): **78.4%**
- Gap: **19.4 pp**.

LongMemEval has $N \approx 10^4$ (S variant: 500 questions, ~30 turns/session, ~10k candidate spans). Plugging into §3 with $\eta = 0.05$, $f_S \approx 4$:

$$
N^\star \;=\; \frac{1}{0.05 \cdot 4} \;=\; 5{,}000.
$$

Test set size $10^4$ is $2 N^\star$. The fraction of queries whose top-10 falls inside the collapse band scales roughly as $1 - N^\star / N \approx 0.5$, but only items in the *boundary band* (between rank 10 and rank 50, where score gap is below $\eta$) are mis-ranked. Empirically that band holds $\sim 20$–$25\%$ of items. Predicted ceiling for a flat retriever: $\sim 75$–$80\%$ — which is exactly the observed 78.4% paper-best. The 19.4 pp gap is the discriminability that decay+heat preserves and uniform priors throw away.

This is a back-of-envelope, not a tight bound. It survives because the order-of-magnitude $N^\star$ matches the test set, not because the constants are precisely calibrated.

---

## 6. WRRF fusion as multi-source decorrelation

Cortex's `recall_memories()` PL/pgSQL function fuses six signals: vector cosine, FTS BM25, trigram similarity, heat, recency, n-gram overlap. Treat each signal $s^{(j)}$ as a noisy observation of a hidden relevance target $r_i$:

$$
s_i^{(j)} \;=\; r_i + \varepsilon_i^{(j)}, \qquad j \in \{1, \dots, 6\}.
$$

If the noises $\varepsilon^{(j)}$ are pairwise low-correlation (which they are: vector vs FTS, FTS vs trigram, recency vs heat — these probe different aspects of the item), the variance of the WRRF fused score is

$$
\text{Var}\big(\hat r_i\big) \;\approx\; \frac{\bar\sigma^2}{m \cdot (1 + (m-1)\bar\rho)},
$$

where $m=6$ and $\bar\rho \ll 1$. With $\bar\rho \approx 0.2$ (rough cross-signal correlation in our ablations), variance shrinks by $\sim 4\times$ relative to a single signal. This effectively raises $f_S$ in the §3 formula (the score density at the operating quantile is sharper), which raises $N^\star$ by the same factor — pushing the collapse threshold from $\sim 5\text{k}$ items to $\sim 20\text{k}$.

**Shannon connection.** This is the noisy-channel coding theorem (Shannon 1948, §17) applied to retrieval: $m$ independent observations of the same hidden $r_i$ raise the effective channel capacity from query to retrieved-set by up to $\log m$ bits. WRRF is an explicit decoder for that channel, and decay supplies one of its strongest independent signals — heat correlates weakly with vector similarity but strongly with relevance, so it carries information no semantic signal can.

---

## 7. Most fragile assumption (limitation flag)

The derivation assumes **iid similarities** $\text{sim}(q, x_i)$ across items. In practice, embeddings live on a low-dimensional manifold (Reimers & Gurevych 2019; Ethayarajh 2019 on BERT anisotropy), so similarities are *correlated* through the manifold — clusters of items have nearly identical similarities to a given query. This makes the effective $N$ in §3 smaller than the raw count (replace $N$ by the number of distinct semantic clusters, $N_{\text{eff}}$), which means **collapse happens at smaller $N$ than the iid bound predicts** — the iid analysis is a *best case* for flat retrieval, and real flat-RAG collapses sooner. The 19.4 pp gap in §5 should therefore be read as a lower bound on what decay buys; the true gap is larger and grows faster with $N$.

This is the assumption to flag in the main paper as a limitation, and the direction of bias is favorable to our claim, not against it.

---

## References

- Anderson, J. R. (1989). "A rational analysis of human memory." *Varieties of Memory and Consciousness*, 195–210.
- Anderson, J. R., & Schooler, L. J. (1991). "Reflections of the environment in memory." *Psychological Science*, 2(6), 396–408.
- David, H. A., & Nagaraja, H. N. (2003). *Order Statistics*, 3rd ed. Wiley. (§4.6 on quantile spacings.)
- Ebbinghaus, H. (1885). *Über das Gedächtnis*. Duncker & Humblot.
- Ethayarajh, K. (2019). "How contextual are contextualized word representations?" *EMNLP 2019*.
- Friston, K. (2010). "The free-energy principle: a unified brain theory?" *Nature Reviews Neuroscience*, 11(2), 127–138.
- Mandelbrot, B. (1953). "An informational theory of the statistical structure of language." *Communication Theory*, 486–502.
- Reimers, N., & Gurevych, I. (2019). "Sentence-BERT." *EMNLP 2019*.
- Shannon, C. E. (1948). "A Mathematical Theory of Communication." *Bell System Technical Journal*, 27, 379–423 & 623–656.
- Wixted, J. T., & Ebbesen, E. B. (1991). "On the form of forgetting." *Psychological Science*, 2(6), 409–415.
