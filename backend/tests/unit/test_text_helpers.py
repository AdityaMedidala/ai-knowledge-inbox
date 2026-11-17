import pytest

from app.utils.text import (
    DERIVED_TITLE_CHARS,
    PREVIEW_CHARS,
    clip_at_word,
    derive_title,
    normalize_note,
    preview_of,
)


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("\n\n  Groceries  \nmilk", "Groceries"),
        ("# Meeting notes\n\nbody", "Meeting notes"),
        ("   \n\t\n", None),
    ],
)
def test_derive_title_uses_first_non_empty_line(text: str, title: str | None) -> None:
    assert derive_title(text) == title


def test_long_derived_title_is_cut_at_a_word_boundary() -> None:
    title = derive_title("The quick brown fox jumps over the lazy dog " * 5)
    assert title is not None and len(title) <= DERIVED_TITLE_CHARS
    assert title.endswith("…") and not title[:-1].endswith(" ")
    assert title[:-1] in "The quick brown fox jumps over the lazy dog " * 5


def test_clip_without_spaces_hard_cuts() -> None:
    assert clip_at_word("x" * 100, 10) == "x" * 9 + "…"


def test_preview() -> None:
    assert preview_of(None) is None and preview_of("  ") is None
    assert preview_of("a\n\nb") == "a b"
    assert len(preview_of("word " * 200) or "") <= PREVIEW_CHARS


def test_normalize_note_collapses_whitespace_and_nfc() -> None:
    assert normalize_note(" Café  au\nlait ") == normalize_note("Café au lait")
