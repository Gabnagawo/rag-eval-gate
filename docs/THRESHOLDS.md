# How the gate thresholds were set

The thresholds in `eval.yaml` come from two real runs on the same 30 golden questions,
with the same corpus, golden set, generator and judge (`qwen3:8b`), one run per
configuration:

| | `rag.yaml` | evidence |
|---|---|---|
| baseline | top_k 4, chunk_size 1200, overlap 150 (235 chunks) | `docs/results/baseline.json`, `baseline-console.txt` |
| degraded | top_k 1, chunk_size 300, overlap 50 (563 chunks) | `docs/results/degraded.json`, `degraded-console.txt` |

## Measured

| metric | baseline | degraded | delta | questions worse / better | threshold | baseline margin | degraded margin |
|---|---|---|---|---|---|---|---|
| faithfulness | 0.943 | 0.576 | -0.367 | 21 / 1 | >= 0.85 | +0.093 | -0.274 |
| context_recall | 0.967 | 0.750 | -0.217 | 9 / 1 | >= 0.85 | +0.117 | -0.100 |
| hit_rate | 0.967 | 0.900 | -0.067 | 2 / 0 | >= 0.80 | +0.167 | +0.100 |
| mrr | 0.922 | 0.900 | -0.022 | 2 / 1 | >= 0.75 | +0.172 | +0.150 |
| answer_relevancy | 0.876 | 0.864 | -0.012 | 15 / 10 | >= 0.70 | +0.176 | +0.164 |
| context_precision | 0.893 | 0.867 | -0.026 | 3 / 5 | >= 0.70 | +0.193 | +0.167 |
| hallucination (agreement) | 0.590 | 0.933 | +0.343 | 2 / 21 | >= 0.40 | +0.190 | +0.533 |

Result: the baseline passes all seven checks and the degraded run fails two
(`faithfulness` and `context_recall`).

## Rationale

- **Two metrics separate the runs, and only those two gate this change.** With one
  300-character chunk the generator still writes a full answer, so most of its claims
  are no longer supported by the context (faithfulness), and the context covers less of
  the reference answer (context_recall). Both thresholds are 0.85: about 0.1 below the
  baseline, and 0.1 to 0.27 above the degraded run.
- **Five metrics did not separate the runs.** Their thresholds are floors that both runs
  pass. They are kept to catch a collapse (an empty index, a broken prompt), not to judge
  a retrieval change like this one. The floors sit 0.17 to 0.19 below the baseline.
- **hit_rate and mrr barely moved** (two questions lost their answering page). The golden
  set marks a page, not a passage, as the source, so a small chunk from the right page
  counts as a hit even when it does not contain the answer.
- **answer_relevancy and context_precision are within noise** (15 questions worse and 10
  better; 3 worse and 5 better). An answer can address the question without being
  grounded, and a single retrieved chunk from the right page ranks first by definition.
- **hallucination went up in the degraded run.** DeepEval 4.x scores it as the share of
  retrieved contexts the answer agrees with. With four contexts an answer rarely agrees
  with all of them (baseline 0.590); with one context it is 0 or 1 and usually 1 (0.933).
  The metric rewards a smaller context here, which is why it only has a floor.

## The `ci` profile (first 8 questions)

| metric | baseline, first 8 | degraded, first 8 |
|---|---|---|
| faithfulness | 1.000 | 0.744 |
| context_recall | 1.000 | 1.000 |

On this subset only `faithfulness` fails the degraded run (0.744 against 0.85). The
subset exists so the PR workflow fits a hosted runner; the 30-question `local` profile is
the reference.

## Limits of this calibration

- One run per configuration and one judge model. The spot check in
  `docs/JUDGE-EMPTY-COMPLETIONS.md` re-scored three baseline questions and 14 of 15 scores
  were identical, but run-to-run variance over 30 questions was not measured.
- The thresholds were set after seeing both runs, on the same questions they are applied
  to. They describe this pair of configurations; a different change needs its own check.
- 30 questions: one question moves a mean by 0.033.
