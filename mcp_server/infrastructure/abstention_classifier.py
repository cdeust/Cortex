"""Abstention classifier loading — filesystem boundary for core/abstention_gate.py.

source: ADR-0097 (issue #560: core/ may not import os/pathlib)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_abstention_classifier() -> Any | None:
    """Load the cortex-beam-abstain classifier from its on-disk cache.

    Precondition: none (safe to call with the optional dependency absent).
    Postcondition: returns a loaded ``AbstentionClassifier`` instance, or
    ``None`` if the optional ``cortex-beam-abstain`` package is not
    installed or fails to load — callers must treat ``None`` as
    "no filtering available". Performs a filesystem read
    (``~/.cache/cortex-abstention/model.onnx`` existence check) and, on a
    cache miss, an auto-download; this is exactly why the function lives
    in infrastructure/ and not core/abstention_gate.py (core is zero-I/O).

    source: ADR-0097
    """
    try:
        # Lazy import — package is optional
        from cortex_beam_abstain import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports] — source: ADR-0097
            AbstentionClassifier,
        )

        cache = Path.home() / ".cache" / "cortex-abstention" / "model.onnx"
        if cache.exists():
            return AbstentionClassifier(model_path=cache)
        return AbstentionClassifier()  # auto-download
    except ImportError:
        logger.debug(
            "cortex-beam-abstain not installed; abstention gate disabled. "
            "Install: pip install cortex-beam-abstain"
        )
        return None
    except Exception as e:  # noqa: BLE001 — source: ADR-0097
        logger.warning("Failed to load abstention classifier: %s", e)
        return None
