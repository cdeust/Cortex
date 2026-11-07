"""Cortex never reaches the code paths of its unpatchable dependency advisories.

macOS Intel has no wheel past torch 2.2.2 and cryptography 48.0.1, and Apple
silicon before macOS 14 none past torch 2.11 (checked 2026-11-07 with uv 0.11 and
`--only-binary :all:`). Their open Dependabot advisories are therefore closed on
those platforms by construction, and these tests keep the construction:

- the embedding model loads only `*.safetensors` (`use_safetensors=True`), so a
  pickled checkpoint never reaches `torch.load` (GHSA-53q9-r3pm-6pq6,
  GHSA-63cw-57p8-fm3p), and only from its pinned Hub commit, so its `config.json`
  cannot be attacker-chosen (GHSA-29pf-2h5f-8g72);
- no module calls the functions the other advisories name.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from mcp_server.infrastructure import embedding_downloads
from mcp_server.infrastructure import embedding_model_lifecycle as lifecycle

ROOT = Path(__file__).resolve().parents[2] / "mcp_server"
# advisory -> the call that reaches it (source: each GHSA's affected function)
FORBIDDEN = {
    "torch.load: GHSA-53q9-r3pm-6pq6, GHSA-63cw-57p8-fm3p": r"\btorch\.load\(",
    "torch.jit.script: GHSA-rrmf-rvhw-rf47": r"\btorch\.jit\b",
    "profiler jit futures: GHSA-c678-jfcj-6jmf": r"\btorch\.ops\.profiler\b",
    "lstm_cell: GHSA-qfhq-4f3w-5fph": r"\blstm_cell\b",
    "pad_packed_sequence: GHSA-f4hp-rmr7-r7v8": r"\bpad_packed_sequence\b",
    "unpack_sequence: GHSA-vgrw-7cvw-pwgx": r"\bunpack_sequence\b",
    "quantized sigmoid: GHSA-x3gm-94wq-g975": r"\btorch\.(?:ao\.)?quantiz",
    "mkldnn_max_pool2d: GHSA-3749-ghw9-m3mg": r"\bmkldnn_max_pool2d\b",
    "ctc_loss: GHSA-887c-mr87-cxwp": r"\bctc_loss\b",
    "save_pretrained path traversal: GHSA-xrqw-3rrv-vx5w": r"\.save_pretrained\(",
    "custom generate code: GHSA-x9r9-c232-4q39": r"\bload_custom_generate\b",
    "remote model code": r"trust_remote_code\s*=\s*True",
    "Trainer: GHSA-69w3-r845-3855": r"\bTrainer\(",
    "LightGlue: GHSA-fgcw-684q-jj6r": r"\bLightGlue",
    "x509 path building and name constraints: GHSA-jwv3-5hgf-82ww, "
    "GHSA-m2h6-j472-rp4c": r"cryptography\.x509\.verification|\bPolicyBuilder\b",
    "PKCS7 decryption: GHSA-g6cj-pr64-35w5": r"\bpkcs7\b",
}


def _sources():
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(ROOT.rglob("*.py"))]


@pytest.mark.parametrize("advisory", sorted(FORBIDDEN))
def test_no_module_reaches_the_advisory(advisory):
    pattern = re.compile(FORBIDDEN[advisory])
    hits = [f"{p.relative_to(ROOT)}" for p, text in _sources() if pattern.search(text)]
    assert hits == [], f"{advisory}: {hits}"


def test_the_model_is_pinned_to_one_hub_commit():
    assert re.fullmatch(r"[0-9a-f]{40}", lifecycle.DEFAULT_MODEL_REVISION)


def test_the_model_is_built_from_safetensors_only():
    built = {}

    class FakeModel:
        def __init__(self, name, **kwargs):
            built.update(kwargs)

    owner = lifecycle._EmbeddingLifecycleMixin()
    owner._model_name, owner._revision = "m", lifecycle.DEFAULT_MODEL_REVISION
    with mock.patch("sentence_transformers.SentenceTransformer", FakeModel):
        owner._construct_model("cpu", None, local=True)
    assert built["model_kwargs"] == {"use_safetensors": True}
    assert built["revision"] == lifecycle.DEFAULT_MODEL_REVISION


def test_the_background_download_fetches_safetensors_only():
    spawned = []
    with (
        mock.patch.object(
            embedding_downloads, "zero_download_requested", return_value=False
        ),
        mock.patch.object(
            embedding_downloads, "_spawn_detached", lambda cmd, _: spawned.append(cmd)
        ),
    ):
        embedding_downloads.trigger_background_model_download("m", "r", None)
    assert "model_kwargs={'use_safetensors': True}" in spawned[0][3]
