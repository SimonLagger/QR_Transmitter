"""Tests for frame encoding and validation."""

from __future__ import annotations

import base64
import zlib

import pytest

from qrxfer.protocol import (
    Frame,
    FrameError,
    TYPE_DATA,
    TYPE_HEADER,
    decode_frame,
    encode_frame,
)


@pytest.mark.parametrize("frame_type", [TYPE_HEADER, TYPE_DATA])
def test_frame_roundtrip(frame_type: int) -> None:
    """Header and data frames retain their values after encoding."""
    frame = Frame(frame_type, 0x12345678, 4, 9, b"example payload")
    assert decode_frame(encode_frame(frame)) == frame


def test_single_bit_changes_are_rejected() -> None:
    """Every changed bit in a valid raw frame is detected by validation."""
    encoded = encode_frame(Frame(TYPE_DATA, 17, 0, 1, b"payload"))
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    for byte_index in range(len(raw)):
        for bit_index in range(8):
            changed = bytearray(raw)
            changed[byte_index] ^= 1 << bit_index
            text = base64.urlsafe_b64encode(changed).decode("ascii").rstrip("=")
            with pytest.raises(FrameError):
                decode_frame(text)


@pytest.mark.parametrize("mutation", ["magic", "version", "truncated"])
def test_invalid_frame_structure_is_rejected(mutation: str) -> None:
    """Invalid magic, protocol versions, and truncated frames are rejected."""
    raw = bytearray(
        base64.urlsafe_b64decode(
            encode_frame(Frame(TYPE_HEADER, 1, 0, 0, b"{}"))
            + "=" * (-len(encode_frame(Frame(TYPE_HEADER, 1, 0, 0, b"{}"))) % 4)
        )
    )
    if mutation == "magic":
        raw[0] = ord("Z")
        raw[-4:] = (zlib.crc32(raw[:-4]) & 0xFFFFFFFF).to_bytes(4, "big")
    elif mutation == "version":
        raw[2] = 2
        raw[-4:] = (zlib.crc32(raw[:-4]) & 0xFFFFFFFF).to_bytes(4, "big")
    else:
        raw = raw[:-1]
    text = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(FrameError):
        decode_frame(text)
