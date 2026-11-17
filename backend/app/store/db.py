"""SQLite connection factory. One connection per unit of work (request or job)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

BUSY_TIMEOUT_MS = 5000


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and the pragmas every connection needs.

    `isolation_level=None` disables Python's implicit transactions; writes that span statements
    use `transaction()` explicitly.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE takes the write lock up front, so a read-then-write transaction never
    fails mid-way with SQLITE_BUSY when the worker and the API write concurrently."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def sqlite_vec_version(conn: sqlite3.Connection) -> str:
    (version,) = conn.execute("SELECT vec_version()").fetchone()
    return str(version)
