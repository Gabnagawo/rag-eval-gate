<!-- rag-eval-gate -->
### ✅ RAG eval gate passed

Profile `local`, 30 golden questions, generator `ollama/qwen3:8b`, judge `qwen3:8b`, embeddings `nomic-embed-text`, top_k 4, chunk_size 1200.

| Metric | Value | Threshold | Status |
|---|---|---|---|
| faithfulness | 0.943 | >= 0.85 | pass |
| context_recall | 0.967 | >= 0.85 | pass |
| hit_rate | 0.967 | >= 0.80 | pass |
| mrr | 0.922 | >= 0.75 | pass |
| answer_relevancy | 0.876 | >= 0.70 | pass |
| context_precision | 0.893 | >= 0.70 | pass |
| hallucination | 0.590 | >= 0.40 | pass |

Thresholds live in `eval.yaml`; the pipeline under test is `rag.yaml`. All metrics are higher-is-better (DeepEval 4.x scores hallucination as agreement).
