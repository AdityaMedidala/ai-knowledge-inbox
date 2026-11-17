import sqlite3
from pathlib import Path

import pytest

from app.domain.errors import EmbeddingConfigMismatchError
from app.store.db import BUSY_TIMEOUT_MS, connect, transaction
from app.store.migrations import apply_migrations


def migrate(conn: sqlite3.Connection, model: str = "m", dim: int = 4) -> None:
    apply_migrations(conn, embedding_model=model, embedding_dim=dim, db_label="data/inbox.db")


def test_every_connection_gets_required_pragmas(tmp_path: Path) -> None:
    for _ in range(2):
        conn = connect(tmp_path / "x.db")
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        conn.close()


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE t (v INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    assert not conn.in_transaction


def test_migrations_are_idempotent_and_record_meta(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    migrate(conn)
    migrate(conn)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert meta == {"embedding_model": "m", "embedding_dim": "4"}


def test_configured_dim_is_injected_into_vec_table(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    migrate(conn, dim=3)
    with pytest.raises(sqlite3.OperationalError, match="Expected 3 dimensions"):
        conn.execute("INSERT INTO chunks_vec (rowid, embedding) VALUES (1, '[1, 2]')")


@pytest.mark.parametrize(("model", "dim"), [("m", 8), ("other-model", 4)])
def test_meta_guard_rejects_changed_embedding_config(tmp_path: Path, model: str, dim: int) -> None:
    conn = connect(tmp_path / "x.db")
    migrate(conn)
    with pytest.raises(EmbeddingConfigMismatchError) as excinfo:
        migrate(conn, model=model, dim=dim)
    message = str(excinfo.value)
    assert "data/inbox.db" in message
    assert "make reindex" in message
    assert "delete the DB" in message
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert meta == {"embedding_model": "m", "embedding_dim": "4"}
