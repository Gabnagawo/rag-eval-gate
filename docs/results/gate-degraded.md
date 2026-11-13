<!-- rag-eval-gate -->
### ❌ RAG eval gate failed

Profile `local`, 30 golden questions, generator `ollama/qwen3:8b`, judge `qwen3:8b`, embeddings `nomic-embed-text`, top_k 1, chunk_size 300.

| Metric | Baseline | This PR | Δ | Threshold | Status |
|---|---|---|---|---|---|
| faithfulness | 0.943 | 0.576 | -0.367 | >= 0.85 | **FAIL** (below 0.85) |
| context_recall | 0.967 | 0.750 | -0.217 | >= 0.85 | **FAIL** (below 0.85) |
| hit_rate | 0.967 | 0.900 | -0.067 | >= 0.80 | pass |
| mrr | 0.922 | 0.900 | -0.022 | >= 0.75 | pass |
| answer_relevancy | 0.876 | 0.864 | -0.012 | >= 0.70 | pass |
| context_precision | 0.893 | 0.867 | -0.026 | >= 0.70 | pass |
| hallucination | 0.590 | 0.933 | +0.343 | >= 0.40 | pass |

Thresholds live in `eval.yaml`; the pipeline under test is `rag.yaml`. All metrics are higher-is-better (DeepEval 4.x scores hallucination as agreement).
