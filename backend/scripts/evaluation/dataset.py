"""Dataset hygiene: the stratified dev/test split and the evidence check.

Thresholds are chosen on `dev` and reported on `test`, so the split is written into
eval_set.json once and never reshuffled.
"""

import json
import random
from collections import Counter

from app.services.chunker import ChunkLimits, chunk_document
from app.store.repository import Repository
from scripts.evaluation.store import EVAL_SET, KINDS, Question, load_raw, normalize

SPLIT_SEED = 20261118


def assign_splits() -> Counter[tuple[str, str]]:
    """Per kind: sort ids, shuffle with a fixed seed, alternate dev/test. Odd counts alternate
    which split gets the extra question, so the two halves stay the same size overall."""
    data = load_raw()
    rng = random.Random(SPLIT_SEED)  # noqa: S311 — reproducible split, not crypto
    extra_to_dev = True
    by_id = {q["id"]: q for q in data["questions"]}
    for kind in KINDS:
        ids = sorted(q["id"] for q in data["questions"] if q["kind"] == kind)
        rng.shuffle(ids)
        first, second = ("dev", "test") if extra_to_dev else ("test", "dev")
        for index, qid in enumerate(ids):
            by_id[qid]["split"] = first if index % 2 == 0 else second
        if len(ids) % 2:
            extra_to_dev = not extra_to_dev
    EVAL_SET.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return Counter((q["kind"], q["split"]) for q in data["questions"])


def check_evidence(
    repo: Repository, keys: dict[str, str], questions: list[Question], limits: ChunkLimits
) -> list[str]:
    """Every evidence string must sit inside one chunk of its item; otherwise chunk-level hit@k
    can't be scored. Returns human-readable problems (empty = clean)."""
    chunks_by_key: dict[str, list[str]] = {}
    for item_id, key in keys.items():
        item = repo.get_item(item_id)
        assert item is not None and item.extracted_text is not None  # noqa: S101
        chunks = chunk_document(item.extracted_text, title=item.title, limits=limits)
        chunks_by_key[key] = [normalize(c.text) for c in chunks]
    problems = []
    for question in questions:
        for key in question.expected_items:
            if key not in chunks_by_key:
                problems.append(f"{question.id}: unknown item {key}")
        for key, text in question.evidence.items():
            needle = normalize(text)
            if not any(needle in chunk for chunk in chunks_by_key.get(key, [])):
                problems.append(f"{question.id}: evidence not in one chunk of {key}: {text!r}")
    return problems
