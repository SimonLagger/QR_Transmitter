"""Tests for capture source adapters."""

from __future__ import annotations

import cv2
import numpy as np

from qrxfer.capture import CameraSource, ScreenSource


class FakeCamera:
    """Small OpenCV capture substitute for unit tests."""

    def __init__(self, _index: int) -> None:
        self.closed = False

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        return True, np.zeros((3, 4, 3), dtype=np.uint8)

    def release(self) -> None:
        self.closed = True


def test_camera_source_reads_and_releases(monkeypatch) -> None:
    """Camera frames are returned and the capture is released on close."""
    camera = FakeCamera(0)
    monkeypatch.setattr(cv2, "VideoCapture", lambda _index: camera)
    source = CameraSource(0)
    assert source.read().shape == (3, 4, 3)
    source.close()
    assert camera.closed


def test_screen_source_returns_bgr_and_applies_region(monkeypatch) -> None:
    """Screen capture converts BGRA to BGR for the selected region."""
    class FakeScreen:
        monitors = [
            {"left": 0, "top": 0, "width": 100, "height": 100},
            {"left": 10, "top": 20, "width": 80, "height": 60},
        ]
        region = None
        closed = False

        def grab(self, region):
            self.region = region
            return np.zeros((region["height"], region["width"], 4), dtype=np.uint8)

        def close(self) -> None:
            self.closed = True

    screen = FakeScreen()
    monkeypatch.setattr("qrxfer.capture.mss.mss", lambda: screen)
    source = ScreenSource(1, (2, 3, 12, 14))
    image = source.read()
    assert image.shape == (14, 12, 3)
    assert screen.region == {"left": 12, "top": 23, "width": 12, "height": 14}
    source.close()
    assert screen.closed
