"""Greedy request batching by token budget and input count (ported from Nova's batcher)."""

from collections.abc import Sequence


def plan_batches(token_counts: Sequence[int], *, max_tokens: int, max_inputs: int) -> list[range]:
    """Split inputs into contiguous, order-preserving batches.

    Every input must already fit `max_tokens` (callers truncate first); unlike Nova, oversize
    inputs are an error here rather than being sent alone and rejected by the API.
    """
    batches: list[range] = []
    start, used = 0, 0
    for index, tokens in enumerate(token_counts):
        if tokens > max_tokens:
            raise ValueError(f"input {index} has {tokens} tokens; batch budget is {max_tokens}.")
        batch_full = index - start == max_inputs or used + tokens > max_tokens
        if batch_full and index > start:
            batches.append(range(start, index))
            start, used = index, 0
        used += tokens
    if start < len(token_counts):
        batches.append(range(start, len(token_counts)))
    return batches
