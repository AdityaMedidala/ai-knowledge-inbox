import asyncio
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
import structlog
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from app.domain.models import ItemStatus, ItemType, NewItem
from app.providers.fakes import FakeEmbedder
from app.services.chunker import ChunkLimits
from app.services.ingestion import IngestionService, IngestionSettings, JobResult, Outcome
from app.store.db import connect
from app.store.migrations import apply_migrations
from app.store.repository import Repository
from app.worker import IngestionWorker, WorkerStoppedError, exponential_backoff
from tests.conftest import TEST_DIM, TEST_MODEL

READY = JobResult(Outcome.READY, 1)


class ScriptedJobs:
    """run_job stand-in: per item id, a list of results (or exceptions) returned in order."""

    def __init__(self, script: dict[str, list[JobResult | Exception]] | None = None) -> None:
        self.script = script or {}
        self.calls: list[str] = []
        self.contexts: list[dict[str, Any]] = []
        self.gate: threading.Event | None = None

    def __call__(self, item_id: str) -> JobResult:
        self.calls.append(item_id)
        self.contexts.append(structlog.contextvars.get_contextvars())
        if self.gate is not None:
            assert self.gate.wait(timeout=5), "test gate never opened"
        results = self.script.get(item_id, [READY])
        result = results.pop(0) if len(results) > 1 else results[0]
        if isinstance(result, Exception):
            raise result
        return result


def make_worker(
    jobs: ScriptedJobs,
    *,
    recovered: list[str] | None = None,
    concurrency: int = 1,
    backoff: Callable[[int], float] = lambda _: 0.0,
) -> IngestionWorker:
    return IngestionWorker(
        jobs, lambda: list(recovered or []), concurrency=concurrency, backoff=backoff
    )


