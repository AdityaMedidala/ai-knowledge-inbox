"""One connection + Repository per unit of work (a request or a job), always closed."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.store.db import connect
from app.store.repository import Repository


@contextmanager
def repository_session(db_path: Path, embedding_dim: int) -> Iterator[Repository]:
    conn = connect(db_path)
    try:
        yield Repository(conn, embedding_dim=embedding_dim)
    finally:
        conn.close()
