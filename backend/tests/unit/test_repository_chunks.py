import sqlite3

import pytest

from app.domain.errors import EmbeddingDimensionError, ItemNotProcessingError
from app.domain.models import ItemStatus, ItemType
from app.store.repository import Repository
from tests.conftest import make_chunk, make_note, make_ready

X, Y, Z = [1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0]


def counts(conn: sqlite3.Connection) -> tuple[int, int, int]:
    def one(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    return (
        one("SELECT count(*) FROM chunks"),
        one("SELECT count(*) FROM chunks_vec"),
        one("SELECT count(*) FROM chunks_fts_docsize"),
    )


def assert_fts_consistent(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO chunks_fts(chunks_fts, rank) VALUES ('integrity-check', 1)")


def test_replace_chunks_writes_all_and_marks_ready(repo: Repository, db_conn) -> None:
    item = make_ready(repo, [("alpha text", X), ("beta text", Y)])

    assert item.status is ItemStatus.READY
    assert item.chunk_count == 2
    assert counts(db_conn) == (2, 2, 2)
    assert_fts_consistent(db_conn)


def test_replace_chunks_on_pending_item_writes_nothing(repo: Repository, db_conn) -> None:
    item = make_note(repo)
    with pytest.raises(ItemNotProcessingError) as excinfo:
        repo.replace_chunks(item.id, [make_chunk(0, "t")], [X])
    assert excinfo.value.current == "pending"
    assert counts(db_conn) == (0, 0, 0)
    assert repo.get_item(item.id).status is ItemStatus.PENDING  # type: ignore[union-attr]


def test_replace_chunks_on_deleted_item_writes_nothing(repo: Repository, db_conn) -> None:
    item = make_note(repo)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.delete_item(item.id)  # deleted while the worker was embedding

    with pytest.raises(ItemNotProcessingError) as excinfo:
        repo.replace_chunks(item.id, [make_chunk(0, "t")], [X])
    assert excinfo.value.current is None
    assert counts(db_conn) == (0, 0, 0)
    assert not db_conn.in_transaction


def test_wrong_embedding_dim_writes_nothing(repo: Repository, db_conn) -> None:
    item = make_note(repo)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    with pytest.raises(EmbeddingDimensionError, match="chunk ordinal 1 has 3 dims; expected 4"):
        repo.replace_chunks(item.id, [make_chunk(0, "a"), make_chunk(1, "b")], [X, [1.0, 0, 0]])
    assert counts(db_conn) == (0, 0, 0)
    assert repo.get_item(item.id).status is ItemStatus.PROCESSING  # type: ignore[union-attr]


def test_chunk_embedding_count_mismatch_and_empty_are_rejected(repo: Repository) -> None:
    item = make_note(repo)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    with pytest.raises(ValueError, match="2 chunks but 1 embeddings"):
        repo.replace_chunks(item.id, [make_chunk(0, "a"), make_chunk(1, "b")], [X])
    with pytest.raises(ValueError, match="at least one chunk"):
        repo.replace_chunks(item.id, [], [])


def test_replacing_chunks_leaves_no_ghost_fts_or_vec_rows(repo: Repository, db_conn) -> None:
    item = make_note(repo, "v1")
    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.replace_chunks(item.id, [make_chunk(0, "obsolete zebra")], [X])
    # Re-processing a ready item isn't a supported transition yet; force it to test the swap.
    db_conn.execute("UPDATE items SET status = 'processing' WHERE id = ?", (item.id,))
    repo.replace_chunks(item.id, [make_chunk(0, "fresh giraffe")], [Y])

    assert repo.keyword_search("zebra", 10) == []
    assert len(repo.keyword_search("giraffe", 10)) == 1
    assert counts(db_conn) == (1, 1, 1)
    assert_fts_consistent(db_conn)


def test_chunk_update_trigger_keeps_fts_in_sync(repo: Repository, db_conn) -> None:
    make_ready(repo, [("original walrus", X)])
    db_conn.execute("UPDATE chunks SET text = 'edited narwhal'")

    assert repo.keyword_search("walrus", 10) == []
    assert len(repo.keyword_search("narwhal", 10)) == 1
    assert_fts_consistent(db_conn)


def test_deleting_item_cascades_to_chunks_fts_and_vec(repo: Repository, db_conn) -> None:
    keep = make_ready(repo, [("kept penguin", Z)])
    gone = make_ready(repo, [("doomed otter", X), ("doomed badger", Y)])
    assert counts(db_conn) == (3, 3, 3)

    assert repo.delete_item(gone.id)

    assert counts(db_conn) == (1, 1, 1)
    assert repo.keyword_search("otter badger", 10) == []
    remaining = {c.item_id for c in repo.get_chunks_by_ids(range(1, 10)).values()}
    assert remaining == {keep.id}
    assert {h.chunk_id for h in repo.vector_search(X, 10)} == set(
        repo.get_chunks_by_ids(range(1, 10))
    )
    assert_fts_consistent(db_conn)


def test_vector_search_returns_nearest_first_with_positions(repo: Repository) -> None:
    make_ready(repo, [("x", X), ("mostly x", [0.9, 0.1, 0, 0]), ("y", Y)])

    hits = repo.vector_search([1.0, 0.05, 0, 0], k=3)

    assert [h.position for h in hits] == [1, 2, 3]
    similarities = [h.similarity for h in hits]
    assert similarities == sorted(similarities, reverse=True)
    assert similarities[0] == pytest.approx(0.9988, abs=1e-3)
    assert len(repo.vector_search(X, k=2)) == 2


def test_vector_search_filters_non_ready_items_as_safety_net(repo: Repository, db_conn) -> None:
    item = make_ready(repo, [("x", X)])
    db_conn.execute("UPDATE items SET status = 'failed' WHERE id = ?", (item.id,))
    assert repo.vector_search(X, k=5) == []


def test_vector_search_rejects_wrong_query_dim(repo: Repository) -> None:
    with pytest.raises(EmbeddingDimensionError, match="query embedding has 2 dims"):
        repo.vector_search([1.0, 0.0], k=1)


def test_keyword_search_survives_punctuation(repo: Repository) -> None:
    make_ready(repo, [("Notes about C and AI systems", X)])
    hits = repo.keyword_search('what\'s C++ & "AI"?', 10)
    assert len(hits) == 1
    assert repo.keyword_search("the of and", 10) == []


def test_keyword_search_ranks_ascending_bm25(repo: Repository) -> None:
    make_ready(
        repo,
        [
            ("kangaroo kangaroo kangaroo jumps", X),
            ("one kangaroo among many other unrelated words here", Y),
            ("filler about lions", Z),
            ("filler about tigers", Z),
        ],
    )
    hits = repo.keyword_search("kangaroo", 10)

    assert [h.position for h in hits] == [1, 2]
    assert hits[0].bm25 < hits[1].bm25 < 0
    chunks = repo.get_chunks_by_ids(h.chunk_id for h in hits)
    assert chunks[hits[0].chunk_id].text.startswith("kangaroo kangaroo")


def test_keyword_search_downweights_title_header(repo: Repository) -> None:
    """With equal column weights the header-only match wins (short column); 0.5 flips it."""
    make_ready(repo, [(f"filler lions tigers number {i}", Z) for i in range(6)])
    header_only = make_note(repo, "header item")
    repo.set_status(header_only.id, ItemStatus.PROCESSING)
    repo.replace_chunks(
        header_only.id,
        [make_chunk(0, "plain words about nothing in particular", header="Title: koala")],
        [X],
    )
    body = make_note(repo, "body item")
    repo.set_status(body.id, ItemStatus.PROCESSING)
    body_text = "koala " + " ".join(f"w{i}" for i in range(8))
    repo.replace_chunks(body.id, [make_chunk(0, body_text, header="Title: other")], [Y])

    hits = repo.keyword_search("koala", 10)

    best = repo.get_chunks_by_ids([hits[0].chunk_id])[hits[0].chunk_id]
    assert best.item_id == body.id


def test_get_chunks_by_ids_joins_item_fields(repo: Repository) -> None:
    item = make_ready(repo, [("first", X), ("second", Y)], title="My note")
    hit_ids = [h.chunk_id for h in repo.vector_search(Y, 1)]

    records = repo.get_chunks_by_ids([*hit_ids, *hit_ids, 999])

    assert list(records) == hit_ids
    record = records[hit_ids[0]]
    assert (record.text, record.item_id, record.item_title) == ("second", item.id, "My note")
    assert record.item_type is ItemType.NOTE
    assert repo.get_chunks_by_ids([]) == {}
