"""Decode QR text from images using available QR readers and preprocessing."""

from __future__ import annotations

import cv2
import numpy as np


def _preprocessed(image: np.ndarray) -> list[np.ndarray]:
    """Return decoder inputs in the protocol's preferred trial order."""
    if image.size == 0:
        return []
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [image, gray]
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(otsu)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
    )
    variants.append(adaptive)
    variants.append(
        cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    )
    return variants


def decode_qr(image: np.ndarray) -> list[str]:
    """Decode QR strings from an image, trying optional pyzbar then OpenCV."""
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy.ndarray")
    variants = _preprocessed(image)
    if not variants:
        return []

    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except (ImportError, OSError):
        pyzbar_decode = None

    if pyzbar_decode is not None:
        for candidate in variants:
            try:
                results = pyzbar_decode(candidate)
            except (ValueError, OSError):
                continue
            texts = [
                result.data.decode("utf-8")
                for result in results
                if result.data
            ]
            if texts:
                return texts

    detector = cv2.QRCodeDetector()
    for tolerance in (0.08, 0.2):
        detector.setEpsX(tolerance)
        detector.setEpsY(tolerance)
        for candidate in variants:
            result = detector.detectAndDecode(candidate)[0]
            if result:
                return [result]
    return []
