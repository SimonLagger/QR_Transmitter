"""Encoding and validation for the QR file-transfer frame protocol."""

from __future__ import annotations

import base64
import binascii
import re
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"QX"
VERSION = 1
TYPE_HEADER = 0
TYPE_DATA = 1
_PREFIX = struct.Struct(">2sBBIIIH")
_CRC = struct.Struct(">I")


class FrameError(ValueError):
    """Raised when a frame is malformed or fails integrity validation."""


@dataclass(frozen=True)
class Frame:
    """A decoded protocol frame."""

    type: int
    transfer_id: int
    index: int
    total: int
    payload: bytes


def encode_frame(frame: Frame) -> str:
    """Encode a frame as unpadded URL-safe Base64 text."""
    if frame.type not in (TYPE_HEADER, TYPE_DATA):
        raise FrameError(f"Unknown frame type: {frame.type}")
    for name, value in (
        ("transfer_id", frame.transfer_id),
        ("index", frame.index),
        ("total", frame.total),
    ):
        if not 0 <= value <= 0xFFFFFFFF:
            raise FrameError(f"{name} must fit in an unsigned 32-bit integer")
    if len(frame.payload) > 0xFFFF:
        raise FrameError("Payload exceeds the 65535-byte protocol limit")

    prefix = _PREFIX.pack(
        MAGIC, VERSION, frame.type, frame.transfer_id, frame.index,
        frame.total, len(frame.payload),
    )
    body = prefix + frame.payload
    raw = body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_frame(text: str) -> Frame:
    """Decode and validate unpadded URL-safe Base64 frame text."""
    if not text or re.fullmatch(r"[A-Za-z0-9_-]+", text) is None:
        raise FrameError("Frame text must be non-empty ASCII")
    try:
        encoded = text.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise FrameError("Invalid URL-safe Base64 frame") from exc

    if len(raw) < _PREFIX.size + _CRC.size:
        raise FrameError("Truncated frame")
    try:
        magic, version, frame_type, transfer_id, index, total, payload_len = (
            _PREFIX.unpack(raw[:_PREFIX.size])
        )
    except struct.error as exc:
        raise FrameError("Truncated frame header") from exc

    if magic != MAGIC:
        raise FrameError("Invalid frame magic")
    if version != VERSION:
        raise FrameError(f"Unsupported frame version: {version}")
    if frame_type not in (TYPE_HEADER, TYPE_DATA):
        raise FrameError(f"Unknown frame type: {frame_type}")
    expected_len = _PREFIX.size + payload_len + _CRC.size
    if len(raw) != expected_len:
        raise FrameError("Frame length does not match payload_len")

    body, crc_bytes = raw[:-_CRC.size], raw[-_CRC.size:]
    (expected_crc,) = _CRC.unpack(crc_bytes)
    if (zlib.crc32(body) & 0xFFFFFFFF) != expected_crc:
        raise FrameError("Frame CRC32 mismatch")

    return Frame(
        type=frame_type,
        transfer_id=transfer_id,
        index=index,
        total=total,
        payload=raw[_PREFIX.size:-_CRC.size],
    )
