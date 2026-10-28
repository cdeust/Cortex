# Preserve every authorized native review recovery path

Source: canonical PR205 commit 6cb9b18d5068fb1ecf510899b52527fae786b163; helper SHA256: 53acd5512f5b49c3ce42fb36b496a9e5c09ca74afa9604878a2d4c2fbb07d58e.

The previous discovery filter could reject completed unresolved proof when a successful Pipeline still had a successful merge pending review placeholder. The full authenticated resumption policy authorizes a review-job refresh in this state. The seven-line correction lets that candidate reach the existing policy. It grants no new rerun authority.

The real discovery and real policy are tested across green wait, readiness failure and merge failure, each with clean and unresolved proof. A genuine failed merge with unresolved proof remains excluded without REST reads. Every fixture uses realistic successful/skipped placeholder steps; no rerun POST or model is issued.

Consumer validation: 331 tests plus 405 subtests pass in pytest prepend and importlib; 331 unittest tests pass. Ruff/format, actual Cortex craftsmanship and whitespace checks pass. The test adapter retains the existing Cortex nullable-proof fixture and namespace. Production/workflow/platform configuration is unchanged. Hosted CI and both automatic bot reviews validate the published head before completion.
