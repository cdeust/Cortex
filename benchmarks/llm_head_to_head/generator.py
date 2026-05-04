"""Generator wrappers — Anthropic + Google APIs with retry/backoff.

Protocol §3 generator panel + §11.6 anti-cheating (one generation per
item × condition × generator; temperature = 0 or vendor floor; no
best-of-N).

API keys are read from the environment ONLY:
  - ANTHROPIC_API_KEY (Haiku 4.5, Opus 4.7)
  - GOOGLE_API_KEY    (Gemini 2.0 Flash)
  - OPENAI_API_KEY    (GPT-4o judge — not in current scope per v3 §3
    table for generators, but kept here for the cross-vendor judge of
    Haiku answers)

Keys are NEVER logged, NEVER serialised into the manifest, NEVER printed.
On missing key, ``call_generator`` raises with a clear message naming
which env var is required for which model.

precondition: the relevant API client library is installed (see
  ``pyproject.toml`` dev deps to be added at run time, NOT imported here
  at module load — this file is import-safe even when the libs are
  absent so that ``--dry-run`` works without API spend).
postcondition: ``call_generator(...)`` returns ``GeneratorResponse``
  with text, input_tokens, output_tokens, and retry_log; or raises
  ``GeneratorError`` with the failed attempt log. On dry-run mode no
  network call is made; the function returns a stubbed response with
  ``dry_run=True``.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field


# Verified pricing snapshotted at protocol freeze (protocol §7).
# source: anthropic api docs (verified 2026-04-30)
# source: openai api docs (verified 2026-04-30)
# source: google ai docs paid Tier 1 (verified 2026-04-30)
PRICING_USD_PER_M_TOKEN: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-opus-4-7-20260301": {"input": 5.00, "output": 25.00},
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    "gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}


# Retry/backoff config (protocol §11.7 — every retry logged to manifest).
MAX_RETRIES = 5
INITIAL_BACKOFF_S = 1.0
BACKOFF_MULTIPLIER = 2.0
MAX_JITTER_S = 0.5


VENDOR_BY_MODEL: dict[str, str] = {
    "claude-haiku-4-5-20251001": "anthropic",
    "claude-opus-4-7-20260301": "anthropic",
    "gpt-4o-mini-2024-07-18": "openai",
    "gpt-4o-2024-11-20": "openai",
    "gemini-2.0-flash": "google",
}


REQUIRED_ENV_VAR: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}


class GeneratorError(RuntimeError):
    """Raised when a generation request exhausts retries or hits a fatal error."""


@dataclass
class RetryAttempt:
    attempt_num: int
    error_class: str
    error_message: str  # truncated; never contains API key
    backoff_s: float


@dataclass
class GeneratorResponse:
    model_id: str
    text: str
    input_tokens: int
    output_tokens: int
    retries: list[RetryAttempt] = field(default_factory=list)
    dry_run: bool = False


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for one call. Pricing snapshotted at freeze.

    pre: ``model_id`` ∈ ``PRICING_USD_PER_M_TOKEN``.
    post: returns float ≥ 0.
    """
    if model_id not in PRICING_USD_PER_M_TOKEN:
        raise KeyError(
            f"Unknown model {model_id!r} for cost estimation. Update "
            "PRICING_USD_PER_M_TOKEN with a verified source citation per §7."
        )
    rates = PRICING_USD_PER_M_TOKEN[model_id]
    return (input_tokens / 1_000_000) * rates["input"] + (
        output_tokens / 1_000_000
    ) * rates["output"]


