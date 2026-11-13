# Judge calls that came back empty

## Symptom

The first degraded run (top_k 1, chunk_size 300, overlap 50) on 2026-11-12 scored no
LLM-judged metric: every RAGAS and DeepEval call failed with
`OllamaError: ollama returned an empty completion for qwen3:8b`, while answer generation
on the same server kept working.

## Root cause

It is not the prompt, the short contexts or the sampling options. The Ollama server log
for that run (`docs/results/judge-empty-completions-server-log.txt`) shows the runner
raising on the first sampled token of each structured request:

```
slot      iterate: id  0 | task 252 | got exception: Unexpected empty grammar stack after accepting piece: 0 (15)
srv    send_error: task id = 252, error: got exception: Unexpected empty grammar stack after accepting piece: 0 (15)
[GIN] 2026/11/12 - 21:17:44 | 200 |    7.17s |       127.0.0.1 | POST     "/api/chat"
```

Ollama 0.40.16 turns that llama-server exception into HTTP 200 with an empty
`message.content`. On that runner instance the failure was sticky: both times an
unconstrained request (generation) preceded it, the next `format` request worked, and every
other `format` request failed. The log holds 32 failed requests of this kind: 30 from that
runner instance within three minutes, and two isolated ones earlier the same evening.

Two things in the client turned a server fault into a lost run:

1. The empty-completion retry re-sent the request with the **same seed**. The server
   matched the cached prompt (`f_sim_best = 1.000`) and failed again in about 120 ms.
2. There was no path that avoided the grammar, although unconstrained requests still worked.

What was ruled out, by replaying the exact failed sample (`popup-window`, one 300-character
context) against a freshly loaded runner with the unchanged client: all five judges scored
it, with `presence_penalty` 1.5, the JSON schema and seed 42. The one-question repro through
the CLI (`rag-gate eval --only popup-window` with the degraded `rag.yaml`) also passed. The
fault could not be triggered on demand, so the server-side trigger is not identified. One
observation, not a conclusion: the Ollama log reports about 1 GiB of free host RAM during the
failing run.

## Fix (`src/rag_eval_gate/ollama.py`)

`OllamaClient.chat` now handles an empty completion in two steps:

1. retry once with a different seed;
2. for a structured request, send it again without `format`, with the JSON schema appended
   to the prompt, and accept the answer only if it contains a parseable JSON object (two
   attempts, different seeds). The adapter still validates the JSON with the framework's
   pydantic model.

`rag-gate eval` prints how many completions came back empty and how many judge calls were
answered through the fallback, so a run that depended on it is visible.

Unit tests: `tests/test_ollama_llm.py` simulates a server that answers every `format`
request with HTTP 200 and an empty message.

## Verification

- Fallback path, live: with every `format` request forced empty in the client, the five
  judges scored the `popup-window` degraded sample through the unconstrained path
  (6 judge calls answered by the fallback, none failed).
- Baseline spot check with the fixed client: see `docs/results/spotcheck-baseline-console.txt`.

Spot check command (3 baseline questions, unchanged `rag.yaml`, 39 requests, 0 empty
completions, 0 fallback answers):

```
uv run rag-gate eval --only custom-test-id-attribute --only popup-window --only download-save --out results/spotcheck-baseline.json
```

| question | metric | baseline run | spot check |
|---|---|---|---|
| custom-test-id-attribute | faithfulness / answer_relevancy / context_precision / context_recall / hallucination | 1.00 / 0.80 / 0.83 / 1.00 / 0.75 | 1.00 / 0.80 / 0.83 / 1.00 / 0.75 |
| popup-window | same | 1.00 / 0.84 / 1.00 / 1.00 / 0.25 | 1.00 / 0.84 / 0.92 / 1.00 / 0.25 |
| download-save | same | 1.00 / 0.86 / 1.00 / 1.00 / 0.50 | 1.00 / 0.86 / 1.00 / 1.00 / 0.50 |

The baseline judges are unaffected: one of 15 judged scores moved (context_precision on
`popup-window`, 1.00 to 0.92).

## Follow-up: the fallback was aborted (answer_relevancy)

The first full degraded run with the fix above scored 15 questions before the host memory
guard stopped it. From question 7 on, `answer_relevancy` failed 9 times in a row with
`HTTP 500: {"error":"prediction aborted, token repeat limit reached"}`: the grammar fault
came back for that one schema, and the unconstrained replacement request made the model
repeat a token until Ollama aborted it. The client treated that 500 as transient and sent
the same request five times with backoff (about two minutes per question, never successful).
The other four judges kept working.

Change in `OllamaClient.chat`:

- an abort with "token repeat limit reached" is no longer retried unchanged; it moves to
  the next step (`OllamaAbortedError`);
- after two schema-constrained attempts, a structured request tries JSON mode
  (`format: "json"`, schema in the prompt), then twice without `format`, with
  `repeat_penalty` 1.15 and at most 1024 new tokens. Every step uses a new seed;
- `rag-gate eval` also prints the number of aborted completions.

Unit tests cover the sequence with a fake server (`tests/test_ollama_llm.py`). Whether
JSON mode or the repeat penalty avoids the abort on the real server is shown by the
counters of the resumed degraded run in `docs/results/degraded-console.txt`.

## Follow-up 2: reload the runner

The resumed run showed that the two faults are one condition of the runner, not of a
schema: about two minutes after the model was loaded, `faithfulness`, `answer_relevancy`,
`context_precision` and `hallucination` calls all started to fail, schema requests and JSON
mode with the grammar exception and unconstrained requests with the repeat abort, so no
fallback step could answer (questions 9 to 12 of that pass lost 10 of 20 judge calls). In
every observed case a freshly loaded runner answered the same kind of request.

`OllamaClient` therefore has `reload_on_fault` (setting `OLLAMA_RELOAD_ON_FAULT`, default
on): after the first failed attempt of a chat call it asks Ollama to unload the model
(`keep_alive: 0`), so the second attempt runs on a new runner. It costs one model load
(about 30 s here) per fault. `rag-gate eval` prints the number of reloads. On a server
shared with other clients, turn it off.

The server-side cause is still not identified. Both symptoms fit a runner that starts
producing the same invalid token, but that was not verified.
