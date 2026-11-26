"""Strict text decoding for the encodings used in the Team Kit."""
from __future__ import annotations


class DecodeError(ValueError):
    """Input bytes could not be safely decoded."""


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig", "utf-8", "utf-16", "cp1252")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16", "utf-8", "cp1252")
    else:
        candidates = ("utf-8", "utf-16", "cp1252")
    for encoding in candidates:
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except UnicodeError:
            continue
    raise DecodeError("unsupported_encoding") from None
