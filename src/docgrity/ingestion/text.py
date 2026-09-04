"""Convert Confluence storage-format HTML to plain text for hashing/embedding."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        # collapse whitespace within lines, drop empty lines
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def storage_html_to_text(html: str) -> str:
    """Extract readable plain text from Confluence storage-format HTML."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def split_into_chunks(text: str, max_chars: int = 2000) -> list[str]:
    """Split plain text into semantic blocks (paragraph-greedy packing).

    Deterministic: paragraphs are packed into chunks up to ``max_chars``;
    oversized single paragraphs are hard-split.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append("\n".join(current))
                current, size = [], 0
            chunks.extend(para[i : i + max_chars] for i in range(0, len(para), max_chars))
            continue
        if size + len(para) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
