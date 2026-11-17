"""Async ingestion queue: N tasks pull item ids and run the synchronous job in a thread.

Retries never hold a worker slot: the job puts the item back to 'pending' and the worker
re-enqueues it from a loop timer after a backoff. Anything left in memory on shutdown (queued
ids, pending timers) is still 'pending' in the database, so startup recovery picks it up.
"""

import asyncio
from collections.abc import Callable

import structlog

from app.services.ingestion import JobResult, Outcome

logger = structlog.get_logger(__name__)

RunJob = Callable[[str], JobResult]  # synchronous; opens its own DB connection
Recover = Callable[[], list[str]]  # synchronous; processing -> pending, returns pending ids
Backoff = Callable[[int], float]  # attempt number (1-based) -> seconds before the next try

SHUTDOWN_GRACE_S = 10.0


class WorkerStoppedError(RuntimeError):
    pass


def exponential_backoff(base_s: float) -> Backoff:
    return lambda attempt: base_s * 2 ** max(attempt - 1, 0)


class IngestionWorker:
    def __init__(
        self, run_job: RunJob, recover: Recover, *, concurrency: int, backoff: Backoff
    ) -> None:
        self._run_job = run_job
        self._recover = recover
        self._concurrency = concurrency
        self._backoff = backoff
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._in_flight: set[asyncio.Future[JobResult]] = set()
        self._retry_timers: set[asyncio.TimerHandle] = set()
        self._retry_fired = asyncio.Event()
        self._accepting = False

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self._recover)
        self._accepting = True
        for item_id in recovered:
            self._queue.put_nowait(item_id)
        self._tasks = [
            asyncio.create_task(self._loop(), name=f"ingest-worker-{n}")
            for n in range(self._concurrency)
        ]
        logger.info("worker.started", concurrency=self._concurrency, recovered=len(recovered))

    def enqueue(self, item_id: str) -> None:
        if not self._accepting:
            raise WorkerStoppedError("The ingestion worker is not accepting jobs.")
        self._queue.put_nowait(item_id)

    async def drain(self, timeout: float) -> None:
        """Wait until the queue is empty, no job is running and no retry is pending."""
        async with asyncio.timeout(timeout):
            while True:
                await self._queue.join()
                if not self._retry_timers:
                    return
                self._retry_fired.clear()
                await self._retry_fired.wait()

    async def stop(self, grace_s: float = SHUTDOWN_GRACE_S) -> None:
        """Stop accepting, drop timers, cancel idle tasks, give running jobs `grace_s` to end."""
        self._accepting = False
        for timer in self._retry_timers:
            timer.cancel()
        self._retry_timers.clear()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._in_flight:
            _, unfinished = await asyncio.wait(self._in_flight, timeout=grace_s)
            if unfinished:
                logger.warning("worker.stop_timeout", running=len(unfinished))
        logger.info("worker.stopped", queued=self._queue.qsize())

    async def _loop(self) -> None:
        while True:
            item_id = await self._queue.get()
            try:
                await self._handle(item_id)
            finally:
                self._queue.task_done()

    async def _handle(self, item_id: str) -> None:
        with structlog.contextvars.bound_contextvars(item_id=item_id):
            job = asyncio.ensure_future(asyncio.to_thread(self._run_job, item_id))
            self._in_flight.add(job)
            job.add_done_callback(self._in_flight.discard)
            try:
                result = await asyncio.shield(job)  # cancelling the task must not orphan the job
            except Exception:
                logger.exception("worker.job_crashed")
                return
            if result.outcome is Outcome.RETRY:
                self._schedule_retry(item_id, result.attempt)

    def _schedule_retry(self, item_id: str, attempt: int) -> None:
        delay = self._backoff(attempt)
        timer: asyncio.TimerHandle | None = None

        def fire() -> None:
            self._retry_timers.discard(timer)  # type: ignore[arg-type]
            if self._accepting:
                self._queue.put_nowait(item_id)
            self._retry_fired.set()

        timer = asyncio.get_running_loop().call_later(delay, fire)
        self._retry_timers.add(timer)
        logger.info("worker.retry_scheduled", delay_s=delay, next_attempt=attempt + 1)
