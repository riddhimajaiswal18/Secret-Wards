"""Strict text decoding for the encodings used in the Team Kit."""
from __future__ import annotations


class DecodeError(ValueError):
    """Input bytes could not be safely decoded."""


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig",)
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8",)
        # BOM-less UTF-16 commonly has a strong NUL-byte pattern. Avoid decoding
        # malformed UTF-16 as plausible-but-garbled cp1252 text.
        sample = raw[:4096]
        even_nuls = sum(sample[i] == 0 for i in range(0, len(sample), 2))
        odd_nuls = sum(sample[i] == 0 for i in range(1, len(sample), 2))
        if sample and max(even_nuls, odd_nuls) >= max(2, len(sample) // 8):
            candidates += ("utf-16-le" if odd_nuls > even_nuls else "utf-16-be",)
        candidates += ("cp1252",)
    for encoding in candidates:
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except UnicodeError:
            continue
    raise DecodeError("unsupported_encoding") from None