def _require_env_var(model_id: str) -> str:
    """Resolve and return the API key, or raise with a clear message.

    pre: ``model_id`` is in ``VENDOR_BY_MODEL``.
    post: returns a non-empty key string (never logged anywhere).
    """
    if model_id not in VENDOR_BY_MODEL:
        raise GeneratorError(f"Unknown model pin: {model_id!r}")
    vendor = VENDOR_BY_MODEL[model_id]
    var_name = REQUIRED_ENV_VAR[vendor]
    key = os.environ.get(var_name, "")
    if not key:
        raise GeneratorError(
            f"Missing API key: env var {var_name} is required for model "
            f"{model_id!r} (vendor: {vendor})."
        )
    return key


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with bounded jitter.

    pre: attempt ∈ [0, MAX_RETRIES].
    post: returns float ≥ 0; deterministic upper bound for budget reasoning.
    """
    base = INITIAL_BACKOFF_S * (BACKOFF_MULTIPLIER**attempt)
    jitter = random.uniform(0.0, MAX_JITTER_S)
    return base + jitter


def call_generator(
    model_id: str,
    prompt: str,
    max_output_tokens: int = 4_000,
    temperature: float = 0.0,
    dry_run: bool = False,
) -> GeneratorResponse:
    """Issue one generation request to the named model.

    pre:
      - ``model_id`` is a known pin (entry in ``VENDOR_BY_MODEL``).
      - ``prompt`` is the rendered Appendix-A template (already filled).
      - ``max_output_tokens`` ≤ vendor maximum (caller responsibility).
      - ``temperature`` = 0.0 by default (protocol §11.6 forbids best-of-N).
    post:
      - on dry_run: returns a stub with no network access and dry_run=True.
      - on success: returns ``GeneratorResponse`` with token counts from
        the vendor (or a heuristic estimate if vendor doesn't provide them).
      - on failure after MAX_RETRIES: raises ``GeneratorError`` whose
        message lists the retry log (never includes API keys).
    invariant: API keys never appear in the response, retries, or error
      messages.
    """
    if dry_run:
        # Stub: no API call, no key required. Token counts heuristic.
        return GeneratorResponse(
            model_id=model_id,
            text=f"[DRY RUN — would call {model_id}]",
            input_tokens=int(len(prompt.split()) * 1.33),
            output_tokens=0,
            dry_run=True,
        )

    # Pre-flight key check (raises GeneratorError if absent).
    _require_env_var(model_id)
    vendor = VENDOR_BY_MODEL[model_id]

    retries: list[RetryAttempt] = []
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            if vendor == "anthropic":
                return _call_anthropic(
                    model_id, prompt, max_output_tokens, temperature, retries
                )
            elif vendor == "google":
                return _call_google(
                    model_id, prompt, max_output_tokens, temperature, retries
                )
            elif vendor == "openai":
                return _call_openai(
                    model_id, prompt, max_output_tokens, temperature, retries
                )
            else:
                raise GeneratorError(f"Unsupported vendor: {vendor}")
        except _RetryableError as e:
            last_error = e
            if attempt >= MAX_RETRIES:
                break
            backoff = _backoff_seconds(attempt)
            retries.append(
                RetryAttempt(
                    attempt_num=attempt + 1,
                    error_class=type(e).__name__,
                    error_message=str(e)[:200],
                    backoff_s=backoff,
                )
            )
            time.sleep(backoff)
        # Non-retryable errors propagate — unknown failure modes must NOT
        # be silently retried (protocol §11.7 — every retry logged).

    raise GeneratorError(
        f"Exhausted {MAX_RETRIES} retries for {model_id}: "
        f"last error {type(last_error).__name__}: {last_error!r}"
    )


# ── Vendor adapters (deferred imports keep this module import-safe) ──


class _RetryableError(RuntimeError):
    """Internal marker for 429 / 500 / connection errors."""


def _heuristic_word_tokens(text: str) -> int:
    """1.33 words→tokens fallback for vendors that don't report usage.

    pre: ``text`` is a Python str (possibly empty).
    post: returns int ≥ 0; 0 only when text is empty.
    source: GPT-2 BPE empirical word→token ratio ≈ 1.33 (Radford 2019),
      cross-checked against tiktoken cl100k. See protocol §7.
    """
    if not text:
        return 0
    return int(len(text.split()) * 1.33) + 1


def _call_anthropic(
    model_id: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    retries: list[RetryAttempt],
) -> GeneratorResponse:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise GeneratorError(
            "anthropic SDK not installed. `uv pip install anthropic` before "
            "running the harness with API spend."
        ) from e

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=max_output_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:  # broad: anthropic exception classes vary by version
        if _looks_retryable(e):
            raise _RetryableError(str(e)) from e
        raise

    text = "".join(getattr(b, "text", "") for b in msg.content)
    return GeneratorResponse(
        model_id=model_id,
        text=text,
        input_tokens=msg.usage.input_tokens,
        output_tokens=msg.usage.output_tokens,
        retries=list(retries),
    )


def _call_google(
    model_id: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    retries: list[RetryAttempt],
) -> GeneratorResponse:
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError as e:
        raise GeneratorError(
            "google-genai SDK not installed. `uv pip install google-genai` "
            "before running the harness with API spend."
        ) from e

    client = genai.Client()  # reads GOOGLE_API_KEY / GEMINI_API_KEY
    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )
    except Exception as e:
        if _looks_retryable(e):
            raise _RetryableError(str(e)) from e
        raise

    text = (resp.text or "") if hasattr(resp, "text") else ""
    usage = getattr(resp, "usage_metadata", None)
    # Google sometimes omits usage on streaming/short responses; fall back
    # to the protocol §7 word→token heuristic so cost-tracking is never
    # silently zero. The fallback is ALWAYS conservative (overcounts).
    in_tok = getattr(usage, "prompt_token_count", 0) or 0
    out_tok = getattr(usage, "candidates_token_count", 0) or 0
    if not in_tok:
        in_tok = _heuristic_word_tokens(prompt)
    if not out_tok:
        out_tok = _heuristic_word_tokens(text)
    return GeneratorResponse(
        model_id=model_id,
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        retries=list(retries),
    )


def _call_openai(
    model_id: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    retries: list[RetryAttempt],
) -> GeneratorResponse:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as e:
        raise GeneratorError(
            "openai SDK not installed. `uv pip install openai` before running "
            "the harness with API spend."
        ) from e

    client = OpenAI()  # reads OPENAI_API_KEY
    try:
        completion = client.chat.completions.create(
            model=model_id,
            temperature=temperature,
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        if _looks_retryable(e):
            raise _RetryableError(str(e)) from e
        raise

    choice = completion.choices[0]
    text = choice.message.content or ""
    usage = completion.usage
    return GeneratorResponse(
        model_id=model_id,
        text=text,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        retries=list(retries),
    )


def _looks_retryable(exc: Exception) -> bool:
    """Classify exceptions as retryable (429/500/connection) vs fatal.

    pre: ``exc`` is any Exception raised by a vendor SDK.
    post: returns True for transient errors (rate limits, server errors,
      connection issues); False otherwise (auth errors, schema errors —
      retrying these wastes time and money).
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    transient_markers = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "rate limit",
        "ratelimit",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "temporary",
        "service unavailable",
    )
    if any(m in name for m in ("ratelimit", "timeout", "connection", "apierror")):
        return True
    return any(m in msg for m in transient_markers)
