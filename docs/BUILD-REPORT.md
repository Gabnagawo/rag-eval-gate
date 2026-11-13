# Build report: rag-eval-gate (INCOMPLETE: stopped at the owner's request)

Builder: Claude Opus 5.5 (Claude Code session in `C:\Cerebro`), 2026-11-12.
Local commits only: no remote, no push. **No tag yet.** Work was stopped on request
before the demo comparison, so this is a status note, not the final report.

## Done (committed on `main`)

- Corpus: 24 Playwright docs pages (Apache-2.0, upstream `9a82788`), Python-only, in
  `data/corpus/` (235 chunks at 1200/150). Source and license in `data/`.
- Pipeline (`rag.yaml`): heading-aware chunking, nomic-embed-text with task prefixes,
  cosine top-k 4, qwen3:8b generator. Anthropic and OpenAI are lazy extras.
- Golden set: 30 Q/A items in `eval/golden.yaml`, each evidence-checked against the corpus by tests.
- Metrics: hit_rate and MRR; RAGAS 0.4.3 faithfulness, answer_relevancy, context_precision
  and context_recall; DeepEval 4.3.4 hallucination (in 4.x this is the agreement share, so
  higher is better). All are judged by Ollama qwen3:8b with num_ctx 16384.
- CLI `rag-gate index|ask|eval|gate|corpus`. Evals are resumable, and the gate's PR comment
  has a baseline/PR/Δ table.
- Tests: 73 unit tests, 98.57 % coverage (gate 80); ruff and mypy strict are clean.
- CI workflow (lint, mypy, pytest, offline smoke, hadolint) and the PR gate workflow
  `rag-eval.yml` (installs Ollama, `ci` profile, sticky comment, fails on breach).
  Dockerfile, Makefile, CHANGELOG, `docs/REPO-META.md`.
- **Real baseline run** (30 questions, qwen3:8b generator and judge, 393 LLM requests,
  83 min, 0 failed judge calls). Evidence is in `docs/results/baseline.json` and
  `docs/results/baseline-console.txt`.

  | metric | mean |
  |---|---|
  | hit_rate | 0.967 |
  | mrr | 0.922 |
  | faithfulness | 0.943 |
  | answer_relevancy | 0.876 |
  | context_precision | 0.893 |
  | context_recall | 0.967 |
  | hallucination (agreement, higher is better) | 0.590 |

## Not done

1. **Degraded run.** The config is top_k 1, chunk_size 300, overlap 50 (563 chunks). The
   attempt on 2026-11-12 was stopped: every RAGAS and DeepEval judge call returned
   `OllamaError: ollama returned an empty completion`, while generation worked. A direct
   structured-output call to the same server succeeded at the same time, but a one-question
   repro through the judge (`--only popup-window`) failed again. This needs debugging before
   any degraded numbers exist; the baseline judges worked with the same code. Suspects:
   the short single-chunk contexts and the JSON schema with `presence_penalty` 1.5, or
   `_post` not retrying on an empty body. No degraded results are committed.
2. Branch `demo/degraded-retriever`, with the `rag.yaml` change committed there.
3. Calibrate `eval.yaml` thresholds (baseline passes, degraded fails) and add the `ci`
   profile (limit 8) that the PR workflow and `make demo` use. The `ci` profile does not
   exist yet, so `make demo` and the PR workflow fail with "unknown profile" until it does.
4. README: it is still an untracked stub. It needs the SPEC sections and real Results,
   plus `docs/DEMO-PR.md`.
5. Final `docs/results/pytest.txt` and `lint.txt`, the full build report, then tag `v0.1.0`.
