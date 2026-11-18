"""eval/REVIEW.md: one row per question and per sentence with labeller A's and B's labels and a
"final" column. `read_overrides` parses "final" back, so adjudication is done by editing
markdown only (DISAGREEMENTS.md lists just the rows where A and B differ)."""

import re
from pathlib import Path
from typing import Any

from scripts.evaluation.answers import load_answers
from scripts.evaluation.corpus import EVAL_DIR
from scripts.evaluation.labels import (
    SentenceRow,
    load_proposed,
    load_second,
    load_synthetic,
    sentence_rows,
)
from scripts.evaluation.store import Question, load_eval_set

REVIEW = EVAL_DIR / "REVIEW.md"
BEHAVIOURS = {
    "answerable": "correct | incomplete | wrong | refused",
    "multi_source": "correct | incomplete | wrong | refused",
    "conflicting": "flags_conflict | picks_right | picks_wrong | refused",
    "injection": "resisted | obeyed",
    "near_miss": "refused | partly_answered | answered",
    "out_of_scope": "n/a (no answer generated: refused at the gate)",
}
_ROW = re.compile(r"^\|\s*`([a-z]\d{2}(?:\.\d+)?)`\s*\|.*\|\s*([^|]*?)\s*\|\s*$")


def cell(text: str | None) -> str:
    return " ".join((text or "").replace("|", "\\|").split())


def _question_table(
    questions: list[Question],
    answers: dict[str, Any],
    proposed: dict[str, str],
    second: dict[str, str],
) -> list[str]:
    lines = [
        "## Questions",
        "",
        "Behaviour of the cached answer. Allowed labels per kind: "
        + "; ".join(f"**{k}**: {v}" for k, v in BEHAVIOURS.items()),
        "",
        "| id | split | kind | question | expected | answer (first 200 chars) | A | B | final |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in questions:
        answer = answers.get(q.id, {}).get("answer", "")
        lines.append(
            f"| `{q.id}` | {q.split} | {q.kind} | {cell(q.question)} | "
            f"{cell(q.expected_answer)} | {cell(answer[:200])} | "
            f"{proposed.get(q.id, '')} | {second.get(q.id, '')} |  |"
        )
    return [*lines, ""]


def _answer_section(
    answer: dict[str, Any], rows: list[SentenceRow], split: str, second: dict[str, str]
) -> list[str]:
    cited = sorted({ref for row in rows for ref in row.refs})
    lines = [f"### `{answer['id']}` · {answer['kind']} · {split} · mode {answer['mode']}", ""]
    lines += [f"**Q:** {answer['question']}", "", "<details><summary>Cited sources</summary>", ""]
    for source in answer["sources"]:
        if source["ref"] in cited:
            where = source["item"] + (f" > {source['section']}" if source["section"] else "")
            lines += [f"**[{source['ref']}] {where}**", "", f"> {cell(source['text'])}", ""]
    lines += ["</details>", ""]
    lines += [
        "| row | tag | error | sentence | refs | A | B | final |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        refs = ",".join(map(str, row.refs)) or "—"
        lines.append(
            f"| `{row.row}` | {row.tag} | {row.error or ''} | {cell(row.text)} | {refs} | "
            f"{row.proposed or ''} | {second.get(row.row, '')} |  |"
        )
    return [*lines, ""]


def write_review() -> str:
    _, questions = load_eval_set()
    answers = {a["id"]: a for a in load_answers()}
    proposed = load_proposed()
    second = load_second()
    synthetic = load_synthetic()
    splits = {q.id: q.split or "?" for q in questions}
    sections: list[str] = []
    tags = {"real": 0, "blatant": 0, "subtle": 0}
    for answer in answers.values():
        rows = sentence_rows(answer, synthetic, proposed["sentences"])
        for row in rows:
            tags[row.tag] += 1
        sections += _answer_section(answer, rows, splits[answer["id"]], second["sentences"])
    n_sentences = sum(tags.values())
    header = [
        "# Label review",
        "",
        "Labellers: **A** = proposed by an LLM; **B** = labelled independently and blind by a "
        "second model (Gemini) from `eval/blind/`; **final** = adjudicated by the project owner. "
        "Fill **final** to set a row's gold label. Blank: A's label is used where A and B agree; "
        "rows where they disagree stay unresolved and are excluded from scoring (and counted).",
        "",
        "Sentence labels: `supported` | `partial` | `unsupported`, judged against the cited "
        "source text only (faithfulness, not world truth). Uncited sentences are labelled on "
        "content but never sent to a verifier.",
        "",
        f"Rows to review: **{len(questions)} questions** and **{n_sentences} sentences** "
        f"({tags['real']} real, {tags['blatant']} blatant, {tags['subtle']} subtle).",
        "",
    ]
    lines = [
        *header,
        *_question_table(questions, answers, proposed["questions"], second["questions"]),
    ]
    lines += ["## Sentences", "", *sections]
    REVIEW.write_text("\n".join(lines), encoding="utf-8")
    return f"wrote eval/REVIEW.md: {len(questions)} questions, {n_sentences} sentences {tags}"


def read_overrides(path: Path = REVIEW) -> dict[str, str]:
    """{row or question id: label} for every non-blank "final" (last) cell."""
    overrides = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match and match.group(2):
            overrides[match.group(1)] = match.group(2).strip("` ")
    return overrides
