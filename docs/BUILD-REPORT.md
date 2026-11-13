# Build report: rag-eval-gate v0.1.0

Builders: Claude Opus 5.5 (first session, up to `a4f8a8b`) and Claude Fable 5.2 (this
session), 2026-11-12 and 2026-11-13. Local commits only: no remote, no push. Annotated
tag `v0.1.0` on `main`; local branch `demo/degraded-retriever` is `main` plus one commit.

## Folder tree

```
rag-eval-gate/
├── rag.yaml                  pipeline under test (chunking, top_k, models)
├── eval.yaml                 metrics, profiles (local, ci) and thresholds
├── eval/golden.yaml          30 questions with references, sources, evidence
├── data/corpus/              24 Playwright doc pages (Apache-2.0) + SOURCE.md
├── src/rag_eval_gate/        13 modules, 1,862 lines
│   ├── corpus.py  rag.py  llm.py  ollama.py        pipeline and Ollama client
│   ├── metrics.py  judges.py                       RAGAS / DeepEval through Ollama
│   ├── evaluate.py  gate.py  golden.py  config.py  evaluator, gate, config
│   └── cli.py                                      rag-gate index|ask|eval|gate|corpus
├── tests/                    84 unit tests (fake LLM, fake HTTP transport)
├── docs/
│   ├── THRESHOLDS.md               calibration and its limits
│   ├── JUDGE-EMPTY-COMPLETIONS.md  root-cause notes on the judge faults
│   ├── DEMO-PR.md                  the PR to open after publishing
│   ├── REPO-META.md  BUILD-REPORT.md
│   └── results/                    raw output of every run cited in the README
├── .github/workflows/        ci.yml (lint, types, tests, offline smoke, hadolint),
│                             rag-eval.yml (PR gate with sticky comment)
├── Dockerfile  Makefile  pyproject.toml  uv.lock  CHANGELOG.md  LICENSE  .env.example
```

## Tests and static checks

| Check | Result | Evidence |
|---|---|---|
| `uv run pytest` | 84 passed, coverage 98.38 % (gate 80 %) | `docs/results/pytest.txt` |
| `uv run ruff check .` | clean | `docs/results/lint.txt` |
| `uv run ruff format --check .` | 28 files formatted | `docs/results/lint.txt` |
| `uv run mypy` (strict) | clean, 13 source files | `docs/results/lint.txt` |

Unit tests need no model: the generator, the embedder and Ollama's HTTP API are faked.

## Demo

`make demo`, run here as:

```
uv run rag-gate eval --profile ci --unload-every 3 --out results/demo.json
uv run rag-gate gate results/demo.json --baseline docs/results/baseline.json
```

Real run on `main` against Ollama (`qwen3:8b`, `nomic-embed-text`): 8 questions,
108 LLM requests, 22 minutes, 0 failed judge calls (2 empty completions, 2 aborts and
8 runner reloads on the way, no fallback answer). Means: hit_rate 1.000, mrr 1.000,
faithfulness 1.000, answer_relevancy 0.885, context_precision 0.945, context_recall
1.000, hallucination 0.562. The gate passed, exit code 0. Output:
`docs/results/demo-console.txt`, `demo.json`, `demo-gate.md`.

`--unload-every 3` is not part of the `make demo` target; it was added on this machine
because of its memory (see Limitations).

## Measured results

Same 30 questions, corpus, generator and judge; only `rag.yaml` differs.

| metric | baseline (top_k 4, 1200/150) | degraded (top_k 1, 300/50) | threshold | gate on degraded |
|---|---|---|---|---|
| faithfulness | 0.943 | 0.576 | >= 0.85 | fail |
| context_recall | 0.967 | 0.750 | >= 0.85 | fail |
| hit_rate | 0.967 | 0.900 | >= 0.80 | pass |
| mrr | 0.922 | 0.900 | >= 0.75 | pass |
| answer_relevancy | 0.876 | 0.864 | >= 0.70 | pass |
| context_precision | 0.893 | 0.867 | >= 0.70 | pass |
| hallucination (agreement, higher is better) | 0.590 | 0.933 | >= 0.40 | pass |

- The baseline passes all seven checks (`gate-baseline.md`, exit 0); the degraded run
  fails two (`gate-degraded.md`, exit 1).
- Two metrics separate the runs. Four did not, and DeepEval's hallucination score went up
  in the degraded run, because it is the share of contexts the answer agrees with and the
  degraded run has one context per question. The README and `docs/THRESHOLDS.md` say so.
- Baseline: one run, 393 requests, 83 minutes. Degraded: four resumed passes (below).
- Spot check with the fixed client: 3 baseline questions re-scored, 14 of 15 judged scores
  identical.

## What happened during the degraded run

1. First attempt (previous session): every judge call failed with an empty completion.
2. Root cause, from the Ollama server log: the runner raised "Unexpected empty grammar
   stack" on structured requests and Ollama answered HTTP 200 with empty content; the
   client retried with the same seed. Fixed in `8cf7d6a`.
3. Pass 1: 15 questions, then the host memory guard stopped it. From question 7 the
   fallback request was aborted ("token repeat limit reached"). Fixed in `70baf43`.
4. Pass 2: stopped by hand at question 12; all request kinds failed on a runner a few
   minutes old. Runner reload on fault added in `f0c3421`.
5. Pass 3: healthy, stopped by the memory guard at question 18.
6. Pass 4 with `unload_every: 3` (`91cf4a8`): finished, 0 failed judge calls.

Each stop by the memory guard was reported to the orchestrator before resuming. The
server-side cause of the faults is not identified.

## Limitations

- One run per configuration, one seed, one judge, and the judge is the generator's model.
  Run-to-run variance over 30 questions was not measured.
- Thresholds were set after seeing both runs, on the same questions.
- On the 8-question `ci` subset only faithfulness separates the runs (1.000 vs 0.744).
- The degraded result file was assembled over four passes with a client that changed
  between them. The changes affect retries and recovery, not prompts or scoring, but
  passes 1 to 3 did not record whether a fallback answer was used.
- `hit_rate` and `mrr` use page-level labels and are insensitive to chunk size.
- A loaded `qwen3:8b` runner used about 8 GB of private memory on this 16 GB machine.
- An earlier commit message (`91cf4a8`) says the runner's prompt cache grows during a
  run. That was wrong; the measurement and correction are in
  `docs/JUDGE-EMPTY-COMPLETIONS.md` (follow-up 3).

## Not done

- **Nothing was published.** No GitHub repository, no remote, no push.
- **The workflows never ran on GitHub.** `ci.yml` and `rag-eval.yml` are untested there;
  the duration of the PR gate on a hosted CPU runner is to be measured.
- **Docker image not built** (daemon off) and **hadolint not run locally** (its download
  was denied earlier; it runs in CI).
- **The demo PR is not open.** `docs/DEMO-PR.md` describes it.
- **Hosted generators** (Anthropic, OpenAI) are implemented as lazy extras and unit
  tested with fakes; no real call was made.
- **Thinking mode** (`OLLAMA_THINK=true`) was not evaluated.
- **The degraded run on the `ci` profile** was not run as its own 8-question run; the
  first-8 figures are computed from the 30-question result files.
