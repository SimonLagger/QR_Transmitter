"""Camera, screen, and image-folder frame sources for the receiver."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import mss
import numpy as np


class FrameSource(ABC):
    """A source of BGR or grayscale images."""

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return the next image, or None when no more images are available."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release resources held by the source."""
        raise NotImplementedError


class CameraSource(FrameSource):
    """Read images from an OpenCV camera."""

    def __init__(self, index: int = 0) -> None:
        self._capture = cv2.VideoCapture(index)
        if not self._capture.isOpened():
            self._capture.release()
            raise RuntimeError(f"Unable to open camera {index}")

    def read(self) -> np.ndarray | None:
        """Read one camera frame."""
        ok, image = self._capture.read()
        return image if ok else None

    def close(self) -> None:
        """Release the camera."""
        self._capture.release()


class ScreenSource(FrameSource):
    """Capture a monitor or a rectangular screen region using mss."""

    def __init__(
        self, monitor: int = 1, region: tuple[int, int, int, int] | None = None
    ) -> None:
        self._sct = mss.mss()
        if monitor < 1 or monitor >= len(self._sct.monitors):
            self._sct.close()
            raise ValueError(f"Monitor index out of range: {monitor}")
        selected = dict(self._sct.monitors[monitor])
        if region is not None:
            x, y, width, height = region
            if width <= 0 or height <= 0:
                self._sct.close()
                raise ValueError("Region width and height must be positive")
            selected = {
                "left": selected["left"] + x,
                "top": selected["top"] + y,
                "width": width,
                "height": height,
            }
        self._region = selected

    def read(self) -> np.ndarray | None:
        """Capture the configured screen region as a BGR image."""
        return cv2.cvtColor(np.asarray(self._sct.grab(self._region)), cv2.COLOR_BGRA2BGR)

    def close(self) -> None:
        """Close the screen-capture handle."""
        self._sct.close()


class FolderSource(FrameSource):
    """Read image files from a directory in sorted order."""

    _EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}

    def __init__(self, path: str | Path) -> None:
        folder = Path(path)
        if not folder.is_dir():
            raise ValueError(f"Image folder does not exist: {folder}")
        self._paths = sorted(
            (item for item in folder.iterdir() if item.suffix.lower() in self._EXTENSIONS),
            key=lambda item: (item.name.lower(), item.name),
        )
        self._index = 0

    def read(self) -> np.ndarray | None:
        """Read the next image, or return None when the folder is exhausted."""
        if self._index >= len(self._paths):
            return None
        path = self._paths[self._index]
        self._index += 1
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Unable to read image: {path}")
        return image

    def close(self) -> None:
        """Release the folder source (which holds no external resources)."""
