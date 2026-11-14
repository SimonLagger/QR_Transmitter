"""File splitting, metadata generation, and verified chunk joining."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path
from typing import TypedDict


class TransferHeader(TypedDict):
    """Validated metadata associated with a transfer."""

    filename: str
    size: int
    chunk_size: int
    chunks: int
    sha256: str
    compressed: bool


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_file(
    path: str | Path, chunk_size: int, compress: bool = False
) -> tuple[TransferHeader, list[bytes]]:
    """Read a file and return its transfer header and indexed chunk payloads."""
    if not 0 < chunk_size <= 0xFFFF:
        raise ValueError("chunk_size must be between 1 and 65535 bytes")
    source_path = Path(path)
    original = source_path.read_bytes()
    data = zlib.compress(original) if compress else original
    chunks = [
        data[offset:offset + chunk_size]
        for offset in range(0, len(data), chunk_size)
    ]
    header: TransferHeader = {
        "filename": source_path.name,
        "size": len(original),
        "chunk_size": chunk_size,
        "chunks": len(chunks),
        "sha256": hashlib.sha256(original).hexdigest(),
        "compressed": compress,
    }
    return header, chunks


def join_chunks(chunks: dict[int, bytes], header: TransferHeader) -> bytes:
    """Join indexed chunks and decompress them when the header requires it."""
    count = header.get("chunks")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("header chunks must be a non-negative integer")
    if set(chunks) != set(range(count)):
        raise ValueError("chunks must contain every index from 0 to chunks - 1")
    data = b"".join(chunks[index] for index in range(count))
    if header.get("compressed") is True:
        data = zlib.decompress(data)
    elif header.get("compressed") is not False:
        raise ValueError("header compressed must be a boolean")
    size = header.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or len(data) != size:
        raise ValueError("Reassembled size does not match the header")
    expected_hash = header.get("sha256")
    if not isinstance(expected_hash, str) or hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("Reassembled SHA-256 does not match the header")
    return data
