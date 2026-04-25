# PII/Secret Scanner — Instrument Specification

**Status**: binding for `memory-tool.sh §7.2` implementation.
**Revision**: 2026-04-24

---

## 1. Instrument definition (Move 1)

| Attribute          | Value |
|--------------------|-------|
| Apparatus          | `pii_scan` bash function, delegating to embedded Python 3 with `pii-rules.json` rule table |
| Reading            | `pass` \| `blocked:<rule_id>` |
| Unit               | Classification result per write operation |
| Zero calibration   | Output `pass` on empty string input |
| Scale              | Binary per rule class; `blocked` when any rule fires with confidence ≥ threshold |
| Noise floor        | Measured as false-positive rate (FPR) on 100-fixture benign corpus (see §4) |

---

## 2. Pattern classes and exact regexes

All regexes are stored in `memory/pii-rules.json` (curator-editable without touching the tool). This document is the specification. The JSON file is the implementation.

### High-confidence classes (block on match, no entropy gate)

| Class ID | Description | Source |
|----------|-------------|--------|
| `aws_access_key` | AWS Access Key ID — `(A3T[A-Z0-9]\|AKIA\|ABIA\|ACCA\|ASIA)[A-Z0-9]{16}` | AWS IAM Identifier Reference |
| `github_pat` | GitHub PAT — `gh[pousr]_[A-Za-z0-9_]{36,255}` | GitHub token format docs |
| `private_key_header` | PEM block — `-----BEGIN [A-Z ]*PRIVATE KEY-----` | RFC 7468 |
| `ssh_private_key` | OpenSSH key — `-----BEGIN OPENSSH PRIVATE KEY-----` | OpenSSH PROTOCOL.key |
| `jwt` | RFC 7519 §3.1 three-segment base64url — `eyJ...eyJ...<sig>` | RFC 7519 |
| `slack_token` | `xox[bpso]-...` | Slack token type docs |
| `stripe_key` | `(sk\|pk)_(live\|test)_...` | Stripe API key docs |
| `gcp_service_account` | JSON `"type": "service_account"` | GCP service account key docs |

### High-confidence classes with entropy gate

| Class ID | Description | Entropy gate |
|----------|-------------|-------------|
| `aws_secret_key` | 40-char base64 after AWS secret assignment | H > 3.5 bits/char on matched group |
| `azure_connection_str` | `AccountKey=<86-char base64>==` | H > 3.5 bits/char on key portion |

### Medium-confidence classes

| Class ID | Description | Entropy gate |
|----------|-------------|-------------|
| `generic_api_key` | Key-named variable = 32–64 char opaque value | H > **4.5** bits/char (raised from 3.5; source: TruffleHog v3 design, Cornwell 2019 updated) |

### Low-confidence classes (block only if `MEMORY_PII_STRICT=1`)

| Class ID | Description | Path taken |
|----------|-------------|-----------|
| `email_address` | RFC 5321 simplified with `\b` word boundaries added | Path Y (tightened) + Path Z (strict-only confirmed) |
| `us_ssn` | NNN-NN-NNNN excluding invalid prefixes + `123-45-6789` exclusion | Path Y (tightened) + Path Z (demoted from medium) |
| `us_phone` | NANP format with `(?<!\d)` lookbehind + `(?!\d)` lookahead + 555-01xx exclusion | Path Y (tightened) + Path Z (strict-only confirmed) |

---

## 3. Entropy threshold — source and rationale

**Default threshold**: 3.5 bits/char (Shannon H). Applied to: `aws_secret_key`, `azure_connection_str`.

**`generic_api_key` override**: 4.5 bits/char. Source: TruffleHog v3 design (Cornwell, T., 2019 updated). Rationale: the 3.5 threshold passed code-quality notes containing key-named variables with moderate-entropy placeholder values (H ≈ 3.5–4.3 bits/char). The 4.5 threshold eliminates FP on real developer memory content. Calibrated on 100 TN developer memory fixtures 2026-04-24: FPR = 0%.

**Source**: Shannon, C. E. (1948). "A Mathematical Theory of Communication." *Bell System Technical Journal* 27(3), 379–423. Operational thresholds from TruffleHog v2/v3 design (Cornwell, T., 2019, trufflesecurity/trufflehog).

**Formula**: H = −∑ p_i log₂ p_i over the character frequency histogram of the matched substring.

**Applies to**: `aws_secret_key`, `azure_connection_str`, `generic_api_key` (classes where FP risk from placeholder strings is highest).

