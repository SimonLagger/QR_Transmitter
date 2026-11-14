"""Command-line QR transmitter."""

from __future__ import annotations

import argparse
import json
import secrets
from typing import Sequence

import cv2
import numpy as np
from qrcode.exceptions import DataOverflowError

from .chunker import TransferHeader, split_file
from .protocol import Frame, TYPE_DATA, TYPE_HEADER, encode_frame
from .qr_render import render_qr


def build_frames(
    header: TransferHeader,
    chunks: list[bytes],
    transfer_id: int,
    header_every: int = 10,
) -> list[tuple[str, int, int]]:
    """Build the repeating frame sequence with periodic transfer headers."""
    if header_every <= 0:
        raise ValueError("header_every must be greater than zero")
    total = len(chunks)
    header_text = encode_frame(
        Frame(
            TYPE_HEADER, transfer_id, 0, total,
            json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
    )
    frames = [(header_text, 0, total)]
    for index, chunk in enumerate(chunks):
        if index and index % header_every == 0:
            frames.append((header_text, index, total))
        data_text = encode_frame(Frame(TYPE_DATA, transfer_id, index, total, chunk))
        frames.append((data_text, index + 1, total))
    return frames


def _display_image(
    image: np.ndarray, scale: int, fullscreen: bool, overlay: str
) -> np.ndarray:
    """Scale and center a QR image, keeping its quiet zone free of overlay text."""
    height, width = image.shape[:2]
    canvas_width = max(1000, width * scale + 40)
    canvas_height = max(900, height * scale + 80)
    canvas = np.full((canvas_height, canvas_width), 255, dtype=np.uint8)
    target_width = width * scale
    target_height = height * scale
    resized = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
    x = (canvas_width - target_width) // 2
    y = 60 + (canvas_height - 60 - target_height) // 2
    canvas[y:y + target_height, x:x + target_width] = resized
    cv2.putText(
        canvas, overlay, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, 0, 1, cv2.LINE_AA
    )
    if fullscreen:
        cv2.namedWindow("QR Transmitter", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(
            "QR Transmitter", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
        )
    return canvas


def run(
    file_path: str,
    chunk_size: int = 600,
    ec: str = "M",
    fps: float = 4,
    compress: bool = False,
    loops: int = 0,
    header_every: int = 10,
    fullscreen: bool = False,
    scale: int = 8,
) -> int:
    """Render and display a file's QR frames until stopped or loops are complete."""
    if fps <= 0 or loops < 0 or scale <= 0:
        raise ValueError("fps and scale must be positive; loops cannot be negative")
    header, chunks = split_file(file_path, chunk_size, compress)
    transfer_id = secrets.randbits(32)
    frames = build_frames(header, chunks, transfer_id, header_every)
    try:
        images = [render_qr(text, ec=ec, box_size=1) for text, _, _ in frames]
    except DataOverflowError as exc:
        raise ValueError(
            "A frame exceeds QR capacity; reduce --chunk-size or lower --ec"
        ) from exc
    seconds_per_loop = len(frames) / fps
    print(
        f"Transfer {transfer_id:08x}: {len(frames)} frames, "
        f"estimated {seconds_per_loop:.1f} seconds per loop"
    )
    delay_ms = max(1, round(1000 / fps))
    paused = False
    loop_number = 0
    frame_number = 0
    try:
        while loops == 0 or loop_number < loops:
            image = images[frame_number]
            if not paused:
                display = _display_image(
                    image, scale, fullscreen,
                    f"transfer {transfer_id:08x}  frame {frame_number + 1}/{len(frames)}  loop {loop_number + 1}",
                )
                cv2.imshow("QR Transmitter", display)
            key = cv2.waitKey(0 if paused else delay_ms) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
                continue
            if not paused:
                frame_number += 1
                if frame_number == len(frames):
                    frame_number = 0
                    loop_number += 1
    finally:
        cv2.destroyAllWindows()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transmit a file as looping QR codes")
    parser.add_argument("file", help="file to transfer")
    parser.add_argument("--chunk-size", type=int, default=600)
    parser.add_argument("--ec", choices=("L", "M", "Q", "H"), default="M")
    parser.add_argument("--fps", type=float, default=4)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--loops", type=int, default=0, help="0 repeats until stopped")
    parser.add_argument("--header-every", type=int, default=10)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--scale", type=int, default=8)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse transmitter options and start the display loop."""
    args = _parser().parse_args(argv)
    try:
        return run(
            args.file, args.chunk_size, args.ec, args.fps, args.compress,
            args.loops, args.header_every, args.fullscreen, args.scale,
        )
    except (OSError, ValueError) as exc:
        print(f"qrxfer-tx: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
