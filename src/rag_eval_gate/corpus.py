"""The document corpus: a Python-only snapshot of the Playwright docs, and its chunking.

The upstream Markdown (microsoft/playwright ``docs/src``, Apache-2.0) is written for
four languages at once. :func:`clean_markdown` keeps what a Python user would read:
sections marked ``* langs:`` without ``python`` are dropped, as are code blocks in
other languages and the async Python variants, and API references such as
``[`method: Page.getByRole`]`` become ``page.get_by_role``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

PLAYWRIGHT_REPO = "microsoft/playwright"
DEFAULT_PAGES = (
    "actionability", "auth", "browser-contexts", "debug", "dialogs", "downloads",
    "emulation", "evaluating", "events", "frames", "input", "intro-python", "locators",
    "mock", "navigations", "network", "pages", "pom", "running-tests-python",
    "screenshots", "test-assertions-csharp-java-python", "test-runners-python",
    "trace-viewer-intro-java-python", "writing-tests-python",
)  # fmt: skip
KEEP_FENCES = {"python", "py", "bash", "sh", "shell", "txt", "html", "json", "ini", "toml", "yaml"}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LANGS_RE = re.compile(r"^\*\s*langs:\s*(.+)$")
_FENCE_RE = re.compile(r"^(\s*)```\s*([\w-]*)\s*(\w*)")
_API_REF_RE = re.compile(
    r"\[`(method|property|event|class|param|option|release):\s*([^`]+)`\](\([^)]*\))?"
)
_LINK_REF_RE = re.compile(r"\[([^\]]+)\]\((?!https?://)[^)]*\)")
_COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _api_ref(match: re.Match[str]) -> str:
    kind, ref = match.group(1), match.group(2).strip()
    if kind == "class":
        return f"`{ref}`"
    parts = ref.split(".")
    if len(parts) >= 2:
        owner = _snake(parts[0])
        member = ".".join(_snake(p) for p in parts[1:])
        return f"`{owner}.{member}`" if kind in {"method", "property"} else f"`{member}`"
    return f"`{_snake(ref)}`"


def clean_markdown(text: str) -> str:
    """Reduce one multi-language Playwright doc page to its Python content."""
    lines = _COMMENT_RE.sub("", text).splitlines()
    title = ""
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        for line in lines[1:end]:
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("\"'")
        lines = lines[end + 1 :]

    out: list[str] = [f"# {title}", ""] if title else []
    skip_level: int | None = None  # inside a section for other languages
    fence: str | None = None  # inside a code block: "keep" or "drop"
    i = 0
    while i < len(lines):
        line = lines[i]
        if fence is not None:
            if line.lstrip().startswith("```"):
                if fence == "keep" and skip_level is None:
                    out.append(line)
                fence = None
            elif fence == "keep" and skip_level is None:
                out.append(line)
            i += 1
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None:
                langs = _next_langs(lines, i + 1)
                if langs is not None and "python" not in langs:
                    skip_level = level
                    i += 1
                    continue
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            indent = fence_match.group(1)
            lang, variant = fence_match.group(2).lower(), fence_match.group(3).lower()
            keep = (lang in KEEP_FENCES or not lang) and variant != "async"
            fence = "keep" if keep else "drop"
            if keep and skip_level is None:
                out.append(f"{indent}```{lang}" if lang else f"{indent}```")
            i += 1
            continue
        if skip_level is None and not _LANGS_RE.match(line.strip()):
            line = _API_REF_RE.sub(_api_ref, line)
            line = _LINK_REF_RE.sub(r"\1", line)
            if not line.strip().startswith("!["):
                out.append(line.rstrip())
        i += 1
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return cleaned + "\n"


def _next_langs(lines: Sequence[str], start: int) -> set[str] | None:
    for line in lines[start : start + 3]:
        match = _LANGS_RE.match(line.strip())
        if match:
            return {lang.strip() for lang in match.group(1).split(",")}
        if line.strip():
            return None
    return None


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    heading: str
    text: str

    def embed_text(self) -> str:
        """What gets embedded: the page and section path give short chunks their topic."""
        return f"{self.heading}\n{self.text}"


def load_corpus(corpus_dir: Path) -> dict[str, str]:
    """``{file stem: markdown}`` for every ``*.md`` page in the corpus directory."""
    pages = {p.stem: p.read_text(encoding="utf-8") for p in sorted(corpus_dir.glob("*.md"))}
    pages.pop("SOURCE", None)
    if not pages:
        raise FileNotFoundError(f"no corpus pages in {corpus_dir}")
    return pages


def chunk_page(source: str, markdown: str, chunk_size: int, overlap: int) -> list[Chunk]:
    """Split a page at headings, then pack paragraphs into chunks of about ``chunk_size``.

    Code blocks are never split. A paragraph longer than ``chunk_size`` is cut with
    ``overlap`` characters repeated across the cut.
    """
    if chunk_size < 100 or not 0 <= overlap < chunk_size:
        raise ValueError("need chunk_size >= 100 and 0 <= overlap < chunk_size")
    sections: list[tuple[str, list[str]]] = []
    path: list[str] = []
    title = source
    block: list[str] = []
    for para in _paragraphs(markdown):
        heading = _HEADING_RE.match(para)
        if heading:
            if block:
                sections.append((" > ".join([title, *path]), block))
                block = []
            level, text = len(heading.group(1)), heading.group(2).strip()
            if level == 1:
                title, path = text, []
            else:
                path = [*path[: max(level - 2, 0)], text]
            continue
        block.append(para)
    if block:
        sections.append((" > ".join([title, *path]), block))

    chunks: list[Chunk] = []
    for section_path, paras in sections:
        for text in _pack(paras, chunk_size, overlap):
            chunks.append(Chunk(f"{source}#{len(chunks)}", source, section_path, text))
    return chunks


def _paragraphs(markdown: str) -> Iterable[str]:
    current: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
            if not in_fence:
                yield "\n".join(current).strip()
                current = []
            continue
        if not in_fence and (not line.strip() or _HEADING_RE.match(line)):
            if current:
                yield "\n".join(current).strip()
                current = []
            if line.strip():
                yield line.strip()
            continue
        current.append(line)
    if current:
        yield "\n".join(current).strip()


def _pack(paras: list[str], size: int, overlap: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for para in paras:
        pieces = [para]
        if len(para) > size and not para.startswith("```"):
            step = size - overlap
            pieces = [para[i : i + size] for i in range(0, len(para) - overlap, step)]
        for piece in pieces:
            if buf and len(buf) + len(piece) + 2 > size:
                out.append(buf)
                buf = ""
            buf = f"{buf}\n\n{piece}" if buf else piece
    if buf:
        out.append(buf)
    return out


def chunk_corpus(pages: dict[str, str], chunk_size: int, overlap: int) -> list[Chunk]:
    return [c for src, md in pages.items() for c in chunk_page(src, md, chunk_size, overlap)]


def corpus_sha256(pages: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(pages):
        digest.update(name.encode() + b"\0" + pages[name].encode() + b"\0")
    return digest.hexdigest()


def build_corpus(raw_dir: Path, out_dir: Path, pages: Iterable[str] = DEFAULT_PAGES) -> list[Path]:
    """Clean raw upstream pages from ``raw_dir`` into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in pages:
        raw = (raw_dir / f"{name}.md").read_text(encoding="utf-8")
        target = out_dir / f"{name}.md"
        target.write_text(clean_markdown(raw), encoding="utf-8", newline="\n")
        written.append(target)
    return written
