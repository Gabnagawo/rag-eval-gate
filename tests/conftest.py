from __future__ import annotations

from pathlib import Path

import pytest

from rag_eval_gate.config import RagConfig

ROOT = Path(__file__).resolve().parents[1]

PAGE_A = """\
# Screenshots

## Full page screenshots

Full page screenshot is a screenshot of a full scrollable page.

```python
page.screenshot(path="screenshot.png", full_page=True)
```

## Element screenshot

Sometimes it is useful to take a screenshot of a single element.
"""

PAGE_B = """\
# Downloads

## Introduction

Downloaded files are deleted when the browser context that produced them is closed.

```python
download.save_as("/path/" + download.suggested_filename)
```
"""


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "screenshots.md").write_text(PAGE_A, encoding="utf-8")
    (d / "downloads.md").write_text(PAGE_B, encoding="utf-8")
    (d / "SOURCE.md").write_text("# not a page\n", encoding="utf-8")
    return d


@pytest.fixture
def rag_cfg(corpus_dir: Path) -> RagConfig:
    return RagConfig(corpus_dir=corpus_dir, chunk_size=200, chunk_overlap=20, top_k=2)
