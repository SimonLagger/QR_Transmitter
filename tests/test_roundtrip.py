"""Offline QR rendering and decoding tests."""

from __future__ import annotations

import random

import cv2
import numpy as np
import pytest

from qrxfer.protocol import Frame, TYPE_DATA, encode_frame
from qrxfer.qr_decode import decode_qr
from qrxfer.qr_render import render_qr


def test_one_hundred_default_size_frames_render_and_decode() -> None:
    """Decode 100 independently generated frames at the default payload size."""
    rng = random.Random(4815)
    for index in range(100):
        payload = rng.randbytes(600)
        text = encode_frame(Frame(TYPE_DATA, 123, index, 100, payload))
        image = render_qr(text)
        assert image.dtype == np.uint8 and image.ndim == 2
        assert text in decode_qr(image)


@pytest.mark.parametrize("transform", ["blur", "downscale"])
def test_qr_decode_with_image_degradation(transform: str) -> None:
    """Decode a normal QR after modest blur or downscaling."""
    text = encode_frame(Frame(TYPE_DATA, 5, 0, 1, b"QR optical channel" * 8))
    image = render_qr(text)
    if transform == "blur":
        image = cv2.GaussianBlur(image, (3, 3), 0)
    else:
        image = cv2.resize(
            image, None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA
        )
    assert text in decode_qr(image)


def test_fast_render_skips_opencv_readability_probes(monkeypatch) -> None:
    """On-demand TX rendering does not start a slow detector for each frame."""
    def fail_detector():
        raise AssertionError("fast rendering must not run OpenCV readability probes")

    monkeypatch.setattr(cv2, "QRCodeDetector", fail_detector)
    image = render_qr("fast frame", verify_readability=False)
    assert image.dtype == np.uint8 and image.ndim == 2
