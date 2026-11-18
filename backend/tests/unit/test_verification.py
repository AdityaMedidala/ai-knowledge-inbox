from structlog.testing import capture_logs

from app.domain.models import ChunkRecord, ItemType, RetrievedChunk
from app.domain.verification import NO_CITATION, Verdict
from app.providers.fakes import FakeVerifier
from app.services.verification import VerificationService, split_sentences

EVIDENCE = "The default checkpoint threshold is 1000 pages of WAL data."


def source(text: str = EVIDENCE) -> RetrievedChunk:
    record = ChunkRecord(
        id=1,
        item_id="item",
        ordinal=0,
        section=None,
        context_header="",
        text=text,
        token_count=10,
        item_title="WAL",
        item_type=ItemType.NOTE,
        source_url=None,
    )
    return RetrievedChunk(record, vec_rank=1, fts_rank=None, rrf=0.0, similarity=0.8)


def service(verifier: FakeVerifier, escalation: FakeVerifier | None = None) -> VerificationService:
    return VerificationService(verifier, escalation, escalate_below=0.8)


# --- sentence splitting ---------------------------------------------------------------------


def test_split_sentences_keeps_refs_and_skips_headings_and_labels() -> None:
    answer = (
        "**What a checkpoint does**\n\n"
        "- It copies WAL pages back [1]. Then it resets the WAL.【2】\n"
        "### Notes\n"
        "```sql\nPRAGMA journal_mode = WAL;\n```\n"
        "1. Threshold is 1000 pages [1, 2], per the docs. Version 3.7.0 added WAL."
    )
    assert split_sentences(answer) == [
        ("It copies WAL pages back.", [1]),
        ("Then it resets the WAL.", [2]),
        ("Threshold is 1000 pages, per the docs.", [1, 2]),
        ("Version 3.7.0 added WAL.", []),
    ]


def test_split_sentences_checks_bold_only_list_items() -> None:
    answer = (
        "Imports are grouped:\n\n1. **Standard library imports**  \n"
        "2. **Related third-party imports**"
    )
    assert split_sentences(answer) == [
        ("Imports are grouped:", []),
        ("Standard library imports", []),
        ("Related third-party imports", []),
    ]


def test_split_sentences_still_skips_bold_list_labels() -> None:
    answer = (
        "- **Overview**:\n- **`asyncio.Queue`**\n- **Readers and writers:**\n"
        "- Readers never block [1]."
    )
    assert split_sentences(answer) == [("Readers never block.", [1])]


def test_split_sentences_attaches_a_citation_only_line_to_the_sentence_before() -> None:
    answer = "Readers never block writers [2].\n\n[1][3]"
    assert split_sentences(answer) == [("Readers never block writers.", [2, 1, 3])]


def test_split_sentences_treats_a_sources_line_as_citations_not_a_sentence() -> None:
    for line in ("**Sources**: [1][2]", "Sources: [1], [2]", "Source: 【1】【2】"):
        assert split_sentences(f"Pending changes are rolled back.\n\n{line}") == [
            ("Pending changes are rolled back.", [1, 2])
        ]


def test_split_sentences_drops_a_leading_citation_only_line() -> None:
    assert split_sentences("[1]\nThe WAL is reset.") == [("The WAL is reset.", [])]


def test_split_sentences_does_not_split_on_abbreviations() -> None:
    answer = (
        "The standup moves to 10:30 a.m. on Tuesdays [1]. "
        "Use a ratio, e.g. 20 g to 320 g, i.e. 1:16 [2]. It ends at 11 a.m. Then lunch."
    )
    assert split_sentences(answer) == [
        ("The standup moves to 10:30 a.m. on Tuesdays.", [1]),
        ("Use a ratio, e.g. 20 g to 320 g, i.e. 1:16.", [2]),
        ("It ends at 11 a.m.", []),
        ("Then lunch.", []),
    ]


def test_split_sentences_strips_suffixed_markers_and_keeps_their_refs() -> None:
    assert split_sentences("The default is 1000 pages【2†section 6】【4†section 2.3】.") == [
        ("The default is 1000 pages.", [2, 4])
    ]


# --- service --------------------------------------------------------------------------------


def test_uncited_and_invalid_ref_sentences_are_unsupported_without_a_backend_call() -> None:
    verifier = FakeVerifier()
    result = service(verifier).verify(
        "The default checkpoint threshold is 1000 pages [1]. No source here. Bad ref [7].",
        [source()],
    )

    assert result is not None
    assert [(s.verdict, s.decided_by) for s in result.sentences] == [
        (Verdict.SUPPORTED, "fake"),
        (Verdict.UNSUPPORTED, NO_CITATION),
        (Verdict.UNSUPPORTED, NO_CITATION),
    ]
    checked = verifier.calls[0]
    assert [c.sentence for c in checked] == ["The default checkpoint threshold is 1000 pages."]
    assert checked[0].evidence == (EVIDENCE,)


def test_answer_with_no_citations_never_calls_the_verifier() -> None:
    verifier = FakeVerifier()
    result = service(verifier).verify("Nothing cited. At all.", [source()])
    assert result is not None and result.count(Verdict.UNSUPPORTED) == 2
    assert verifier.calls == []


def test_low_confidence_jev_verdicts_escalate_to_groq_only_for_those() -> None:
    jev = FakeVerifier("jev", confidence=0.5)
    groq = FakeVerifier("groq", confidence=0.95)
    result = service(jev, groq).verify(
        "The default checkpoint threshold is 1000 pages [1]. Uncited.", [source()]
    )

    assert result is not None
    assert result.escalated == 1
    assert [s.decided_by for s in result.sentences] == ["groq", NO_CITATION]
    assert [len(call) for call in groq.calls] == [1]


def test_confident_jev_verdicts_and_non_jev_verifiers_do_not_escalate() -> None:
    groq = FakeVerifier("groq")
    answer = "The default checkpoint threshold is 1000 pages [1]."
    confident = service(FakeVerifier("jev", confidence=0.9), groq).verify(answer, [source()])
    not_jev = service(FakeVerifier("fake", confidence=0.1), groq).verify(answer, [source()])
    assert confident is not None and not_jev is not None
    assert (confident.escalated, not_jev.escalated) == (0, 0)
    assert groq.calls == []


def test_verifier_failure_is_logged_and_returns_none() -> None:
    with capture_logs() as logs:
        result = service(FakeVerifier(fail=True)).verify("Claim [1].", [source()])
    assert result is None
    assert any(log["event"] == "query.verify_failed" for log in logs)


def test_escalation_failure_keeps_the_jev_verdicts() -> None:
    jev = FakeVerifier("jev", confidence=0.5)
    with capture_logs() as logs:
        result = service(jev, FakeVerifier("groq", fail=True)).verify(
            "The default checkpoint threshold is 1000 pages [1].", [source()]
        )
    assert result is not None
    assert (result.sentences[0].decided_by, result.escalated) == ("jev", 0)
    assert any(log["event"] == "query.verify_escalation_failed" for log in logs)
