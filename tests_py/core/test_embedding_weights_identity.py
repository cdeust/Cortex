"""Classification of the cached embedding weights digest (issue #734, slice 4)."""

from __future__ import annotations

from mcp_server.core.embedding_weights_identity import (
    WeightsIdentity,
    classify_weights,
)

_DIGEST = "a" * 64


def test_no_file_is_absent():
    assert classify_weights(_DIGEST, None) == WeightsIdentity("absent", None, None)


def test_a_copy_without_a_digest_name_is_unverifiable():
    assert classify_weights(None, _DIGEST) == WeightsIdentity(
        "unverifiable", _DIGEST, None
    )


def test_a_blob_named_by_a_git_sha1_is_unverifiable():
    # A non-LFS file's blob is named by its 40-hex git hash, not a sha256.
    sha1 = "b" * 40
    assert classify_weights(sha1, _DIGEST).state == "unverifiable"


def test_equal_digests_verify_whatever_the_case():
    assert classify_weights(_DIGEST.upper(), _DIGEST) == WeightsIdentity(
        "verified", _DIGEST, _DIGEST
    )


def test_an_upper_case_digest_of_the_bytes_verifies():
    assert classify_weights(_DIGEST, _DIGEST.upper()).state == "verified"


def test_different_digests_mismatch():
    found = "c" * 64
    assert classify_weights(_DIGEST, found) == WeightsIdentity(
        "mismatch", found, _DIGEST
    )
