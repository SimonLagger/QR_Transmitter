"""Tests for transmitter frame sequencing."""

from __future__ import annotations

import json

import numpy as np

from qrxfer.protocol import TYPE_DATA, TYPE_HEADER, decode_frame
from qrxfer import tx
from qrxfer.chunker import TransferHeader
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


def test_transmitter_shows_startup_info_before_rendering_all_frames(
    monkeypatch, capsys, tmp_path
) -> None:
    """Large transfers render frames on demand after reporting loop duration."""
    header: TransferHeader = {
        "filename": "sample.bin",
        "size": 1,
        "chunk_size": 600,
        "chunks": 1,
        "sha256": "0" * 64,
        "compressed": False,
    }
    monkeypatch.setattr(tx, "split_file", lambda *_args: (header, [b"x"]))
    render_calls: list[str] = []

    def render(text, **_kwargs):
        if not render_calls:
            assert "Preparing the first QR code" in capsys.readouterr().out
        render_calls.append(text)
        return np.zeros((10, 10), dtype=np.uint8)

    monkeypatch.setattr(tx, "render_qr", render)
    monkeypatch.setattr(tx, "_display_image", lambda image, *_args: image)
    monkeypatch.setattr(tx.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(tx.cv2, "waitKey", lambda *_args: -1)
    monkeypatch.setattr(tx.cv2, "destroyAllWindows", lambda: None)

    assert tx.run(str(tmp_path / "sample.bin"), loops=1, scale=1) == 0
    assert len(render_calls) == 2
