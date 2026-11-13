# Demo pull request: a retrieval change the gate should block

This describes the pull request to open **after the repository is published**. Nothing
here has run on GitHub yet; the numbers below come from the local runs in
`docs/results/`.

## What the PR is

The local branch `demo/degraded-retriever` is `main` plus one commit that changes three
lines of `rag.yaml`:

```diff
-chunk_size: 1200
-chunk_overlap: 150
-top_k: 4
+chunk_size: 300
+chunk_overlap: 50
+top_k: 1
```

It looks like a cost optimization (a quarter of the context per question) and it does not
break a unit test. The point of the demo is that the eval gate, not a reviewer, shows what
it does to answer quality.

## Steps

1. Publish `main` and wait for the `CI` workflow to pass.
2. Rebase the branch on the published `main` if needed, then push it:
   `git push origin demo/degraded-retriever`.
3. Open a pull request into `main` with the title and body below. Do not merge it.
4. The `RAG eval gate` workflow (`.github/workflows/rag-eval.yml`) starts because
   `rag.yaml` changed. It installs Ollama, pulls `qwen3:8b` and `nomic-embed-text`, runs
   `rag-gate eval --profile ci` (the first 8 golden questions) and `rag-gate gate` against
   `docs/results/baseline.json`.
5. Record the run: duration, the posted comment and the failed check. Put a screenshot of
   the comment in the README and replace the "to be measured" row in Results.
6. Keep the PR open as the demo, with a label such as `demo: do not merge`.

### Title

`Retrieve one small chunk per question (demo: blocked by the eval gate)`

### Body

```markdown
Cuts the context sent to the generator: one 300-character chunk per question instead of
four 1200-character chunks.

This PR is a demonstration and is not meant to be merged. It changes only `rag.yaml`.
The RAG eval gate scores it on the golden set and compares it with the baseline on the
same questions; see the comment below.
```

## Expected result

The workflow uses the `ci` profile, so the comment covers 8 questions. On those 8
questions the local runs gave:

| Metric | Baseline (first 8) | Degraded (first 8) | Threshold | Expected status |
|---|---|---|---|---|
| faithfulness | 1.000 | 0.744 | >= 0.85 | **FAIL** |
| context_recall | 1.000 | 1.000 | >= 0.85 | pass |
| hit_rate | 1.000 | 1.000 | >= 0.80 | pass |
| mrr | 1.000 | 1.000 | >= 0.75 | pass |
| answer_relevancy | 0.871 | 0.913 | >= 0.70 | pass |
| context_precision | 0.955 | 1.000 | >= 0.70 | pass |
| hallucination | 0.562 | 1.000 | >= 0.40 | pass |

So the expected outcome is a failed check with one failing metric, faithfulness. On the
full 30 questions (`local` profile) the same change fails two metrics, faithfulness
(0.576) and context_recall (0.750); the 8-question subset does not show the recall drop.
The full comment for 30 questions is in `docs/results/gate-degraded.md`.

The CI run will not reproduce these values exactly: the runner uses CPU inference, and
the judge samples with a temperature of 0.7. The local spot check re-scored three
baseline questions and 14 of 15 scores were identical, but that is three questions on one
machine.

## What could go wrong on a hosted runner

These are untested; check them on the first run.

- **Time.** The workflow allows 240 minutes. Locally (GPU) a question took 33 to 170
  seconds with one context and about 165 seconds with four. A CPU runner will be several
  times slower. If the run does not fit, lower the `ci` profile's `limit` or move the job
  to a larger runner.
- **Memory.** `qwen3:8b` with `num_ctx` 16384 used about 8 GB of private memory here.
  A standard hosted runner has 16 GB, so it should fit, with little room to spare.
- **Judge faults.** The empty completions described in `docs/JUDGE-EMPTY-COMPLETIONS.md`
  were seen with the Vulkan backend on Windows. Whether they occur on CPU is unknown. The
  gate fails a metric when more than 20 % of its judge calls fail, so a faulty run fails
  loudly instead of passing.
- **Faithfulness close to the threshold.** With 8 questions, one question moves the mean
  by 0.125. The expected 0.744 is 0.106 below the threshold, so a single differently
  judged question would not flip the result, but two could.

## After the demo

Open a second, harmless PR (for example a README typo outside the workflow's `paths`) to
show that the gate does not run when nothing that affects answers changed, and a third
one that edits `eval.yaml` comments only, which runs the gate and passes.
