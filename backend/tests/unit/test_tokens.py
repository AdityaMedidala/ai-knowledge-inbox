from app.utils.tokens import count_tokens, truncate_to_tokens


def test_count_and_truncate() -> None:
    text = "one two three four five six"
    assert count_tokens(text) == 6
    assert truncate_to_tokens(text, 3) == "one two three"
    assert truncate_to_tokens(text, 100) == text


def test_special_token_text_is_treated_as_plain_text() -> None:
    assert count_tokens("<|endoftext|>") > 1
