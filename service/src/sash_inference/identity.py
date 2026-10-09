"""The digests the statement names components by, computed as PySyft's eval job computes them.

The statement only matches a receipt if both sides get the same digest from the same bytes or
params, so tests/test_identity.py checks these against the digests in a v3 receipt.
"""

import hashlib
import json
import math
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

DIRHASH = "dirhash-sha256/1"
JCS = "jcs-sha256/1"


def file_sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def dirhash_sha256(root: Path, files: Iterable[Path] | None = None) -> str:
    """dirhash-sha256/1: sha256 of the canonical JSON of {relative path: file sha256}.

    `files` defaults to every file under `root`.
    """
    if files is None:
        files = (p for p in root.rglob("*") if p.is_file())
    digests = {str(p.relative_to(root)): file_sha256(p) for p in sorted(files)}
    return hashlib.sha256(canonical_json(digests)).hexdigest()


def jcs_sha256(value) -> str:
    """jcs-sha256/1: sha256 of the canonical JSON of `value`."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def canonical_json(value) -> bytes:
    """RFC 8785 (JCS): sorted, compact JSON with numbers written as JavaScript writes them, so 1.0 is
    `1`. For dicts of strings, as in a dirhash, that is plain sorted, compact JSON."""
    return _jcs(value).encode()


def _jcs(value) -> str:
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
        return "{" + ",".join(f"{_jcs(k)}:{_jcs(v)}" for k, v in items) + "}"
    if isinstance(value, list | tuple):
        return "[" + ",".join(_jcs(v) for v in value) + "]"
    if isinstance(value, float):
        return _jcs_number(value)
    return json.dumps(value, ensure_ascii=False)  # strings, integers, booleans, null


def _jcs_number(x: float) -> str:
    """ECMAScript's Number::toString, which JCS prescribes: the shortest digits that round-trip
    (Python's repr has the same), placed as JavaScript places them."""
    if not math.isfinite(x):
        raise ValueError(f"JSON has no {x}")
    if x == 0:
        return "0"
    sign, digit_tuple, exponent = Decimal(repr(x)).as_tuple()
    n = len(digit_tuple) + exponent  # x = 0.d1d2… × 10^n
    digits = "".join(map(str, digit_tuple)).rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{mantissa}e{'+' if n > 0 else '-'}{abs(n - 1)}"
    return ("-" if sign else "") + text
