"""Command-line QR receiver and independently testable receive state machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
import zlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence

import cv2

from .capture import CameraSource, FolderSource, FrameSource, ScreenSource
from .chunker import TransferHeader, join_chunks
from .protocol import Frame, FrameError, TYPE_DATA, TYPE_HEADER, decode_frame
from .qr_decode import decode_qr

LOGGER = logging.getLogger(__name__)
_MAX_BUFFERED_FRAMES = 2000


class ReceiverState(str, Enum):
    """Lifecycle state of a single transfer."""

    WAIT_HEADER = "WAIT_HEADER"
    RECEIVING = "RECEIVING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Event:
    """Result of feeding one QR text value to a receiver."""

    kind: str
    message: str = ""


class Receiver:
    """Validate frames, assemble chunks, and write only hash-verified files."""

    def __init__(self, out: str | Path = ".", reset: bool = False) -> None:
        self.out = Path(out)
        self.reset = reset
        self.state = ReceiverState.WAIT_HEADER
        self.transfer_id: int | None = None
        self.header: TransferHeader | None = None
        self.chunks: dict[int, bytes] = {}
        self._buffer: dict[int, bytes] = {}
        self.duplicates = 0
        self.conflicts = 0
        self.rejected = 0
        self.crc_rejects = 0
        self.unique_frames = 0
        self._buffer_total: int | None = None
        self._total = 0
        self.output_path: Path | None = None
        self.expected_hash: str | None = None
        self.actual_hash: str | None = None
        self.missing: list[int] = []

    def feed(self, frame_text: str) -> Event:
        """Decode a frame text and update transfer state."""
        try:
            frame = decode_frame(frame_text)
        except FrameError as exc:
            self.rejected += 1
            self.crc_rejects += 1
            return Event("rejected", str(exc))
        if self.state in (ReceiverState.COMPLETE, ReceiverState.FAILED):
            return Event("ignored", "Transfer is already finished")
        if self.transfer_id is None:
            self.transfer_id = frame.transfer_id
        elif frame.transfer_id != self.transfer_id:
            if not (self.reset and frame.type == TYPE_HEADER):
                return Event("ignored", "Frame belongs to a different transfer")
            self.transfer_id = frame.transfer_id
            self.state = ReceiverState.WAIT_HEADER
            self.header = None
            self.chunks.clear()
            self._buffer.clear()
            self._buffer_total = None
            self.output_path = None
            self.expected_hash = None
            self.actual_hash = None
            self.missing.clear()

        if frame.type == TYPE_HEADER:
            return self._accept_header(frame)
        return self._accept_data(frame)

    def _accept_header(self, frame: Frame) -> Event:
        if frame.index != 0:
            self.rejected += 1
            return Event("rejected", "Header index must be zero")
        if self._buffer_total is not None and frame.total != self._buffer_total:
            self.state = ReceiverState.FAILED
            return Event("failed", "Header total does not match buffered data frames")
        try:
            raw_header = json.loads(frame.payload.decode("utf-8"))
            header = self._validate_header(raw_header, frame.total)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self.state = ReceiverState.FAILED
            return Event("failed", f"Invalid transfer header: {exc}")
        if self.header is not None:
            if header != self.header or frame.total != self._total:
                self.conflicts += 1
                return Event("conflict", "Conflicting transfer header")
            self.duplicates += 1
            return Event("duplicate")

        self.header = header
        self._total = frame.total
        self.state = ReceiverState.RECEIVING
        self.unique_frames += 1
        self.chunks.update(
            (index, payload)
            for index, payload in self._buffer.items()
            if index < self._total
        )
        self._buffer.clear()
        return self._finish_if_ready()

    @staticmethod
    def _validate_header(header: object, total: int) -> TransferHeader:
        if not isinstance(header, dict):
            raise ValueError("header payload must be a JSON object")
        chunks = header.get("chunks")
        if not isinstance(chunks, int) or isinstance(chunks, bool) or chunks < 0:
            raise ValueError("header chunks must be a non-negative integer")
        if chunks != total:
            raise ValueError("header chunk count does not match frame total")
        size = header.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("header size must be a non-negative integer")
        chunk_size = header.get("chunk_size")
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
            raise ValueError("header chunk_size must be greater than zero")
        compressed = header.get("compressed")
        if not isinstance(compressed, bool):
            raise ValueError("header compressed must be a boolean")
        filename = header.get("filename")
        if not isinstance(filename, str) or not filename or "\x00" in filename:
            raise ValueError("header filename must be a non-empty string")
        _safe_basename(filename)
        digest = header.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("header sha256 must be a lowercase SHA-256 hex digest")
        return {
            "filename": filename,
            "size": size,
            "chunk_size": chunk_size,
            "chunks": chunks,
            "sha256": digest,
            "compressed": compressed,
        }

    def _accept_data(self, frame: Frame) -> Event:
        if frame.index >= frame.total:
            self.rejected += 1
            return Event("rejected", "Data index must be less than total")
        if self.header is not None and frame.total != self._total:
            self.rejected += 1
            return Event("rejected", "Data total does not match header")
        if self.header is None:
            if self._buffer_total is None:
                self._buffer_total = frame.total
            elif frame.total != self._buffer_total:
                self.rejected += 1
                return Event("rejected", "Pre-header data totals do not match")
        target = self.chunks if self.header is not None else self._buffer
        if self.header is None and frame.index >= frame.total:
            self.rejected += 1
            return Event("rejected", "Data index is out of range")
        if frame.index in target:
            if target[frame.index] == frame.payload:
                self.duplicates += 1
                return Event("duplicate")
            self.conflicts += 1
            return Event("conflict", f"Conflicting duplicate chunk {frame.index}")
        if self.header is None and len(self._buffer) >= _MAX_BUFFERED_FRAMES:
            self.rejected += 1
            return Event("rejected", "Pre-header data buffer is full")
        target[frame.index] = frame.payload
        self.unique_frames += 1
        return self._finish_if_ready()

    def _finish_if_ready(self) -> Event:
        if self.header is None:
            return Event("accepted")
        total = self._total
        self.missing = [index for index in range(total) if index not in self.chunks]
        if self.missing:
            return Event("accepted")
        self.expected_hash = str(self.header["sha256"])
        try:
            content = join_chunks(self.chunks, self.header)
        except (ValueError, zlib.error) as exc:
            self.state = ReceiverState.FAILED
            data = b"".join(self.chunks[index] for index in range(total))
            if self.header["compressed"]:
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    data = b""
            self.actual_hash = hashlib.sha256(data).hexdigest()
            return Event("failed", f"Transfer integrity check failed: {exc}")
        self.actual_hash = hashlib.sha256(content).hexdigest()
        destination_name = _safe_basename(str(self.header["filename"]))
        self.out.mkdir(parents=True, exist_ok=True)
        destination = self.out / destination_name
        if destination.is_symlink():
            self.state = ReceiverState.FAILED
            return Event("failed", "Output filename resolves to a symbolic link")
        destination.write_bytes(content)
        self.output_path = destination
        self.state = ReceiverState.COMPLETE
        return Event("complete", str(destination))

def _safe_basename(filename: str) -> str:
    """Keep only a filename component across both Windows and POSIX paths."""
    name = PureWindowsPath(filename).name
    name = PurePosixPath(name).name
    if name in ("", ".", ".."):
        raise ValueError("Transfer filename has no safe basename")
    return name


def _parse_region(value: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("region must be x,y,w,h integers") from exc
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("region must be x,y,w,h with positive size")
    return parts  # type: ignore[return-value]


def _source_from_args(args: argparse.Namespace) -> FrameSource:
    if args.source == "camera":
        return CameraSource(args.index)
    if args.source == "screen":
        return ScreenSource(args.monitor, args.region)
    if args.path is None:
        raise ValueError("--path is required when --source=folder")
    return FolderSource(args.path)


def _missing_ranges(missing: list[int]) -> str:
    if not missing:
        return "none"
    ranges: list[str] = []
    start = previous = missing[0]
    for index in missing[1:]:
        if index != previous + 1:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = index
        previous = index
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def receive(
    source: FrameSource,
    out: str | Path = ".",
    timeout: float = 60,
    show: bool = True,
    reset: bool = False,
) -> int:
    """Receive a transfer from a source until completion, exhaustion, or timeout."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    receiver = Receiver(out, reset=reset)
    started = time.monotonic()
    last_text: str | None = None
    decoded_count = 0
    decode_failures = 0
    try:
        while receiver.state not in (ReceiverState.COMPLETE, ReceiverState.FAILED):
            if time.monotonic() - started >= timeout:
                break
            image = source.read()
            if image is None:
                if isinstance(source, FolderSource):
                    break
                time.sleep(0.01)
                continue
            texts = decode_qr(image)
            if not texts:
                decode_failures += 1
                last_text = None
            for text in texts:
                if text == last_text:
                    continue
                last_text = text
                decoded_count += 1
                event = receiver.feed(text)
                if event.kind == "failed":
                    print(event.message)
                break
            elapsed = max(time.monotonic() - started, 0.001)
            total = receiver._total
            received = len(receiver.chunks)
            percentage = 100.0 if total == 0 and receiver.header else (
                100 * received / total if total else 0
            )
            status = (
                f"\r{received}/{total} ({percentage:5.1f}%) "
                f"missing {len(receiver.missing)} | decoded {decoded_count} "
                f"| rejected {receiver.crc_rejects} (CRC) | {elapsed:.1f}s"
            )
            print(status, end="", flush=True)
            if show:
                cv2.imshow("QR Receiver", image)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    finally:
        source.close()
        if show:
            cv2.destroyAllWindows()
    print()
    if receiver.state == ReceiverState.COMPLETE:
        output_path = receiver.output_path
        if output_path is None:
            raise RuntimeError("Completed receiver has no output path")
        print(
            f"Received {receiver.output_path}; SHA-256 {receiver.actual_hash}; "
            f"unique frames {receiver.unique_frames}, duplicates {receiver.duplicates}, "
            f"CRC rejects {receiver.crc_rejects}, decode failures {decode_failures}, "
            f"throughput {output_path.stat().st_size / max(time.monotonic() - started, 0.001):.1f} bytes/s"
        )
        return 0
    if receiver.state == ReceiverState.FAILED:
        print(
            f"Transfer failed: expected SHA-256 {receiver.expected_hash}, "
            f"actual {receiver.actual_hash}"
        )
        return 2
    if receiver.header is not None:
        receiver.missing = [
            index for index in range(receiver._total)
            if index not in receiver.chunks
        ]
    print(f"Timed out or source exhausted; missing chunks: {_missing_ranges(receiver.missing)}")
    return 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Receive a file from QR codes")
    parser.add_argument("--source", choices=("camera", "screen", "folder"), required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--region", type=_parse_region)
    parser.add_argument("--path")
    parser.add_argument("--out", default=".")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--no-preview", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse receiver options and begin receiving frames."""
    args = _parser().parse_args(argv)
    try:
        source = _source_from_args(args)
        return receive(
            source, args.out, args.timeout, not args.no_preview, args.reset
        )
    except (OSError, RuntimeError, ValueError) as exc:
        LOGGER.error("qrxfer-rx: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
