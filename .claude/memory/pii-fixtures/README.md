# PII Scanner Fixture Corpus

**Created**: 2026-04-24
**Instrument**: `pii-scanner.py` + `pii-rules.json`
**Calibration target**: FPR ≤ 5% on ≥100 TN developer memory fixtures, FNR = 0% on TP set.

## Files

| File | Suite | Count | Purpose |
|------|-------|-------|---------|
| `tn-developer-memory.txt` | TN | 100 | Benign developer memory content — must PASS default scan |

> **Removed 2026-04-25** — `tp-known-secrets.txt` (the TP corpus) was deleted from the
> working tree AND stripped from git history. Plain-text fixtures matching real
> credential regex shapes (AWS / Stripe / Slack / GitHub PAT / etc.) trigger GitHub's
> secret-scanning push protection on every push, even when scrubbed to `EXAMPLE`-padded
> synthetic values — the scanner is regex-based and cannot distinguish synthetic from
> real. There is **no safe way** to keep a TP corpus as a tracked plain-text file.
> Re-introduction (if ever needed) requires a generator-at-runtime fixture model:
> assemble fragments at test time into a gitignored path so adjacent regex-matching
> tokens never enter the git tree.

## Provenance

### True-Negative (TN) fixtures
Synthesized from actual content patterns in this repository:
- `agents/*.md` — agent procedure language, ADR entries, benchmark results
- `memory/ADR-001-scope-coverage.md`, `memory/contract.md`, `memory/concurrency-audit.md`
- `memory/pii-instrument-spec.md` — instrument spec language
- Developer memory style: code decisions, architecture notes, bug-fix rationale, research observations

Content deliberately includes patterns that look superficially like PII but are NOT:
- `555-01xx` phone numbers (NANPA-reserved fictional range; ATIS-0300114)
- `123-45-6789` SSN (universally known invalid test value; SSA Publication No. 05-10002)
- `000-xx-xxxx`, `666-xx-xxxx`, `9xx-xx-xxxx` SSNs (unassigned areas per SSA)
- Placeholder strings `YOUR_API_KEY_HERE`, `<INSERT_TOKEN>` (entropy ~1.5–2.5 bits/char)
- Variable name references (`AWS_ACCESS_KEY_ID` the name, not a value)
- Regex patterns in documentation (e.g. `AKIA[A-Z0-9]{16}`)
- URLs containing `@` (email-like but not emails)
- Git SHAs, UUIDs, version strings

### True-Positive (TP) fixtures — REMOVED

The TP corpus has been removed from this repository (working tree + history). Any
re-introduction must use a generator-at-runtime model where regex-matching shapes
are assembled from fragments at test time. **Do not commit plain-text TP fixtures**
— GitHub secret-scanning will block every push regardless of value synthesisticity.

## Sources

- AWS IAM key format: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html
- GitHub PAT format: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github
- JWT RFC 7519: https://www.rfc-editor.org/rfc/rfc7519
- RFC 7468 (PEM): https://www.rfc-editor.org/rfc/rfc7468
- Slack token types: https://api.slack.com/authentication/token-types
- Stripe keys: https://stripe.com/docs/keys
- GCP service account: https://cloud.google.com/iam/docs/creating-managing-service-account-keys
- Azure connection strings: https://learn.microsoft.com/en-us/azure/storage/common/storage-configure-connection-string
- detect-secrets v1.4 (IBM, MIT): AWSKeyDetector pattern
- TruffleHog v2/v3 entropy threshold: Cornwell, T. (2019). trufflesecurity/trufflehog design doc
- Shannon entropy: Shannon, C.E. (1948). Bell System Technical Journal 27(3), 379-423
- NANPA reserved ranges: ATIS-0300114; https://www.nanpa.com
- SSA SSN assignment rules: SSA Publication No. 05-10002
- NANPA area code structure: ITU-T E.164 / E.123
