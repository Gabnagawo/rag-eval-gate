# Corpus source

The pages in this folder are a snapshot of the Playwright documentation, reduced to the
content that applies to Python.

- Upstream: https://github.com/microsoft/playwright, folder `docs/src`
- Commit: `9a82788d83cf91d8262e65a432b9bf93dc5418a7` (2026-11-12)
- License: Apache License 2.0, copyright Microsoft Corporation. See
  [../LICENSE-playwright-docs.txt](../LICENSE-playwright-docs.txt).
- Changes: sections and code blocks for JavaScript, Java and .NET were removed, async Python
  variants were removed, and API references such as `[`method: Page.getByRole`]` were
  rewritten as `page.get_by_role`. The transformation is `rag_eval_gate.corpus.clean_markdown`.

Reproduce:

```bash
uv run rag-gate corpus fetch raw-docs --ref 9a82788d83cf91d8262e65a432b9bf93dc5418a7
uv run rag-gate corpus build raw-docs
```
