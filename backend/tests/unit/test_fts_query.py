from app.store.fts import MAX_FTS_TOKENS, build_fts_query


def test_punctuation_and_quotes_are_neutralised() -> None:
    assert build_fts_query('what\'s C++ & "AI"?') == '"c" OR "ai"'


def test_fts_operators_become_plain_terms() -> None:
    assert build_fts_query("NEAR(a b) OR -x* ^col:y") == '"near" OR "b" OR "x" OR "col" OR "y"'


def test_stop_word_only_and_empty_queries_return_none() -> None:
    assert build_fts_query("what is the") is None
    assert build_fts_query("  ?!  ") is None
    assert build_fts_query("") is None


def test_tokens_are_deduplicated_and_lowercased() -> None:
    assert build_fts_query("Python python PYTHON tips") == '"python" OR "tips"'


def test_unicode_words_are_kept() -> None:
    assert build_fts_query("café naïve 東京") == '"café" OR "naïve" OR "東京"'


def test_long_question_is_capped_at_max_unique_tokens() -> None:
    question = " ".join(f"word{i}" for i in range(200))
    assert len(question) > 1000
    query = build_fts_query(question)
    assert query is not None
    terms = query.split(" OR ")
    assert len(terms) == MAX_FTS_TOKENS == 32
    assert terms[0] == '"word0"'
    assert terms[-1] == '"word31"'
