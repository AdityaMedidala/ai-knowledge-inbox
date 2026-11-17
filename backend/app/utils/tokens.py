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
