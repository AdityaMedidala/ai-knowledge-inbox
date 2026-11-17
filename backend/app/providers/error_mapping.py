"""Translate vendor SDK exceptions into ProviderError."""

import openai
import structlog

from app.domain.errors import ProviderError, ProviderErrorKind

logger = structlog.get_logger(__name__)

# 429s that mean "no money", not "slow down": retrying cannot help.
QUOTA_EXHAUSTED_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted"})


def kind_for_status(status: int) -> ProviderErrorKind:
    if status == 429:
        return ProviderErrorKind.RATE_LIMITED
    if status in (401, 403):
        return ProviderErrorKind.AUTH
    if status in (408, 504):
        return ProviderErrorKind.TIMEOUT
    if status >= 500:
        return ProviderErrorKind.UNAVAILABLE
    return ProviderErrorKind.BAD_REQUEST


def provider_error(
    kind: ProviderErrorKind, provider: str, message: str, **kw: bool
) -> ProviderError:
    """Build a ProviderError, logging auth failures distinctly (they need a human, not a retry)."""
    if kind is ProviderErrorKind.AUTH:
        logger.error("provider.auth_failed", provider=provider)
    return ProviderError(kind, provider, message, **kw)


def map_openai_error(exc: openai.OpenAIError, provider: str = "openai") -> ProviderError:
    # APITimeoutError subclasses APIConnectionError, so it must be checked first.
    if isinstance(exc, openai.APITimeoutError):
        return provider_error(ProviderErrorKind.TIMEOUT, provider, "request timed out")
    if isinstance(exc, openai.APIConnectionError):
        return provider_error(ProviderErrorKind.UNAVAILABLE, provider, "connection failed")
    if isinstance(exc, openai.APIStatusError):
        kind = kind_for_status(exc.status_code)
        message = f"HTTP {exc.status_code} ({exc.code or 'no code'})"
        if isinstance(exc, openai.RateLimitError) and exc.code in QUOTA_EXHAUSTED_CODES:
            logger.error("provider.quota_exhausted", provider=provider, code=exc.code)
            return provider_error(kind, provider, message, retryable=False)
        return provider_error(kind, provider, message)
    return provider_error(ProviderErrorKind.UNAVAILABLE, provider, type(exc).__name__)
