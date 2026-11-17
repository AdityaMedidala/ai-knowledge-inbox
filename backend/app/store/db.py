"""SQLite connection factory. One connection per unit of work; each loads sqlite-vec."""

import sqlite3
from pathlib import Path

import sqlite_vec


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sqlite_vec_version(conn: sqlite3.Connection) -> str:
    (version,) = conn.execute("SELECT vec_version()").fetchone()
    return str(version)
