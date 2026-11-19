"""Adjudication between labeller A (LLM-proposed) and B (second model, blind).

The final (gold) labels live in eval/labels_final.json: {row: label} plus {row: reason}.
`disagreements` lists the rows where A and B differ in eval/DISAGREEMENTS.md (a generated,
git-ignored view) and returns agreement and Cohen's kappa per set; `adjudicate row=label`
records a final in labels_final.json.

Adjudication rule applied automatically: an uncited sentence is `unsupported`, because that is
how the app treats it (by rule, never sent to a verifier). Its reason says "rule: uncited".
"""

import json
from collections import Counter
from dataclasses import dataclass

from scripts.evaluation.answers import load_answers
from scripts.evaluation.corpus import EVAL_DIR
from scripts.evaluation.labels import (
    SentenceRow,
    load_proposed,
    load_second,
    load_synthetic,
    sentence_rows,
)
from scripts.evaluation.review import cell

DISAGREEMENTS = EVAL_DIR / "DISAGREEMENTS.md"
FINAL = EVAL_DIR / "labels_final.json"
FINAL_ABOUT = (
    "Final (gold) labels adjudicated by the project owner where labellers A and B disagreed, "
    "plus rows set by rule. Row ids match labels.json. reasons: why each final was set; "
    '"wrong citation" marks a citation error type.'
)
UNCITED_RULE = ("unsupported", "rule: uncited")


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return float("nan")
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    count_a, count_b = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(count_a[k] * count_b[k] for k in count_a) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def _load_final() -> tuple[dict[str, str], dict[str, str]]:
    if not FINAL.exists():
        return {}, {}
    data = json.loads(FINAL.read_text("utf-8"))
    return data["labels"], data["reasons"]


def _save_final(adjudicated: dict[str, tuple[str, str]]) -> None:
    """Write {row: (reason, final)} to labels_final.json."""
    data = {
        "_about": FINAL_ABOUT,
        "by": "project owner",
        "labels": {row: final for row, (_, final) in sorted(adjudicated.items())},
        "reasons": {row: reason for row, (reason, _) in sorted(adjudicated.items())},
    }
    FINAL.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def _read_table() -> dict[str, tuple[str, str]]:
    """{row id: (reason, final)} for every adjudicated row."""
    labels, reasons = _load_final()
    return {row: (reasons.get(row, ""), label) for row, label in labels.items()}


