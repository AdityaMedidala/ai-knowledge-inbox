"""Token counting with the text-embedding-3 tokenizer (cl100k_base).

tiktoken downloads the BPE file on first use; `make install` warms TIKTOKEN_CACHE_DIR so tests
and the app run offline afterwards.
"""

from functools import cache

import tiktoken

ENCODING_NAME = "cl100k_base"


@cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text, disallowed_special=()))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    tokens = _encoding().encode(text, disallowed_special=())
    return text if len(tokens) <= max_tokens else _encoding().decode(tokens[:max_tokens])


def split_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Hard split into consecutive pieces of at most `max_tokens` (last resort for run-on text).

    A cut can land inside a multi-byte character; tiktoken's decode replaces the broken bytes.
    """
    if max_tokens <= 0:
        raise ValueError(f"max_tokens must be positive, got {max_tokens}.")
    tokens = _encoding().encode(text, disallowed_special=())
    return [
        _encoding().decode(tokens[start : start + max_tokens])
        for start in range(0, len(tokens), max_tokens)
    ]
