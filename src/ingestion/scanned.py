"""Offline extraction for documents that have no parseable text: PDF, JPEG/PNG, TIFF.

Three backends, tried cheapest first, each optional and bounded. Nothing here needs the network,
and a missing backend degrades to a typed quarantine reason instead of a crash:

  1. ``pdf-text-layer``  pypdf — most "scanned" PDFs in practice still carry a text layer.
  2. ``exif``            Pillow — image descriptions, comments and XMP often hold a name.
  3. ``ocr``             pytesseract + the tesseract binary — pixels only, bounded pages/DPI.

The output is a ``Scan``: extracted text, the backend that produced it, and notes that are safe to
report (never content).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

MAX_PAGES = 5
MAX_CHARS = 200_000
OCR_DPI = 200
OCR_TIMEOUT_S = 20


@dataclass
class Scan:
    text: str = ""
    backend: str = ""
    pages: int = 0
    notes: list[str] = field(default_factory=list)   # reason codes, never values

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


def plausible_text(text: str) -> bool:
    """Reject carved nonsense: a compressed image stream inflates to bytes that look like text.

    A real document has mostly printable characters, a healthy share of letters and words of
    ordinary length. Anything else is binary and must be quarantined, never released.
    """
    import re

    stripped = text.strip()
    if len(stripped) < 3:
        return False
    allowed = set(".,:;/-()[]#%+*'&\"!?\n\t ")
    printable = sum(1 for char in stripped
                    if char.isalnum() or char.isspace() or char in allowed)
    ratio = printable / len(stripped)
    letters = sum(1 for char in stripped if char.isalpha()) / len(stripped)
    words = re.findall(r"[A-Za-z\u0900-\u097F]{2,}", text)
    if not words:
        return False
    mean_word = sum(len(word) for word in words) / len(words)
    return ratio >= 0.90 and letters >= 0.25 and mean_word <= 20


def _bounded(text: str) -> str:
    text = text.replace("\x00", " ")
    return text[:MAX_CHARS]


# ── PDF ──────────────────────────────────────────────────────────────────────
def scan_pdf(path: Path) -> Scan:
    """PDF ladder: text layer -> raw stream carve -> OCR of rendered pages -> honest failure.

    Every step is attempted; none of them may raise. A truncated PDF is a normal input here, not
    an error condition.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return Scan(notes=["unreadable"])

    scan = Scan(backend="pdf-text-layer")
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        PdfReader = None  # type: ignore
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path), strict=False)
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception:
                    return Scan(notes=["pdf_encrypted"])
            chunks: list[str] = []
            for page in reader.pages[:MAX_PAGES]:
                try:
                    chunks.append(page.extract_text() or "")
                except Exception:
                    scan.notes.append("page_extract_failed")
            scan.pages = min(len(reader.pages), MAX_PAGES)
            scan.text = _bounded("\n".join(chunks))
        except Exception:
            scan.notes.append("pdf_parser_failed")

    if not scan.ok:
        carved = _pdf_carve(raw)
        if carved.strip():
            return Scan(text=_bounded(carved), backend="pdf-raw-stream", pages=1,
                        notes=scan.notes)

    if not scan.ok:
        rendered = _render_pdf_pages(path)
        if rendered:
            ocr = _ocr_images(rendered, backend="pdf-ocr")
            ocr.pages = min(len(rendered), MAX_PAGES)
            ocr.notes = scan.notes + ocr.notes
            if ocr.ok:
                return ocr

    if not scan.ok:
        scan.notes.append("no_text_layer")
    return scan


def _pdf_carve(raw: bytes) -> str:
    """Last-resort text recovery for PDFs a parser refuses: inflate streams, read text operators.

    Hand-built and truncated PDFs are common in the chaos set; the text operators are still there
    even when the cross-reference table is unusable.
    """
    import re
    import zlib

    pieces: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        blob = match.group(1)
        try:
            blob = zlib.decompress(blob)
        except Exception:
            pass
        for literal in re.finditer(rb"\((?:\\.|[^()\\])*\)", blob):
            value = literal.group(0)[1:-1]
            value = re.sub(rb"\\([()\\])", rb"\1", value)
            if len(value) >= 2:
                pieces.append(value.decode("latin-1", "ignore"))
        for encoded in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>", blob):
            digits = re.sub(rb"\s", b"", encoded.group(1))
            if len(digits) % 2:
                continue
            try:
                data = bytes.fromhex(digits.decode("ascii"))
            except ValueError:
                continue
            if data[:2] == b"\xfe\xff":
                piece = data[2:].decode("utf-16-be", "ignore")
            elif data and all(byte == 0 for byte in data[0::2]):
                piece = data.decode("utf-16-be", "ignore")
            else:
                piece = data.decode("latin-1", "ignore")
            if len(piece.strip()) >= 2:
                pieces.append(piece)
    kept = [piece for piece in dict.fromkeys(pieces) if plausible_text(piece)]
    return "\n".join(kept)