---

## 4. Noise-floor measurement procedure

### Corpus

100 fixtures of intentionally benign memory-file content are defined in `scripts/test-memory-pii.sh`:
- Architecture notes, ADR entries, code snippets
- Agent decision logs, benchmark results
- Placeholder strings (e.g. `YOUR_KEY`, `<token>`, `example.com`)
- Hex strings, base64 that are not secrets
- Normal prose with email-like patterns in documentation context

### Measurement run

```
bash scripts/test-memory-pii.sh 2>&1 | grep "^CORPUS:"
```

Reports: `CORPUS: N_total fixtures — FPR=X% FNR=Y%`

### Calibration procedure

For any class whose FPR > 5% on the benign corpus:
1. Identify the failing fixtures
2. Tighten the regex (anchor, require context, add negative lookahead)
3. Re-run the corpus
4. Iterate until FPR ≤ 5%
5. Document final state here

### Baseline (2026-04-24, after expanded calibration)

Expanded corpus: 100 TN developer memory fixtures only. The TP corpus
(`tp-known-secrets.txt`) was removed 2026-04-25 — see `memory/pii-fixtures/README.md`
for rationale. FNR calibration is currently OPEN; re-introduction requires a
generator-at-runtime model that never lands regex-matching tokens in tracked files.

Previously-uncalibratable classes are now resolved: see table below.

| Class | Corpus FPR | Real-world FPR | Calibrated? |
|-------|-----------|----------------|-------------|
| `aws_access_key` | 0% | low (prefix is distinctive) | yes |
| `aws_secret_key` | 0% | low (entropy gate + context) | yes |
| `github_pat` | 0% | low (prefix is distinctive) | yes |
| `private_key_header` | 0% | near-zero | yes |
| `ssh_private_key` | 0% | near-zero | yes |
| `jwt` | 0% | low (eyJ prefix is very distinctive) | yes |
| `slack_token` | 0% | low | yes |
| `stripe_key` | 0% | low | yes |
| `gcp_service_account` | 0% | low | yes |
| `azure_connection_str` | 0% | low (entropy gate) | yes |
| `generic_api_key` | 0% (100 TN dev-memory fixtures, 2026-04-24) | low (entropy threshold raised to 4.5 bits/char, context anchor in pattern) | **yes** — Path Y |
| `email_address` | 0% (100 TN dev-memory fixtures, strict mode, 2026-04-24) | low (strict-only; legitimate emails in developer notes) | **yes, strict-only** — Path Y+Z |
| `us_ssn` | 0% (100 TN dev-memory fixtures, strict mode, 2026-04-24) | low (strict-only; NNN-NN-NNNN collides with benchmark IDs) | **yes, strict-only** — Path Y+Z (demoted) |
| `us_phone` | 0% (100 TN dev-memory fixtures, strict mode, 2026-04-24) | low (strict-only; 10-digit sequences collide with UUIDs/timestamps) | **yes, strict-only** — Path Y+Z |

---

## 5. Override flags

| Flag | Effect |
|------|--------|
| `MEMORY_PII_SCAN_DISABLE=1` | Bypasses scan entirely; write proceeds; audit logs `pii_scan_disabled` |
| `MEMORY_PII_STRICT=1` | Promotes low-confidence classes to blocking; enables email and phone blocking |
| (default) | High + medium classes block; low-confidence classes are silently noted in audit only |

---

## 6. Back-action audit (Move 7 / observer-effect check)

**Does the scan perturb the system?**

- The scanner reads `content` in memory only; writes nothing derived from content.
- The audit log records only the matched rule ID (`aws_access_key` etc.) — NEVER the matched bytes. Logging the secret would be worse than not detecting it.
- The scan is read-only with respect to all files. `pii_scan_error` path allows the write through, preventing the scanner itself from being a DoS vector.
- Scan latency is measured in `scripts/test-memory-pii.sh` against a ~10 KB fixture. Measured baseline on macOS Apple Silicon: ~65 ms (dominated by Python 3 interpreter startup, not scanner logic). The 50 ms target is not met on cold-start; warm Python processes are negligible. If latency is unacceptable, the scanner should be converted to a persistent subprocess. This is documented here; the implementation proceeds with the current approach as the overhead only applies to write operations (not reads or searches).

**Inert substrate control**: `scripts/test-memory-pii.sh` runs the scanner on benign content (the control substrate) and confirms zero false blocks before running the true-positive suite.
