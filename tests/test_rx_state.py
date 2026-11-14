"""Tests for receiver state transitions and integrity handling."""

from __future__ import annotations

import hashlib
import json
import random

from qrxfer.protocol import Frame, TYPE_DATA, TYPE_HEADER, decode_frame, encode_frame
from qrxfer.rx import Receiver, ReceiverState


def _encoded_transfer(content: bytes, filename: str = "sample.bin"):
    chunk_size = 73
    chunks = [
        content[offset:offset + chunk_size]
        for offset in range(0, len(content), chunk_size)
    ]
    header = {
        "filename": filename,
        "size": len(content),
        "chunk_size": chunk_size,
        "chunks": len(chunks),
        "sha256": hashlib.sha256(content).hexdigest(),
        "compressed": False,
    }
    transfer_id = 1234
    header_text = encode_frame(
        Frame(
            TYPE_HEADER,
            transfer_id,
            0,
            len(chunks),
            json.dumps(header).encode("utf-8"),
        )
    )
    data_texts = [
        encode_frame(Frame(TYPE_DATA, transfer_id, index, len(chunks), payload))
        for index, payload in enumerate(chunks)
    ]
    return header_text, data_texts, header


def test_random_order_with_duplicates_completes(tmp_path) -> None:
    """Out-of-order frames and repeated data still produce verified output."""
    content = random.Random(8).randbytes(4096)
    header, data, _ = _encoded_transfer(content)
    frames = data + [header]
    rng = random.Random(10)
    frames = [item for frame in frames for item in ([frame] * (2 if rng.random() < 0.3 else 1))]
    rng.shuffle(frames)
    receiver = Receiver(tmp_path)
    for frame in frames:
        receiver.feed(frame)
    assert receiver.state == ReceiverState.COMPLETE
    assert receiver.output_path.read_bytes() == content
    assert receiver.duplicates > 0


def test_missing_chunk_is_reported(tmp_path) -> None:
    """A missing chunk keeps the receiver in the receiving state."""
    header, data, _ = _encoded_transfer(b"x" * 1000)
    receiver = Receiver(tmp_path)
    receiver.feed(header)
    for index, frame in enumerate(data):
        if index != 2:
            receiver.feed(frame)
    assert receiver.state == ReceiverState.RECEIVING
    assert receiver.missing == [2]


def test_valid_crc_with_corrupted_payload_fails_hash(tmp_path) -> None:
    """A changed payload with a newly valid CRC still fails whole-file SHA-256."""
    content = b"expected bytes"
    header, data, _ = _encoded_transfer(content)
    original = decode_frame(data[0])
    damaged = bytes([original.payload[0] ^ 1]) + original.payload[1:]
    damaged_text = encode_frame(
        Frame(TYPE_DATA, original.transfer_id, original.index, original.total, damaged)
    )
    receiver = Receiver(tmp_path)
    receiver.feed(header)
    event = receiver.feed(damaged_text)
    assert event.kind == "failed"
    assert receiver.state == ReceiverState.FAILED
    assert receiver.actual_hash != receiver.expected_hash
    assert not (tmp_path / "sample.bin").exists()


def test_midstream_data_is_applied_after_header(tmp_path) -> None:
    """Data buffered before a header is applied when that header arrives."""
    content = b"join in the middle " * 20
    header, data, _ = _encoded_transfer(content)
    receiver = Receiver(tmp_path)
    for frame in data:
        receiver.feed(frame)
    receiver.feed(header)
    assert receiver.state == ReceiverState.COMPLETE
    assert receiver.output_path.read_bytes() == content


def test_malicious_filename_is_reduced_to_basename(tmp_path) -> None:
    """Path traversal metadata writes only the basename under the output folder."""
    content = b"safe"
    header, data, _ = _encoded_transfer(content, "../../x")
    receiver = Receiver(tmp_path)
    receiver.feed(header)
    receiver.feed(data[0])
    assert receiver.state == ReceiverState.COMPLETE
    assert receiver.output_path == tmp_path / "x"
    assert receiver.output_path.read_bytes() == content


def test_header_after_empty_transfer_completes(tmp_path) -> None:
    """An empty file completes from its header without data frames."""
    header, _, _ = _encoded_transfer(b"")
    receiver = Receiver(tmp_path)
    receiver.feed(header)
    assert receiver.state == ReceiverState.COMPLETE
