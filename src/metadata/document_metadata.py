"""Extract document metadata from PPTX and PDF files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentMetadata:
    document_title: str = ""
    author: str = ""
    organization: str = ""
    publication_date: str | None = None
    language: str = "en"


def extract_metadata(path: Path) -> DocumentMetadata:
    ext = path.suffix.lower()
    if ext == ".pptx":
        return _from_pptx(path)
    if ext == ".pdf":
        return _from_pdf(path)
    return DocumentMetadata()


def _from_pptx(path: Path) -> DocumentMetadata:
    from pptx import Presentation

    prs = Presentation(str(path))
    props = prs.core_properties
    title = (props.title or "").strip()
    author = (props.author or "").strip()
    org = (props.category or props.subject or "").strip()
    pub = None
    if props.modified:
        pub = props.modified.date().isoformat()
    elif props.created:
        pub = props.created.date().isoformat()
    return DocumentMetadata(
        document_title=title,
        author=author,
        organization=org,
        publication_date=pub,
    )


def _from_pdf(path: Path) -> DocumentMetadata:
    import fitz

    doc = fitz.open(str(path))
    meta = doc.metadata or {}
    doc.close()
    title = (meta.get("title") or "").strip()
    author = (meta.get("author") or "").strip()
    org = (meta.get("subject") or meta.get("creator") or "").strip()
    pub = (meta.get("creationDate") or meta.get("modDate") or "").strip() or None
    return DocumentMetadata(
        document_title=title,
        author=author,
        organization=org,
        publication_date=pub,
    )
