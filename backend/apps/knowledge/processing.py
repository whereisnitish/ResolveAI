"""Extraction, normalization and chunking for knowledge sources."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from pypdf import PdfReader

CHUNK_TARGET_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150
MAX_EXTRACTED_CHARS = 2_000_000


class ExtractionError(ValueError):
    pass


@dataclass
class Section:
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def extract_pdf(data: bytes) -> list[Section]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("Encrypted PDFs are not supported.")
        sections = []
        for number, page in enumerate(reader.pages, start=1):
            text = normalize(page.extract_text() or "")
            if text:
                sections.append(Section(text, {"page": number}))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("The PDF could not be read.") from exc
    if not sections:
        raise ExtractionError("No text found in the PDF (scanned PDFs need OCR, which isn't supported yet).")
    return sections


def extract_text_file(data: bytes) -> list[Section]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = normalize(text)
    if not text:
        raise ExtractionError("The file is empty.")
    return [Section(text)]


def extract_html(html: bytes | str, url: str = "") -> tuple[str, list[Section]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
        tag.decompose()
    title = normalize(soup.title.get_text()) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalize(main.get_text("\n"))
    if not text:
        raise ExtractionError("No readable text found at this URL.")
    return title[:200], [Section(text, {"url": url})]


def faq_sections(items: list[dict[str, str]]) -> list[Section]:
    return [
        Section(f"Q: {normalize(i['question'])}\nA: {normalize(i['answer'])}", {"faq_index": n})
        for n, i in enumerate(items)
        if i.get("question") and i.get("answer")
    ]


def chunk_sections(sections: list[Section]) -> list[Section]:
    """Split into ~CHUNK_TARGET_CHARS chunks on paragraph/sentence boundaries with overlap.

    FAQ entries are never merged or split (one Q/A per chunk keeps answers precise).
    """
    chunks: list[Section] = []
    for section in sections:
        if "faq_index" in section.metadata or len(section.text) <= CHUNK_TARGET_CHARS:
            chunks.append(section)
            continue
        units = re.split(r"(?<=\n\n)|(?<=[.!?])\s+", section.text)
        current = ""
        for unit in units:
            if not unit.strip():
                continue
            if len(current) + len(unit) > CHUNK_TARGET_CHARS and current:
                chunks.append(Section(current.strip(), dict(section.metadata)))
                current = current[-CHUNK_OVERLAP_CHARS:] + " "
            while len(unit) > CHUNK_TARGET_CHARS:  # pathological long run without breaks
                chunks.append(Section(unit[:CHUNK_TARGET_CHARS], dict(section.metadata)))
                unit = unit[CHUNK_TARGET_CHARS - CHUNK_OVERLAP_CHARS :]
            current += unit + " "
        if current.strip():
            chunks.append(Section(current.strip(), dict(section.metadata)))
    return chunks


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
