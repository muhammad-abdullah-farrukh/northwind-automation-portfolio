"""File type detection and PDF text-layer reading (pdfplumber)."""

import io
from dataclasses import dataclass

import pdfplumber

IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
}


class DocumentError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PdfText:
    text: str
    pages: int


def detect_type(content: bytes) -> str:
    if content[:1024].lstrip().startswith(b"%PDF-"):
        return "application/pdf"
    for magic, kind in IMAGE_MAGIC.items():
        if content.startswith(magic):
            return kind
    return "application/octet-stream"


def read_pdf_text(content: bytes, max_pages: int) -> PdfText:
    """Blocking; call through a threadpool. Raises DocumentError with an HTTP status."""
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = len(pdf.pages)
            if pages > max_pages:
                raise DocumentError(413, f"document has {pages} pages; sync extraction handles up to {max_pages} (use /v1/jobs)")
            texts = [page.extract_text() or "" for page in pdf.pages]
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many types for broken/encrypted files
        raise DocumentError(422, f"could not read PDF ({type(exc).__name__})") from exc
    if pages > 1:
        text = "\n\n".join(f"--- page {i} ---\n{t}" for i, t in enumerate(texts, 1))
    else:
        text = texts[0] if texts else ""
    return PdfText(text=text, pages=pages)