def _printable_runs(raw: bytes, limit: int = 65536, minimum: int = 6) -> str:
    """Carve human-readable metadata out of a binary header (EXIF, XMP, comments)."""
    import re

    runs: list[str] = []
    for match in re.finditer(rb"[\x20-\x7e\t]{%d,}" % minimum, raw[:limit]):
        candidate = match.group(0).decode("ascii", "ignore").strip()
        letters = sum(char.isalpha() for char in candidate)
        if letters >= 4 and letters / max(len(candidate), 1) > 0.55 and plausible_text(candidate):
            runs.append(candidate)
    return "\n".join(dict.fromkeys(runs))


def _render_pdf_pages(path: Path) -> list[bytes]:
    """Rasterise with a system renderer if one exists. Optional, never required."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("pdftoppm"):
        return []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-r", str(OCR_DPI), "-png", "-l", str(MAX_PAGES),
                            str(path), f"{tmp}/page"], check=True, timeout=OCR_TIMEOUT_S * 2,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return [p.read_bytes() for p in sorted(Path(tmp).glob("page*.png"))]
    except Exception:
        return []


# ── Images ───────────────────────────────────────────────────────────────────
def scan_image(path: Path) -> Scan:
    raw = path.read_bytes()
    meta_text, meta_notes = _image_metadata(raw)
    ocr = _ocr_images([raw], backend="ocr")
    if not meta_text.strip() and not ocr.ok:
        meta_text = _printable_runs(raw)
        if meta_text.strip():
            meta_notes.append("carved_from_bytes")
    meta_text = meta_text if plausible_text(meta_text) else ""
    parts = [part for part in (meta_text, ocr.text) if part.strip()]
    if meta_text.strip() and ocr.ok:
        backend = "exif+ocr"
    elif meta_text.strip():
        backend = "exif-carved" if "carved_from_bytes" in meta_notes else "exif"
    else:
        backend = ocr.backend or "ocr"
    scan = Scan(text=_bounded("\n".join(parts)), backend=backend,
                pages=1, notes=meta_notes + ocr.notes)
    return scan


def _image_metadata(raw: bytes) -> tuple[str, list[str]]:
    """Collect human-readable metadata (EXIF ImageDescription, XMP, comments)."""
    texts: list[str] = []
    notes: list[str] = []
    try:
        from PIL import Image, ExifTags  # type: ignore
    except Exception:
        return "", ["pillow_missing"]
    try:
        with Image.open(io.BytesIO(raw)) as image:
            for key, value in (image.getexif() or {}).items():
                tag = ExifTags.TAGS.get(key, str(key))
                if isinstance(value, str) and len(value) >= 4:
                    texts.append(value)
                elif isinstance(value, bytes):
                    try:
                        texts.append(value.decode("utf-8", "ignore"))
                    except Exception:
                        pass
            for key in ("Description", "Comment", "Author", "Artist", "Title"):
                value = getattr(image, key, None) or image.info.get(key)
                if isinstance(value, str) and len(value) >= 4:
                    texts.append(value)
            xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
            if isinstance(xmp, bytes):
                texts.append(xmp.decode("utf-8", "ignore"))
    except Exception:
        notes.append("image_unreadable")
    return "\n".join(dict.fromkeys(texts)), notes


def _ocr_images(blobs: list[bytes], *, backend: str) -> Scan:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return Scan(backend=backend, notes=["ocr_missing"])
    import shutil
    if not shutil.which("tesseract"):
        return Scan(backend=backend, notes=["tesseract_binary_missing"])
    chunks: list[str] = []
    notes: list[str] = []
    for blob in blobs[:MAX_PAGES]:
        try:
            with Image.open(io.BytesIO(blob)) as image:
                if image.mode not in ("L", "RGB"):
                    image = image.convert("RGB")
                chunks.append(pytesseract.image_to_string(image, timeout=OCR_TIMEOUT_S) or "")
        except Exception:
            notes.append("ocr_failed")
    return Scan(text=_bounded("\n".join(chunks)), backend=backend, pages=len(blobs), notes=notes)


def scan_path(path: str | Path, suffix: str | None = None) -> Scan:
    """Dispatch on the suffix; unknown binaries produce an empty scan plus a reason."""
    source = Path(path)
    kind = (suffix or source.suffix).lower()
    if kind == ".pdf":
        return scan_pdf(source)
    if kind in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}:
        return scan_image(source)
    return Scan(notes=["no_extractor"])