def write_disagreements(updates: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """Rewrite DISAGREEMENTS.md keeping every typed final and reason; `updates` adds or
    replaces {row: (reason, final)}, also for rows where A and B agree (listed after the
    disagreements). Uncited sentences always get the uncited rule."""
    a, b = load_proposed(), load_second()
    if not b["sentences"] and not b["questions"]:
        raise SystemExit('no labels_B.json yet; run: make eval ARGS="import-labels"')
    synthetic = load_synthetic()
    # A's sentence labels: labels.json for real sentences, synthetic.json for injected ones.
    rows = {
        r.row: r
        for answer in load_answers()
        for r in sentence_rows(answer, synthetic, a["sentences"])
    }
    kept = {**_read_table(), **(updates or {})}
    table = [
        "| row | tag | sentence or question | A | B | reason | final |",
        "|---|---|---|---|---|---|---|",
    ]
    pairs: dict[str, list[tuple[str, str]]] = {"real": [], "blatant": [], "subtle": []}
    pairs["questions"] = []
    listed: set[str] = set()
    adjudicated: dict[str, tuple[str, str]] = {}

    def add(row_id: str, tag: str, text: str, label_a: str, label_b: str) -> None:
        reason, final = kept.get(row_id, ("", ""))
        row = rows.get(row_id)
        if row is not None and not row.refs:
            final, reason = UNCITED_RULE
        if final:
            adjudicated[row_id] = (reason, final)
        table.append(
            f"| `{row_id}` | {tag} | {text} | {label_a} | {label_b} | {reason} | {final} |"
        )
        listed.add(row_id)

    for row_id, row in sorted(rows.items()):
        label_a, label_b = row.proposed, b["sentences"].get(row_id)
        if label_a is None or label_b is None:
            continue
        pairs[row.tag].append((label_a, label_b))
        if label_a != label_b:
            add(row_id, row.tag, f"{cell(row.text)} (refs {row.refs or 'none'})", label_a, label_b)
    for qid, label_a in sorted(a["questions"].items()):
        label_b = b["questions"].get(qid)
        if label_b is None:
            continue
        pairs["questions"].append((label_a, label_b))
        if label_a != label_b:
            add(qid, "question", "behaviour", label_a, label_b)
    n_disagree = len(listed)
    for row_id in sorted(set(kept) - listed):
        row = rows.get(row_id)
        if row is not None:
            text = f"{cell(row.text)} (refs {row.refs or 'none'}) — A and B agreed"
            add(row_id, row.tag, text, row.proposed or "", b["sentences"].get(row_id, ""))
        else:
            label_a, label_b = a["questions"].get(row_id, ""), b["questions"].get(row_id, "")
            add(row_id, "question", "behaviour — A and B agreed", label_a, label_b)
    header = [
        "# A vs B disagreements",
        "",
        "A = proposed by an LLM; B = second model (Gemini), labelled blind. **final** is the gold "
        "label (rows left blank are excluded from scoring and counted). Uncited sentences are "
        "`unsupported` by rule (reason `rule: uncited`); rows below the disagreements were "
        "adjudicated although A and B agreed.",
        "",
    ]
    DISAGREEMENTS.write_text("\n".join([*header, *table]) + "\n", "utf-8")
    _save_final(adjudicated)
    report = ["| set | rows | agree | Cohen's kappa |", "|---|---|---|---|"]
    for name, items in pairs.items():
        agree = sum(x == y for x, y in items)
        report.append(f"| {name} | {len(items)} | {agree} | {cohen_kappa(items):.2f} |")
    extra = len(listed) - n_disagree
    return [
        *report,
        f"wrote eval/DISAGREEMENTS.md ({n_disagree} disagreements, {extra} extra) "
        f"and eval/labels_final.json ({len(adjudicated)} finals)",
    ]


def read_final() -> dict[str, str]:
    """Adjudicated labels from eval/labels_final.json."""
    return _load_final()[0]


def read_reasons() -> dict[str, str]:
    """{row: reason} for adjudicated rows (e.g. "wrong citation" marks a real error type)."""
    return _load_final()[1]


REASON_TO_ERROR = {"wrong citation": "wrong_citation"}


@dataclass(frozen=True, slots=True)
class GoldRow:
    row: SentenceRow
    label: str
    error: str | None  # synthetic error type, or a real error found in adjudication


def gold() -> tuple[dict[str, GoldRow], dict[str, str], list[str]]:
    """(gold sentences, gold question behaviours, unresolved rows).

    Sentence rule, in order: a final from adjudication; `unsupported` for any uncited sentence
    (that is how the app treats it); A's label where A and B agree; otherwise unresolved."""
    a, b = load_proposed(), load_second()
    final, reasons = read_final(), read_reasons()
    synthetic = load_synthetic()
    sentences: dict[str, GoldRow] = {}
    unresolved: list[str] = []
    for answer in load_answers():
        for row in sentence_rows(answer, synthetic, a["sentences"]):
            error = row.error or REASON_TO_ERROR.get(reasons.get(row.row, ""))
            label_b = b["sentences"].get(row.row)
            if final.get(row.row):
                label = final[row.row]
            elif not row.refs:
                label = UNCITED_RULE[0]
            elif row.proposed and (label_b is None or label_b == row.proposed):
                label = row.proposed
            else:
                unresolved.append(row.row)
                continue
            sentences[row.row] = GoldRow(row, label, error)
    questions: dict[str, str] = {}
    for qid, label_a in a["questions"].items():
        label_b = b["questions"].get(qid)
        if final.get(qid):
            questions[qid] = final[qid]
        elif label_b is None or label_b == label_a:
            questions[qid] = label_a
        else:
            unresolved.append(qid)
    return sentences, questions, unresolved
