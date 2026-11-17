from time import perf_counter
from types import TracebackType


class Timer:
    """Context manager recording elapsed wall time in `ms` (set even if the block raises)."""

    def __init__(self) -> None:
        self.ms: float = 0.0
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.ms = round((perf_counter() - self._start) * 1000, 1)
