"""Usage log lines shared by chat providers. Counts and timings only, never text."""

import structlog

logger = structlog.get_logger(__name__)


def log_chat_completed(
    model: str, *, input_tokens: int | None, output_tokens: int | None, ms: float, streamed: bool
) -> None:
    logger.info(
        "provider.chat_completed",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        ms=ms,
        streamed=streamed,
    )
