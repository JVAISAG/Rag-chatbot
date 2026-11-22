# RAG evaluation reports

## Research workspace — 21 November 2026

`eval/workspace_set.json` contains six fictional sources (four paper-like and
two article-like) and 37 reviewed synthetic questions: 30 factual, three
multi-source, three unanswerable, and one hostile-source case. It is separate
from the older development smoke set below. Source-level retrieval scores cover
the 34 cases with expected sources; ranks are deduplicated by source.

| Method | Recall@3 | MRR@3 | nDCG@3 | Observed mean seconds |
| --- | ---: | ---: | ---: | ---: |
| Dense | 1.000 | 0.971 | 0.978 | 0.838 |
| BM25 | 0.985 | 0.966 | 0.964 | 0.081 |
| Hybrid RRF | 0.985 | 0.956 | 0.962 | 0.187 |
| Reranked hybrid | 1.000 | 0.971 | 0.978 | 2.203 |

The reproducible command is `python scripts/verify_workspace.py evaluation
--report eval/workspace_results.json`. It creates a temporary PostgreSQL database,
indexes with real models, warms the retrieval stack, then removes the database
and synthetic originals. The report records individual ranks, model versions,
and platform. Hardware: Intel i5-11300H, 8 GB host RAM, retrieval models on CPU.
The run encountered severe Windows RAM compression. Timing differences across
modes are not controlled speed comparisons; see `PERFORMANCE_NOTES.md`.

The default remains reranked hybrid, but this small corpus does not establish
that it universally outperforms dense search. These are retrieval results, not
answer accuracy, citation entailment, or real-paper scientific-domain scores.
Unanswerable cases need abstention review. Add `--answers` to save real model
answers, expected answers, status, and timing for semantic review; successful
structural validation alone must never be treated as a correctness grade.

The separate real 3B GPU summary and Q&A checks passed on their narrow synthetic
passages. The smaller 1B candidate failed factual checks and was not adopted.

### Broader answer audit

The subsequent real-model audit exposed a limitation missed by the one-passage
smoke check. Of the first 27 saved `llama3.2` answers, manual review found seven
usable supported answers, six erroneous refusals despite explicit facts in the
passages, and fourteen `unsupported` results after citation-format validation.
The run was interrupted when Docker encountered resource errors; its checkpoint
is `eval/workspace_answers_llama3b_partial.json`, marked incomplete. These counts
describe an interrupted development run, not a 37-question accuracy score.

Diagnostic prompts showed correct extraction with a single relevant passage but
frequent false refusals with additional unrelated passages. Changing question
placement and relevance instructions improved several cases but did not resolve
all refusals reliably. A subsequent Qwen2.5 3B experiment also failed broader
answer checks and was not adopted.

The release uses Qwen3 4B with `qa-v4`: bounded JSON claims, independently
validated reference numbers, and server-rendered citation markers. Empty claims
must explicitly declare insufficient evidence; that state never carries fabricated
citations. Hyphenated numeric identifiers must appear exactly in their cited
passages; mismatches receive specific repair feedback. At most three focused
checks can select a verbatim excerpt after an abstention. These are explicitly
labeled `quoted_evidence`, validated against their original passage and word/number
boundaries, and may answer only part of a question. Follow-up
generation uses the saved standalone retrieval question. These measures enforce
structure and source boundaries; they cannot prove that a claim is entailed.

`scripts/evaluate_workspace_answers.py` isolates generation using the same
production answer/citation gate and saved real reranked source order, without
loading the CPU retrieval models again. The three unanswerable cases receive the
complete fictional corpus. It records generated text, supporting passage numbers,
expected answers, status, and generation-only time. This replay checks generation;
it does not remeasure retrieval, queue behavior, or database access. Use it for
resource-constrained model comparisons, followed by the live pipeline check:

```powershell
python scripts/evaluate_workspace_answers.py --model MODEL --report eval/workspace_answer_replay.json
```

The corpus is a development/regression set used during diagnosis and selection,
not a held-out benchmark. Correct source retrieval does not by itself establish
answer correctness or citation support.

### Previous qa-v3 generation replay

`eval/workspace_answers_qa3.json` is complete and uses Qwen3 4B, `qa-v3`, a
2048-token context, batch 128, and explicit GPU placement on this host. Engineering
review against the fictional passages found 32 usable supported responses across
34 answerable cases. All three genuinely unanswerable cases abstained, and the
hostile quoted instruction was ignored. The two remaining answerable cases are
recorded explicitly: q26 abstains despite an available cold/warm timing fact;
q31 answers both datasets but misspells `Maple-600` as `Maple-60-0`. Valid reference
numbers do not detect this semantic error. Do not present this report as 100%
correct or as an independent human evaluation. Review identifiers and other
generated claims against their passages before using them.

