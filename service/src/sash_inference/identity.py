"""The digests the statement names components by, computed as PySyft's eval job computes them.

The statement only matches a receipt if both sides get the same digest from the same bytes or
params, so tests/test_identity.py checks these against the digests in a v3 receipt.
"""

import hashlib
import json
from collections.abc import Iterable
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
    """Sorted, compact JSON. It is RFC 8785 (JCS) for what this service hashes: ASCII keys, strings,
    integers and short decimals, so it needs no JCS library in the vLLM image."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
