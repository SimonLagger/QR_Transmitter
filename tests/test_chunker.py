"""Tests for file splitting and verified reassembly."""

from __future__ import annotations

import hashlib
import random

import pytest

from qrxfer.chunker import join_chunks, split_file


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("size", [0, 1, 600, 601, 1024 * 1024])
def test_split_join_roundtrip(tmp_path, size: int, compress: bool) -> None:
    """Files of boundary and large sizes reassemble without data loss."""
    path = tmp_path / "input.bin"
    content = random.Random(size).randbytes(size)
    path.write_bytes(content)
    header, chunks = split_file(path, 600, compress)
    assert join_chunks(dict(enumerate(chunks)), header) == content
    assert header["sha256"] == hashlib.sha256(content).hexdigest()


def test_sha256_file(tmp_path) -> None:
    """The file hashing helper returns the standard lowercase digest."""
    path = tmp_path / "digest.bin"
    path.write_bytes(b"hash me")
    from qrxfer.chunker import sha256_file

    assert sha256_file(path) == hashlib.sha256(b"hash me").hexdigest()


def test_split_rejects_nonpositive_chunk_size(tmp_path) -> None:
    """Chunk sizes must be positive."""
    path = tmp_path / "empty"
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        split_file(path, 0)
