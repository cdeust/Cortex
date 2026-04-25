# PII Scanner Fixture Corpus

**Created**: 2026-04-24
**Instrument**: `pii-scanner.py` + `pii-rules.json`
**Calibration target**: FPR ≤ 5% on ≥100 TN developer memory fixtures, FNR = 0% on TP set.

## Files

| File | Suite | Count | Purpose |
|------|-------|-------|---------|
| `tn-developer-memory.txt` | TN | 100 | Benign developer memory content — must PASS default scan |
| `tp-known-secrets.txt` | TP | 55 | Known-secret-shape fixtures — must BLOCK |

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

### True-Positive (TP) fixtures
Placeholder-pattern secrets that match regex shapes but contain no real credential material.
Pattern style: structurally valid shapes with obviously non-real content (e.g., `AKIAIOSFODNN7EXAMPLE`).

**Invariant**: no real credentials committed. All AWS key IDs use the `EXAMPLE` suffix pattern
documented in AWS IAM examples. All JWTs use the RFC 7519 example payload. All Stripe keys
use `_test_` or truncated live patterns. SSNs are either the widely-known test value
(`123-45-6789`) or values from the SSA's own documentation examples.

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