def run(coro: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(coro())


def test_processes_enqueued_items_with_item_id_bound() -> None:
    jobs = ScriptedJobs()

    async def scenario() -> None:
        worker = make_worker(jobs, concurrency=2)
        await worker.start()
        worker.enqueue("a")
        worker.enqueue("b")
        await worker.drain(timeout=5)
        await worker.stop()

    run(scenario)
    assert sorted(jobs.calls) == ["a", "b"]
    assert sorted(ctx["item_id"] for ctx in jobs.contexts) == ["a", "b"]


def test_startup_recovery_enqueues_pending_items() -> None:
    jobs = ScriptedJobs()

    async def scenario() -> None:
        worker = make_worker(jobs, recovered=["old1", "old2"])
        await worker.start()
        await worker.drain(timeout=5)
        await worker.stop()

    run(scenario)
    assert jobs.calls == ["old1", "old2"]


def test_retry_is_re_enqueued_after_backoff_for_that_attempt() -> None:
    jobs = ScriptedJobs({"a": [JobResult(Outcome.RETRY, 1), JobResult(Outcome.RETRY, 2), READY]})
    attempts_seen: list[int] = []

    def backoff(attempt: int) -> float:
        attempts_seen.append(attempt)
        return 0.0

    async def scenario() -> None:
        worker = make_worker(jobs, backoff=backoff)
        await worker.start()
        worker.enqueue("a")
        await worker.drain(timeout=5)
        await worker.stop()

    run(scenario)
    assert jobs.calls == ["a", "a", "a"]
    assert attempts_seen == [1, 2]


def test_waiting_retry_does_not_hold_the_only_worker_slot() -> None:
    jobs = ScriptedJobs({"a": [JobResult(Outcome.RETRY, 1), READY]})

    async def scenario() -> None:
        worker = make_worker(jobs, concurrency=1)
        await worker.start()
        worker.enqueue("a")
        worker.enqueue("b")
        await worker.drain(timeout=5)
        await worker.stop()

    run(scenario)
    assert jobs.calls == ["a", "b", "a"]


@pytest.mark.parametrize("outcome", [Outcome.FAILED, Outcome.ALREADY_CLAIMED, Outcome.VANISHED])
def test_terminal_outcomes_are_not_retried(outcome: Outcome) -> None:
    jobs = ScriptedJobs({"a": [JobResult(outcome, 1)]})

    async def scenario() -> None:
        worker = make_worker(jobs)
        await worker.start()
        worker.enqueue("a")
        await worker.drain(timeout=5)
        await worker.stop()

    run(scenario)
    assert jobs.calls == ["a"]


def test_crashing_job_is_logged_and_the_loop_keeps_going() -> None:
    jobs = ScriptedJobs({"boom": [RuntimeError("bug")]})

    async def scenario() -> None:
        worker = make_worker(jobs)
        await worker.start()
        worker.enqueue("boom")
        worker.enqueue("ok")
        await worker.drain(timeout=5)
        await worker.stop()

    with capture_logs(processors=[merge_contextvars]) as logs:
        run(scenario)
    assert jobs.calls == ["boom", "ok"]
    [crash] = [line for line in logs if line["event"] == "worker.job_crashed"]
    assert crash["item_id"] == "boom"


def test_drain_times_out_while_a_retry_is_far_away() -> None:
    jobs = ScriptedJobs({"a": [JobResult(Outcome.RETRY, 1)]})

    async def scenario() -> None:
        worker = make_worker(jobs, backoff=lambda _: 3600.0)
        await worker.start()
        worker.enqueue("a")
        with pytest.raises(TimeoutError):
            await worker.drain(timeout=0.05)
        await worker.stop()

    run(scenario)
    assert jobs.calls == ["a"]


def test_stop_rejects_new_jobs_and_cancels_pending_retries() -> None:
    jobs = ScriptedJobs({"a": [JobResult(Outcome.RETRY, 1), READY]})

    async def scenario() -> None:
        worker = make_worker(jobs, backoff=lambda _: 3600.0)
        await worker.start()
        worker.enqueue("a")
        while not jobs.calls:
            await asyncio.sleep(0)
        await worker.stop()
        with pytest.raises(WorkerStoppedError):
            worker.enqueue("b")

    run(scenario)
    assert jobs.calls == ["a"]  # the retry never fired; the item stays 'pending' in the DB


def test_stop_waits_for_a_running_job_to_finish() -> None:
    jobs = ScriptedJobs()
    jobs.gate = threading.Event()
    finished: list[bool] = []

    async def scenario() -> None:
        worker = make_worker(jobs)
        await worker.start()
        worker.enqueue("slow")
        while not jobs.calls:
            await asyncio.sleep(0)
        stopping = asyncio.create_task(worker.stop(grace_s=5))
        await asyncio.sleep(0)
        assert not stopping.done()
        jobs.gate.set()  # type: ignore[union-attr]
        await stopping
        finished.append(True)

    run(scenario)
    assert finished == [True]


def test_exponential_backoff() -> None:
    backoff = exponential_backoff(2.0)
    assert [backoff(n) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]


# --- with the real service and a real database ----------------------------------------------


def test_crash_recovery_end_to_end(tmp_path: Path) -> None:
    db_path = tmp_path / "worker.db"
    setup = connect(db_path)
    apply_migrations(setup, embedding_model=TEST_MODEL, embedding_dim=TEST_DIM, db_label="t")
    repo = Repository(setup, embedding_dim=TEST_DIM)
    ids = []
    for text in ("first note about WAL", "second note about FTS5"):
        item = repo.create_item(
            NewItem(type=ItemType.NOTE, content_hash=text, raw_content=text, extracted_text=text)
        )
        ids.append(item.id)
    repo.set_status(ids[1], ItemStatus.PROCESSING)  # a job that died mid-way

    settings = IngestionSettings(limits=ChunkLimits(350, 60, 400), max_attempts=3)

    def run_job(item_id: str) -> JobResult:
        conn = connect(db_path)
        try:
            job_repo = Repository(conn, embedding_dim=TEST_DIM)
            return IngestionService(
                job_repo, FakeEmbedder(TEST_DIM), _no_fetch(), settings
            ).process(item_id)
        finally:
            conn.close()

    async def scenario() -> None:
        worker = IngestionWorker(
            run_job, repo.recover_interrupted, concurrency=2, backoff=lambda _: 0
        )
        await worker.start()
        await worker.drain(timeout=10)
        await worker.stop()

    run(scenario)
    statuses = [repo.get_item(item_id).status for item_id in ids]  # type: ignore[union-attr]
    assert statuses == [ItemStatus.READY, ItemStatus.READY]
    setup.close()


class _NoFetch:
    def fetch(self, url: str) -> Any:
        raise AssertionError("notes are never fetched")


def _no_fetch() -> _NoFetch:
    return _NoFetch()
