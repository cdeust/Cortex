# Python dependency remediation, 2026-10-28

Base: main631b66f0c1537326335fff7a72b357d4b5499c4f. Scope: pyproject.toml and uv.lock, preserving all platform forks.

## Changes

- filelock3.32.5 becomes4.2.4. The advisory-backed floor4.2.1 fixes Dependabot315,316,317. Sources: https://github.com/advisories/GHSA-v4x8-3wr5-3wq8, https://github.com/advisories/GHSA-567q-5qvw-pf92, https://github.com/advisories/GHSA-9vhv-jxww-xfm5.
- Modern setuptools84.0.0 becomes84.2.1, with floor84.1.0 outside the existing pre-macOS14 Apple Silicon fork. Sources: https://github.com/advisories/GHSA-xmj3-9gf7-h52w and https://github.com/advisories/GHSA-h35f-9h28-mq5c.
- Modern transformers5.16.1 becomes5.21.0, with the same modern platform lower bound. Its required huggingface-hub fork becomes1.33.0. Intel retains transformers4.57.6 and huggingface-hub0.36.2.
- Modern cryptography50.0.1 becomes50.0.2. Its wheels bundle OpenSSL4.0.3, which includes the September29 security fixes. Intel retains48.0.1. Sources: https://cryptography.io/en/latest/changelog/#v50-0-2 and https://openssl-library.org/news/vulnerabilities-4.0/.
- setuptools81.0.0 remains required by torch2.11.0 on the older Apple Silicon tier. PyPI metadata explicitly requires setuptools<82: https://pypi.org/pypi/torch/2.11.0/json. The two setuptools alerts therefore remain open. No support tier is removed and no dependency requirement is overridden.

## Verification

The resolver used uv0.13.5 to preserve the existing revision5 lock format. Only filelock and the modern setuptools, transformers, huggingface-hub and cryptography package versions changed. All other package versions and platform forks remain. The launcher-pinned uv0.11.3 subsequently passed `uv lock --python /opt/homebrew/bin/python3.14 --check`.

The shared venv failed its existing version-parity guard. It was left unchanged. A private `.security-venv` reused existing packages in read-only mode and installed exact lock versions for the reported drifts. No torch wheel or model was installed.

Final command after all dependency edits: `UV_PYTHON=/opt/homebrew/bin/python3.14 .security-venv/bin/python -m pytest -q --tb=short tests_py/scripts/test_launcher_platform_coverage.py tests_py/scripts/test_uv_lock_single_source.py tests_py/scripts/test_codex_dependency_platform.py`: **70 passed in4.34s**. This covers hash-pinned dry-run resolutions for Linux x86/ARM, Windows, Intel Mac and older Apple Silicon across Python3.11-3.14, plus explicit macOS12/13/14 tiers. It preserves the existing failures where upstream publishes no wheel.

Actual huggingface-hub0.36.2 and1.33.0 consumers were tested. Their `WeakFileLock` context managers each excluded a second process while held, then permitted acquisition after release, using filelock4.2.4. Both passed without loading a model.

The real installed `GenerationMixin.load_custom_generate` method was invoked with `trust_remote_code=False`. Only its network helpers were stubbed: `has_file` reported a file present, and `get_cached_module_file` recorded any code download. On5.16.1 the download helper ran before trust denial, so the zero-download assertion failed. On5.21.0 trust denial raised before that helper, so the assertion passed. Both wheels were checked against their official SHA256; no model was downloaded. Source fix: https://github.com/huggingface/transformers/commit/cbc1651a032b923da7f4b44b3d0e6f68e6ba6b55, shipped in https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/utils.py. The GHSA-x9r9-c232-4q39 affected range ending at5.8.1 is stale: the actual5.16.1 wheel still contained the defect.

The real PyJWT crypto consumer generated a temporary EC key, signed and verified an ES256 token, and rejected verification with another key. The installed cryptography50.0.2 backend reported `OpenSSL 4.0.3 29 Sep 2026`. No key or token value was printed or persisted.

The downloaded official wheel bytes matched uv.lock SHA256. Installed contents matched those wheels byte-for-byte:27 files for filelock4.2.4 and335 for setuptools84.2.1, excluding installer-rewritten RECORD files. Source wheels: https://pypi.org/pypi/filelock/4.2.4/json and https://pypi.org/pypi/setuptools/84.2.1/json.

Final additional wheel verification:

| Package | Wheel SHA256 | Installed files checked |
| --- | --- | ---: |
| transformers5.21.0 | `8803a8712932aa3441c1e8bb340e66d5e3eca079fe65d9b717ede2f3ead01c79` | 2803 |
| huggingface-hub1.33.0 | `04e434b06e100eddbce9a6e817d72693a7884b10a79bd67ab48080d5c07eb899` | 193 |
| cryptography50.0.2, cp311-abi3 macOS ARM | `fa8f5efb344d6908a1ce62f4a24e2e5780f825d6f53f5f50ec5ffacac72936cb` | 119 |

Installed `transformers/generation/utils.py` SHA256: `966f70ba83d94c9ce07b21150be49ff84b24eadbf9c47de052a1fb0f8ba38679`. Its source fix is cbc1651a032b923da7f4b44b3d0e6f68e6ba6b55.

To reproduce the consumer assertion in an environment containing either official Transformers wheel:

```python
from unittest.mock import patch
import transformers.generation.utils as implementation

with patch.object(implementation, "has_file", return_value=True, create=True):
    with patch.object(implementation, "get_cached_module_file") as download:
        download.return_value = "/unused/custom_generate/generate.py"
        try:
            implementation.GenerationMixin.load_custom_generate(
                object(), "untrusted/model", trust_remote_code=False
            )
        except ValueError as error:
            assert "trust_remote_code" in str(error)
        else:
            raise AssertionError("trust denial did not raise ValueError")
        download.assert_not_called()
```

The assertion fails on5.16.1 and passes on5.21.0. Both executions set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` as an additional network restriction.

`git diff --check`, the project craftsmanship diff gate, and plugin source/craftsmanship checks passed. Passing a TOML path explicitly to the Python-only project checker produced a parser error; the documented diff mode correctly filtered file types and passed.

## Remaining constraints

Intel Mac torch2.2.2 and transformers4.57.6, Intel cryptography48.0.1, and old Apple Silicon setuptools81.0.0 remain. Replacing these requires a supported platform strategy or upstream patched compatible artifacts. This patch does not claim those advisories resolved. Root will obtain genuine hosted bot reviews before protected merge.
