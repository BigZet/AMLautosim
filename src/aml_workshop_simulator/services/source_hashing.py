"""Versioned source hashing; binary and evidence hashes remain byte-exact."""

from hashlib import sha256
from pathlib import Path


def source_sha256(path: Path) -> str:
    """Hash source with CRLF normalized to LF (the ``lf-v1`` contract)."""
    return sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
