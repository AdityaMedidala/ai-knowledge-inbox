## Headline

- **Cosine gate:** set `RELEVANCE_MIN_PARTIAL` to about **0.625–0.65** for bge-small. That refuses every out-of-scope question (max 0.605) and loses one answerable question (a18, 0.588). No threshold separates the near-misses: they score 0.71–0.80, inside the answerable range of 0.59–0.89. Refusing them takes the LLM, which got all 10 right in the frozen answers: each one said the sources don't cover it, or (n08) gave the 9:45 weekday time the note does state.
- **Verifiers:** none of the three let an unsupported sentence through. Agreement is 96% (Groq), 96% (Jev) and 98% (Jev + escalation). With 57 scored sentences, one sentence is about 2 points, so **Jev does not measurably beat Groq on accuracy.** It is faster (median about 480 ms vs 970 ms, p95 about 630 ms vs 5.7 s), about 6× cheaper, and had no failed calls (Groq: 1 of 36 in its second run). Escalation re-checked 4 sentences and fixed 1 (a15).

## Method and caveats

- 8 notes (one planted with a wrong "500 pages" figure) and 42 questions: 24 answerable, 2 on the planted note, 10 near-miss, 6 out of scope.
- Gate: the best cosine similarity among the top 5 chunks, measured with the gate disabled. A question counts as answered wrongly if it should be refused, or if none of its expected items is among the sources the LLM sees.
- Verifiers: the answers were generated once with Groq (`openai/gpt-oss-120b`) and frozen, then hand-labelled per sentence against the cited sources (faithfulness, not world truth).
  - Real answers were almost all supported, so 25 labelled sentences were injected: contradicted, invented or overreaching claims, each with a citation.
  - Most of the 20 unsupported sentences are therefore blatant. Subtle errors are under-tested.
- Results vary between runs. Groq's two runs disagreed with the labels on different sentences, and Jev's top probability for p02 was 0.78 in one run and 0.81 in the other, either side of the 0.8 escalation threshold.
- Planted note: verification checks faithfulness, not truth. In Groq's first run it marked "runs at 500 pages [2]" (citing the planted note) as unsupported, using knowledge outside the cited source. Jev accepted it as supported, which is the strict reading.
- Cost: Jev's figure is OpenRouter's `usage.cost`. Groq's is tokens × $0.15 / $0.60 per million tokens (third-party price listings; check Groq's pricing page).
