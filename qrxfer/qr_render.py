"""Render protocol text as QR-code images."""

from __future__ import annotations

import cv2
import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
from qrcode.image.pil import PilImage
import numpy as np

_ERROR_CORRECTION = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


def render_qr(
    text: str,
    ec: str = "M",
    box_size: int = 4,
    border: int = 4,
    verify_readability: bool = True,
) -> np.ndarray:
    """Render a QR image, optionally checking dense codes with OpenCV."""
    level = _ERROR_CORRECTION.get(ec.upper())
    if level is None:
        raise ValueError("ec must be one of L, M, Q, or H")
    if box_size <= 0 or border < 4:
        raise ValueError("box_size must be positive and border must be at least 4")
    detector = cv2.QRCodeDetector() if verify_readability else None
    mask_patterns = (
        (None, 0, 7, 2, 3, 4, 5, 6, 1)
        if verify_readability
        else (0,)
    )
    selected_image: np.ndarray | None = None
    for mask_pattern in mask_patterns:
        code = qrcode.QRCode(
            version=None,
            error_correction=level,
            box_size=box_size,
            border=border,
            mask_pattern=mask_pattern,
        )
        code.add_data(text)
        code.make(fit=True)
        wrapped_image = code.make_image(fill_color="black", back_color="white")
        if not isinstance(wrapped_image, PilImage):
            wrapped_image = wrapped_image.get_image()
        image = np.asarray(wrapped_image.convert("L"), dtype=np.uint8)
        selected_image = image
        if not verify_readability or code.version < 15:
            break
        # OpenCV can miss valid high-version codes with particular QR masks.
        probe = image
        if box_size < 4:
            probe = cv2.resize(
                image, None, fx=4 / box_size, fy=4 / box_size,
                interpolation=cv2.INTER_NEAREST,
            )
        detector.setEpsX(0.08)
        detector.setEpsY(0.08)
        if detector.detectAndDecode(probe)[0] == text:
            break
    if selected_image is None:
        raise RuntimeError("Unable to render a QR code")
    return selected_image
