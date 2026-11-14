"""Tests for transmitter frame sequencing."""

from __future__ import annotations

import json

from qrxfer.protocol import TYPE_DATA, TYPE_HEADER, decode_frame
from qrxfer.tx import build_frames


def test_build_frames_repeats_header_at_configured_interval() -> None:
    """The sequence starts with a header and repeats it every N data frames."""
    header = {
        "filename": "sample.bin",
        "size": 5,
        "chunk_size": 1,
        "chunks": 5,
        "sha256": "0" * 64,
        "compressed": False,
    }
    frames = build_frames(header, [bytes([index]) for index in range(5)], 19, 2)
    decoded = [decode_frame(text) for text, _, _ in frames]
    assert [frame.type for frame in decoded] == [
        TYPE_HEADER, TYPE_DATA, TYPE_DATA, TYPE_HEADER,
        TYPE_DATA, TYPE_DATA, TYPE_HEADER, TYPE_DATA,
    ]
    assert json.loads(decoded[0].payload) == header