This final warm generation-only run had a median of about 1.32 seconds over cases
2–37; its longest case was about 2.34 seconds. An earlier cold run took 238 seconds
for its first request under host memory pressure. These figures exclude retrieval,
database, queue, frontend polling, and heavy CPU-model startup. They are diagnostic
observations on tiny synthetic passages, not an interactive latency promise.

### Independent validation corpus

`eval/workspace_validation_set.json` contains six different fictional sources and
32 questions, including three multi-source cases, three missing-answer cases, and
one quoted hostile instruction. Its content was frozen before the first model
run. The 37-question development set remains separate and was used for tuning.
Both retrieval reports carry canonical corpus fingerprints; answer replay refuses
incomplete reports, changed corpora, and unknown rank identities before inference.

The independent real retrieval run scored 29 answerable cases:

| Method | Recall@3 | MRR@3 | nDCG@3 | Observed mean seconds |
| --- | ---: | ---: | ---: | ---: |
| Dense | 1.000 | 1.000 | 1.000 | 0.216 |
| BM25 | 1.000 | 0.966 | 0.974 | 0.094 |
| Hybrid RRF | 1.000 | 1.000 | 0.997 | 0.238 |
| Reranked hybrid | 1.000 | 0.983 | 0.989 | 3.584 |

See `eval/workspace_validation_results.json`. The development and validation runs
used the same CPU models sequentially, with Ollama stopped. Windows still reached
roughly 15 MB free physical RAM. These timings remain observations under changing
memory pressure. Perfect source Recall@3 on this tiny corpus does not establish
perfect answers, universal reranker benefit, or real-paper domain accuracy.

### Completion answer review — 22 November 2026

The final `qa-v4` reports are `eval/workspace_answers_final.json` and
`eval/workspace_validation_answers.json`. Both contain complete runs bound to
their corpus fingerprints. `eval/workspace_answer_review.json` records an
engineering review, per-case judgements, cited source identities, and canonical
hashes of the reviewed reports. It is not independent human grading.

| Corpus | Generated supported answers | Supported quoted excerpts | Correct missing-fact abstentions | False refusals |
| --- | ---: | ---: | ---: | ---: |
| Development, 37 questions | 31 | 2 | 3 | 1 |
| Validation, 32 questions | 29 | 0 | 3 | 0 |

The development dataset-identifier error is repaired: q31 now preserves both
dataset names. q20 and q30 return exact, explicitly labeled excerpts covering
the requested facts. q26 still declines an available cold/warm timing fact in
the full run, despite returning it in one earlier diagnostic. It is counted as
a false refusal. General evidence-selection instruction experiments did not
reliably remove that refusal and were not adopted. No corpus wording or expected
answer was changed to turn it into a pass. Both hostile-source cases were ignored.

The validation answers contain style limitations separate from factual support:
v15 is a terse numeric reply, and v19 adds an unrequested but
source-supported RRF constant. Quoted excerpts can be partial, so the UI labels
them explicitly. Source identities and literal identifier checks are narrower
than semantic entailment; the review does not guarantee arbitrary future answers.

The final development run's first generation took 75.42 seconds cold, followed
by a 1.49-second median for the remaining cases. The validation run reused the
warm model and had a 1.30-second median after its first case. These measurements
exclude retrieval, queueing, database access, and browser polling.

## Legacy development smoke benchmark

Measured over 12 questions from `demo_set.json` with an isolated index.

Embedding model: `all-MiniLM-L6-v2` (CPU). Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU).

| Method | Recall@1 | MRR@1 | nDCG@1 | Mean retrieval seconds |
|---|---:|---:|---:|---:|
| dense | 0.917 | 0.917 | 0.917 | 0.011 |
| bm25 | 1.000 | 1.000 | 1.000 | 0.000 |
| hybrid | 0.917 | 0.917 | 0.917 | 0.012 |
| hybrid_rrf | 0.917 | 0.917 | 0.917 | 0.011 |
| hybrid_rrf_rerank | 1.000 | 1.000 | 1.000 | 0.054 |

One expected document is labelled per question; recall is therefore document hit rate. MRR is truncated at k. This small synthetic corpus is a smoke benchmark, not a held-out quality claim. Generation faithfulness, citation support, unanswerable questions, and production latency are not evaluated here.
