from __future__ import annotations

from pathlib import Path

import pytest

from rag_eval_gate.corpus import (
    build_corpus,
    chunk_corpus,
    chunk_page,
    clean_markdown,
    corpus_sha256,
    load_corpus,
)
from tests.conftest import PAGE_A, ROOT

RAW = """\
---
id: demo
title: "Demo page"
---

## Intro

Use [`method: Page.getByRole`] and [`class: Locator`], see [locators](./locators.md).
Also [`option: Locator.filter.visible`] and [`event: Page.dialog`] and [`method: click`].
<!-- hidden comment -->
![image](https://example.com/x.png)

```js
await page.click('x');
```

```python async
await page.click("x")
```

```python sync
page.click("x")
```

  ```java
  page.click("x");
  ```

## Only for JS
* langs: js

Text for JavaScript users.

### Nested JS section

More JS text.

## For Python too
* langs: java, python

Python text with [external](https://playwright.dev) link.

```bash
pip install pytest-playwright
```
"""


def test_clean_markdown_keeps_python_content() -> None:
    out = clean_markdown(RAW)
    assert out.startswith("# Demo page\n")
    assert "`page.get_by_role`" in out
    assert "`Locator`" in out
    assert "see locators." in out
    assert "`filter.visible`" in out
    assert "`dialog`" in out
    assert "`click`" in out
    assert 'page.click("x")' in out
    assert "await" not in out
    assert "```js" not in out
    assert "java" not in out.lower().replace("java, python", "")
    assert "JavaScript users" not in out
    assert "More JS text" not in out
    assert "Python text with [external](https://playwright.dev) link." in out
    assert "pip install pytest-playwright" in out
    assert "langs:" not in out
    assert "hidden comment" not in out
    assert "![image]" not in out


def test_chunk_page_paths_and_code_blocks() -> None:
    chunks = chunk_page("screenshots", PAGE_A, chunk_size=120, overlap=10)
    assert [c.heading for c in chunks] == [
        "Screenshots > Full page screenshots",
        "Screenshots > Full page screenshots",
        "Screenshots > Element screenshot",
    ]
    assert chunks[1].text.startswith("```python")
    assert chunks[1].text.endswith("```")
    assert chunks[0].id == "screenshots#0"
    assert chunks[0].embed_text().startswith("Screenshots > Full page screenshots\n")


def test_long_paragraphs_are_cut_with_overlap() -> None:
    text = "# T\n\n## S\n\n" + "word " * 100
    chunks = chunk_page("p", text, chunk_size=100, overlap=20)
    assert len(chunks) > 3
    assert all(len(c.text) <= 100 for c in chunks)
    assert chunks[0].text[-20:] == chunks[1].text[:20]


def test_chunk_size_validation() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_page("p", "x", chunk_size=50, overlap=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_page("p", "x", chunk_size=200, overlap=200)


def test_load_corpus_skips_source_file(corpus_dir: Path, tmp_path: Path) -> None:
    pages = load_corpus(corpus_dir)
    assert sorted(pages) == ["downloads", "screenshots"]
    assert len(chunk_corpus(pages, 200, 20)) >= 3
    assert corpus_sha256(pages) == corpus_sha256(dict(reversed(pages.items())))
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "missing")


def test_build_corpus(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "demo.md").write_text(RAW, encoding="utf-8")
    written = build_corpus(raw, tmp_path / "out", pages=["demo"])
    assert written[0].read_text(encoding="utf-8").startswith("# Demo page")


def test_committed_corpus() -> None:
    pages = load_corpus(ROOT / "data" / "corpus")
    assert len(pages) == 24
    fences = {line.strip() for md in pages.values() for line in md.splitlines()}
    assert not fences & {"```js", "```java", "```csharp", "```python async"}
    assert len(chunk_corpus(pages, 1200, 150)) == 235
