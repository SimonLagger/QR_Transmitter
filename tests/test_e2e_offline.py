"""Offline end-to-end file transfer through rendered QR images."""

from __future__ import annotations

import json
import hashlib
import random

import cv2

from qrxfer.capture import FolderSource
from qrxfer.protocol import Frame, TYPE_DATA, TYPE_HEADER, encode_frame
from qrxfer.qr_render import render_qr
from qrxfer.rx import receive


def test_offline_folder_transfer_is_byte_identical(tmp_path) -> None:
    """Rendered frame images pass through FolderSource and reproduce the file."""
    content = random.Random(99).randbytes(100 * 1024)
    chunk_size = 600
    chunks = [
        content[offset:offset + chunk_size]
        for offset in range(0, len(content), chunk_size)
    ]
    transfer_id = 0x1234ABCD
    header = {
        "filename": "offline.bin",
        "size": len(content),
        "chunk_size": chunk_size,
        "chunks": len(chunks),
        "sha256": hashlib.sha256(content).hexdigest(),
        "compressed": False,
    }
    texts = [
        encode_frame(
            Frame(
                TYPE_HEADER, transfer_id, 0, len(chunks),
                json.dumps(header).encode("utf-8"),
            )
        )
    ]
    texts.extend(
        encode_frame(Frame(TYPE_DATA, transfer_id, index, len(chunks), chunk))
        for index, chunk in enumerate(chunks)
    )
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for index, text in enumerate(texts):
        image = render_qr(text)
        assert cv2.imwrite(str(frame_dir / f"{index:04}.png"), image)

    output = tmp_path / "output"
    result = receive(FolderSource(frame_dir), output, timeout=120, show=False)
    assert result == 0
    assert (output / "offline.bin").read_bytes() == content
