"""Are the cached embedding weights the bytes the Hub declared for them?

Issue #734, slice 4. The embedding revision is pinned, but no file of the
embedding cache was hashed anywhere (docs/audits/model-identity-inventory-
2026-11-06.md, "Digest of the bytes: none"): a truncated or altered
``model.safetensors`` under the pinned snapshot was reported by no surface.

The Hugging Face cache names the blob of an LFS file by the sha256 the Hub
returned for it when it was downloaded (``blobs/<etag>``, the etag being the
file's sha256), and the snapshot entry is a link to that blob.
``classify_weights`` compares the digest of the bytes on disk with that name.

Pure: the blob name and the digest are read by the caller
(``infrastructure.embedding_weights_cache``).

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 3
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# source: huggingface_hub file_download.py, REGEX_SHA256 ("Regex to check if
# the file etag IS a valid sha256") and ``blob_path = os.path.join(
# storage_folder, "blobs", etag)``, in both versions uv.lock resolves
# (0.36.2 and 1.33.0; read 2026-11-10).
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

ABSENT = "absent"
UNVERIFIABLE = "unverifiable"
VERIFIED = "verified"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class WeightsIdentity:
    """What the cached weights are, against the digest their blob is named by."""

    state: str
    sha256: str | None
    expected: str | None


def classify_weights(blob_name: str | None, sha256: str | None) -> WeightsIdentity:
    """Classify the cached weights file.

    precondition: ``sha256`` is the hex sha256 of the file the snapshot entry
        resolves to, or None when no file is there; ``blob_name`` is the name
        of the blob the entry links to, or None when the entry is not a link.
    postcondition: ``absent`` when ``sha256`` is None; ``unverifiable`` when
        ``blob_name`` is not a sha256 (a copied file, as huggingface_hub writes
        where links are unsupported, carries no declared digest);
        ``verified`` when both digests are equal; ``mismatch`` otherwise. A
        mismatch says the bytes differ from what was downloaded, not why.
    """
    if sha256 is None:
        return WeightsIdentity(ABSENT, None, None)
    if blob_name is None or not _SHA256.match(blob_name.lower()):
        return WeightsIdentity(UNVERIFIABLE, sha256, None)
    expected = blob_name.lower()
    state = VERIFIED if sha256.lower() == expected else MISMATCH
    return WeightsIdentity(state, sha256, expected)
