"""Sentence and question labels: synthetic error sentences and the three labellers.

Labeller ids (provenance is recorded, names are not):
  A      labels proposed by an LLM            eval/labels.json
  B      independent second model (Gemini),   eval/labels_B.json   (blind: never saw A or tags)
  final  adjudicated by the project owner     "final" column of DISAGREEMENTS.md / REVIEW.md

Each cached answer is verified as `answer + synthetic sentences`. Synthetic sentences name the
item they cite as `{item_key}`; that resolves to the answer's first source from that item, so
the citation is a real [n] the verifier can follow. Labels are judged against the CITED source
text only (faithfulness, not world truth).

Gold labels are built in adjudication.gold(): final > uncited rule > A where A and B agree;
disagreements with no final are unresolved, excluded from scoring and counted.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.verification import split_sentences
from scripts.evaluation.corpus import EVAL_DIR

SYNTHETIC = EVAL_DIR / "synthetic.json"
PROPOSED = EVAL_DIR / "labels.json"
SECOND = EVAL_DIR / "labels_B.json"
LABELLERS = {"A": "LLM-proposed", "B": "second model (Gemini), blind", "final": "adjudicated"}
SENTENCE_LABELS = ("supported", "partial", "unsupported", "skip")  # skip = not a claim
_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")


@dataclass(frozen=True, slots=True)
class SentenceRow:
    row: str  # "<question id>.<sentence index>"
    answer_id: str
    index: int
    text: str
    refs: list[int]
    tag: str  # real | blatant | subtle
    error: str | None  # synthetic error type, None for real sentences
    proposed: str | None


def _load(path: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_synthetic() -> dict[str, list[dict[str, str]]]:
    by_answer: dict[str, list[dict[str, str]]] = {}
    for entry in _load(SYNTHETIC).get("sentences", []):
        by_answer.setdefault(entry["answer"], []).append(entry)
    return by_answer


def load_proposed() -> dict[str, Any]:
    """Labeller A."""
    return _labels(_load(PROPOSED))


def load_second() -> dict[str, Any]:
    """Labeller B (empty until `import-labels` has run)."""
    return _labels(_load(SECOND))


def _labels(data: dict[str, Any]) -> dict[str, Any]:
    return {"questions": data.get("questions", {}), "sentences": data.get("sentences", {})}


def resolve(text: str, answer: dict[str, Any]) -> str:
    """'{bike}' -> '[n]' for the first source of that item in this answer."""
    refs = {}
    for source in answer["sources"]:
        refs.setdefault(source["item"], source["ref"])

    def ref_for(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in refs:
            raise SystemExit(f"{answer['id']}: synthetic sentence cites {key}, not in sources")
        return f"[{refs[key]}]"

    return _PLACEHOLDER.sub(ref_for, text)


def labelled_text(answer: dict[str, Any], synthetic: dict[str, list[dict[str, str]]]) -> str:
    extra = [resolve(s["text"], answer) for s in synthetic.get(answer["id"], [])]
    return "\n".join([answer["answer"], *extra])


def sentence_rows(
    answer: dict[str, Any],
    synthetic: dict[str, list[dict[str, str]]],
    proposed: dict[str, str],
) -> list[SentenceRow]:
    """Real sentences first (split_sentences order), then the synthetic ones in file order."""
    real = split_sentences(answer["answer"])
    extra = synthetic.get(answer["id"], [])
    rows = []
    for index, (text, refs) in enumerate(split_sentences(labelled_text(answer, synthetic))):
        row = f"{answer['id']}.{index}"
        entry = extra[index - len(real)] if index >= len(real) else None
        rows.append(
            SentenceRow(
                row=row,
                answer_id=answer["id"],
                index=index,
                text=text,
                refs=refs,
                tag=entry["tag"] if entry else "real",
                error=entry["error"] if entry else None,
                proposed=entry["label"] if entry else proposed.get(row),
            )
        )
    return rows
