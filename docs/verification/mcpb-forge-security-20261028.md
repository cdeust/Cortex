# MCPB node-forge remediation, 2026-10-28

The MCPB tool lock now resolves official node-forge 1.4.2 instead of 1.4.0. MCPB remains 2.1.2 and its declared forge range remains compatible. Only the forge version, tarball URL and integrity hash change in the lock.

## Maintainer evidence

- The original advisory still says no patched release: https://github.com/advisories/GHSA-86w9-cpqp-85rv
- Forge maintainer confirms CVE-2026-85393 fixed in 1.4.1: https://github.com/digitalbazaar/forge/issues/1149#issuecomment-6434727630
- The maintained fix uses canonical DigestInfo encoding rather than the unmerged proposed element-count patch: https://github.com/digitalbazaar/forge/pull/1152#issuecomment-6434865685
- Official advisory identifies patched 1.4.1: https://github.com/digitalbazaar/forge/security/advisories/GHSA-2g46-22mc-6gwp
- Version 1.4.2 also repairs the 1.4.1 PEM Buffer-input regression: https://github.com/digitalbazaar/forge/blob/v1.4.2/CHANGELOG.md

Registry integrity for 1.4.2, verified by npm ci:
`sha512-rRtAR5XLJ8gCKd9du4qrKAsgCG1ObGP4gLeNJMa4vYSeq4bmBMOJk5IHkrviBV0q7uoAJlVd8HEQYQSVUb4FGQ==`

## Executed checks

`node --test .github/mcpb/test-forge-security.cjs` passes both tests. The exact upstream forged-signature vector from v1.4.1/tests/unit/rsa.js fails the rejection assertion with separately installed 1.4.0, then passes with locked 1.4.2. The second test verifies a valid Node-generated RSA signature through forge and exercises Buffer PEM input. No padding-check bypass is enabled.

The real MCPB CLI validates the Cortex manifest and packs a bounded fixture containing that manifest, icon and Python entry point. CLI signing succeeds with an ephemeral test certificate. OpenSSL CMS verification of its detached signature succeeds; changing one content byte makes verification fail. This verifies signature compatibility, without establishing operating-system certificate trust or a complete release installation.

The upstream MCPB verify command reports the signed artifact unsigned. MCPB 2.1.2 calls forge PKCS7 verify, whose implementation throws "not yet implemented"; MCPB catches it and returns unsigned. This behavior is not fixed by the lock update. Sources: https://github.com/anthropics/mcpb/blob/2a788100a60db19a6b1c018fb1cf84ae85de9537/src/node/sign.ts and https://github.com/digitalbazaar/forge/blob/v1.4.2/lib/pkcs7.js

Existing upstream tracking: https://github.com/modelcontextprotocol/mcpb/issues/277 and https://github.com/modelcontextprotocol/mcpb/issues/260 . The repository moved from anthropics/mcpb to modelcontextprotocol/mcpb; old source URLs redirect. No duplicate issue was opened.

## Separate Zod alert

The installed packaging graph has a separate high Zod advisory: https://github.com/advisories/GHSA-mrhx-c7xc-m3w5 . npm audit no longer reports forge, but still reports Zod and its MCPB dependent, two high entries.

An isolated Zod 4.6.6 override produces npm audit zero and passes actual manifest validation and packing. It is not applied to the project: the upstream schema-generation pipeline converts the Zod 4 manifest to an empty JSON Schema, whereas the locked Zod 3 output has object type and required manifest fields. The unchanged upstream schemas test also fails its validation-error contract. Source: https://github.com/anthropics/mcpb/blob/2a788100a60db19a6b1c018fb1cf84ae85de9537/scripts/build-mcpb-schema.js

The full upstream Jest attempt is not green: 61 tests pass and 20 fail, with five failed suites. Several suites require absent yarn, signing has a forge Buffer typing failure, and init encounters a dependency failure on Node 26. No warning was suppressed, no test source changed, and this result does not establish full Zod compatibility.
