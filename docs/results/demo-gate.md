<!-- rag-eval-gate -->
### ✅ RAG eval gate passed

Profile `ci`, 8 golden questions, generator `ollama/qwen3:8b`, judge `qwen3:8b`, embeddings `nomic-embed-text`, top_k 4, chunk_size 1200.

| Metric | Baseline | This PR | Δ | Threshold | Status |
|---|---|---|---|---|---|
| faithfulness | 1.000 | 1.000 | +0.000 | >= 0.85 | pass |
| context_recall | 1.000 | 1.000 | +0.000 | >= 0.85 | pass |
| hit_rate | 1.000 | 1.000 | +0.000 | >= 0.80 | pass |
| mrr | 1.000 | 1.000 | +0.000 | >= 0.75 | pass |
| answer_relevancy | 0.872 | 0.885 | +0.013 | >= 0.70 | pass |
| context_precision | 0.955 | 0.945 | -0.010 | >= 0.70 | pass |
| hallucination | 0.562 | 0.562 | +0.000 | >= 0.40 | pass |

Thresholds live in `eval.yaml`; the pipeline under test is `rag.yaml`. All metrics are higher-is-better (DeepEval 4.x scores hallucination as agreement).
