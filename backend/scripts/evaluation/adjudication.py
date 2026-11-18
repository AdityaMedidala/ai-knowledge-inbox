"""Adjudication between labeller A (LLM-proposed) and B (second model, blind).

`disagreements` writes eval/DISAGREEMENTS.md: the rows where A and B differ, with a blank
"final" column for the project owner, and returns agreement and Cohen's kappa per set.
"""

from collections import Counter

from scripts.evaluation.answers import load_answers
from scripts.evaluation.corpus import EVAL_DIR
from scripts.evaluation.labels import load_proposed, load_second, load_synthetic, sentence_rows
from scripts.evaluation.review import cell, read_overrides

DISAGREEMENTS = EVAL_DIR / "DISAGREEMENTS.md"


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return float("nan")
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    count_a, count_b = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(count_a[k] * count_b[k] for k in count_a) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def write_disagreements() -> list[str]:
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
    table = ["| row | tag | sentence or question | A | B | final |", "|---|---|---|---|---|---|"]
    pairs: dict[str, list[tuple[str, str]]] = {"real": [], "blatant": [], "subtle": []}
    pairs["questions"] = []
    for row_id, row in sorted(rows.items()):
        label_a, label_b = row.proposed, b["sentences"].get(row_id)
        if label_a is None or label_b is None:
            continue
        pairs[row.tag].append((label_a, label_b))
        if label_a != label_b:
            text = f"{cell(row.text)} (refs {row.refs or 'none'})"
            table.append(f"| `{row_id}` | {row.tag} | {text} | {label_a} | {label_b} |  |")
    for qid, label_a in sorted(a["questions"].items()):
        label_b = b["questions"].get(qid)
        if label_b is None:
            continue
        pairs["questions"].append((label_a, label_b))
        if label_a != label_b:
            table.append(f"| `{qid}` | question | behaviour | {label_a} | {label_b} |  |")
    header = [
        "# A vs B disagreements",
        "",
        "A = proposed by an LLM; B = second model (Gemini), labelled blind. Fill **final** for "
        "each row; it becomes the gold label (rows left blank are excluded from scoring).",
        "",
    ]
    DISAGREEMENTS.write_text("\n".join([*header, *table]) + "\n", "utf-8")
    report = ["| set | rows | agree | Cohen's kappa |", "|---|---|---|---|"]
    for name, items in pairs.items():
        agree = sum(x == y for x, y in items)
        report.append(f"| {name} | {len(items)} | {agree} | {cohen_kappa(items):.2f} |")
    return [*report, f"wrote eval/DISAGREEMENTS.md ({len(table) - 2} disagreements)"]


def read_final() -> dict[str, str]:
    """Adjudicated labels: DISAGREEMENTS.md "final", overridden by REVIEW.md "final"."""
    final = read_overrides(DISAGREEMENTS) if DISAGREEMENTS.exists() else {}
    return {**final, **read_overrides()}
