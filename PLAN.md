# QR File Transfer (TX/RX) – Implementation Plan

Audience: GitHub Copilot (Agent/Chat) in VS Code.
Usage: place this file in the repo root as `PLAN.md`. Prompt Copilot: *"Read PLAN.md. Implement step N only. Follow the spec exactly. Do not change the packet format."* Work step by step, one step per prompt.

---

## 1. Goal

Transfer a file between two PCs using only an optical channel (QR codes).

- `tx.py`: reads a file, splits it into chunks, displays a looping sequence of QR codes.
- `rx.py`: captures the screen/camera, decodes QR codes, reassembles the file, verifies integrity.
- No return channel (one-way). Reliability comes from looping the stream and from verification.

## 2. Constraints and defaults

| Item | Decision |
|---|---|
| Language | Python 3.10+ |
| Dependencies | `qrcode[pil]`, `opencv-python`, `numpy`, `mss` (screen capture), optional `pyzbar` |
| Chunk payload size | default 600 bytes (configurable `--chunk-size`) |
| QR error correction | default `M` (configurable `--ec L|M|Q|H`) |
| Frame rate (TX) | default 4 fps (configurable `--fps`) |
| Loop mode | TX repeats all frames until stopped (or `--loops N`) |
| Integrity | CRC32 per frame + SHA-256 over whole file |
| Compression | optional zlib (`--compress`), flag stored in header |
| OS | Windows and Linux; no OS-specific code outside capture backend |

Non-goals: bidirectional protocol, fountain/erasure codes, encryption (may be added later).

## 3. Project structure

```
qrxfer/
├── PLAN.md
├── README.md
├── requirements.txt
├── pyproject.toml            # optional
├── qrxfer/
│   ├── __init__.py
│   ├── protocol.py           # frame encode/decode, constants, CRC
│   ├── chunker.py            # file -> chunks, chunks -> file, SHA-256
│   ├── qr_render.py          # frame bytes -> QR image (numpy array)
│   ├── qr_decode.py          # image -> frame bytes (OpenCV, optional pyzbar)
│   ├── capture.py            # camera / screen / image-folder sources
│   ├── tx.py                 # TX CLI + display loop
│   ├── rx.py                 # RX CLI + receive state machine
│   └── gui.py                # desktop launcher for TX and RX
└── tests/
    ├── test_protocol.py
    ├── test_chunker.py
    ├── test_roundtrip.py     # render -> decode, no camera
    ├── test_rx_state.py
    └── test_gui.py           # desktop launcher command construction
```

## 4. Protocol specification (authoritative)

All integers big-endian. A QR code carries one **frame**. The frame bytes are encoded as **URL-safe Base64 without padding** and put into the QR as a text string (byte-mode safe, avoids binary-handling issues across decoders).

### 4.1 Frame layout (before Base64)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `magic` | ASCII `QX` |
| 2 | 1 | `version` | `1` |
| 3 | 1 | `type` | `0` = HEADER, `1` = DATA |
| 4 | 4 | `transfer_id` | random u32, same for all frames of one transfer |
| 8 | 4 | `index` | HEADER: `0`; DATA: chunk index starting at `0` |
| 12 | 4 | `total` | total number of DATA chunks |
| 16 | 2 | `payload_len` | length of payload in bytes |
| 18 | N | `payload` | see below |
| 18+N | 4 | `crc32` | CRC32 over bytes `[0 .. 18+N)` |

### 4.2 HEADER payload (UTF-8 JSON)

```json
{
  "filename": "example.txt",
  "size": 12345,
  "chunk_size": 600,
  "chunks": 21,
  "sha256": "<hex of ORIGINAL uncompressed file>",
  "compressed": false
}
```

If `compressed` is true, DATA payloads concatenated and zlib-decompressed give the original file. `size` and `sha256` always refer to the original file.

### 4.3 DATA payload

Raw bytes of the chunk.

### 4.4 Rules

- Frames failing magic, version, length, or CRC check are discarded silently (counted in statistics).
- Frames with a different `transfer_id` than the active one are ignored (RX locks onto the first valid transfer unless `--reset` is used).
- TX sends the HEADER frame at the start of every loop **and** repeated every `--header-every` DATA frames (default 10), so RX can join mid-stream.

## 5. Implementation steps

Each step has acceptance criteria. Do not start the next step until tests for the current step pass.

### Step 1 – Project scaffold

- Create folder structure, `requirements.txt`, empty modules with docstrings.
- Acceptance: `python -c "import qrxfer"` works.

### Step 2 – `protocol.py`

- Constants: `MAGIC`, `VERSION`, `TYPE_HEADER`, `TYPE_DATA`.
- Dataclass `Frame(type, transfer_id, index, total, payload)`.
- `encode_frame(frame) -> str` (Base64url string).
- `decode_frame(text: str) -> Frame` raising `FrameError` on any validation failure.
- Acceptance (`tests/test_protocol.py`):
  - encode/decode roundtrip for HEADER and DATA.
  - flipping any single bit in the raw bytes raises `FrameError`.
  - wrong magic, wrong version, truncated frame raise `FrameError`.

### Step 3 – `chunker.py`

- `sha256_file(path) -> str`.
- `split_file(path, chunk_size, compress) -> (header_dict, list[bytes])`.
- `join_chunks(chunks: dict[int, bytes], header) -> bytes` (handles decompression).
- Acceptance (`tests/test_chunker.py`):
  - roundtrip with sizes: 0 bytes, 1 byte, exactly `chunk_size`, `chunk_size + 1`, 1 MB random.
  - compressed and uncompressed variants.
  - `sha256` matches the original after join.

### Step 4 – `qr_render.py` and `qr_decode.py`

- `render_qr(text, ec, box_size, border) -> np.ndarray` (grayscale uint8, white background, black modules, quiet zone ≥ 4 modules).
- `decode_qr(image: np.ndarray) -> list[str]` using `cv2.QRCodeDetector`; if `pyzbar` is installed, use it as primary and OpenCV as fallback.
- Preprocessing in decoder (try in order until success): original, grayscale, Otsu threshold, adaptive threshold, 2x upscale.
- Acceptance (`tests/test_roundtrip.py`):
  - render then decode 100 random frames at default chunk size without loss.
  - decode still succeeds after Gaussian blur (kernel 3) and 0.7x downscale of the rendered image.

### Step 5 – `tx.py`

CLI:

```
python -m qrxfer.tx FILE [--chunk-size 600] [--ec M] [--fps 4]
                         [--compress] [--loops 0] [--header-every 10]
                         [--fullscreen] [--scale 8]
```

- Build header and chunks, build frame sequence: `HEADER, D0..D(k-1)` repeated, with extra HEADER every `--header-every` DATA frames.
- Render the first QR immediately and keep memory bounded for large transfers; cache and reuse the HEADER image instead of pre-rendering every DATA image.
- Display with OpenCV window (`cv2.imshow`), image scaled with nearest-neighbor, centered on a white canvas. Overlay is **outside** the QR area: text line with `transfer_id`, `frame i/n`, `loop L`. The overlay must not touch the QR or its quiet zone.
- Keys: `q`/`ESC` quit, `space` pause.
- `--loops 0` means infinite.
- Acceptance: running TX on a test file shows cycling QR codes; console prints frame count, estimated duration per loop.

### Step 6 – `capture.py`

Abstract `FrameSource` with `read() -> np.ndarray | None` and `close()`.

Implementations:

- `CameraSource(index)` via `cv2.VideoCapture`.
- `ScreenSource(monitor, region)` via `mss`.
- `FolderSource(path)` reading images in sorted order (for offline tests).

Acceptance: each source returns BGR or grayscale `np.ndarray`; `FolderSource` used in tests.

### Step 7 – `rx.py`

CLI:

```
python -m qrxfer.rx --source camera|screen|folder [--index 0] [--monitor 1]
                    [--region x,y,w,h] [--path DIR] [--out OUTDIR] [--reset]
                    [--timeout SECONDS]
```

Receive state machine (`Receiver` class, independent from capture and GUI, fully unit-testable):

- States: `WAIT_HEADER` → `RECEIVING` → `COMPLETE` | `FAILED`.
- `feed(frame_text) -> Event` for each decoded string.
- Stores `chunks: dict[int, bytes]`; duplicates ignored (if a duplicate differs from the stored chunk, count a conflict and keep the first).
- DATA frames received before the HEADER may be buffered (bounded, e.g. 2000 frames) and applied once the matching HEADER arrives.
- On all chunks present: join, decompress if needed, compute SHA-256, compare to header.
  - Match: write file to `--out` (use basename of `filename` only; reject path separators), state `COMPLETE`, exit code `0`.
  - Mismatch: state `FAILED`, do not write the file as valid output, print expected vs actual hash, exit code `2`.
- Live progress on console (single updating line): `received/total`, percentage, missing count, frames decoded, frames rejected (CRC), elapsed time.
- On `--timeout` without completion: print list of missing chunk indices (compressed to ranges), exit code `3`.
- Deduplicate decode work: skip identical consecutive decode results quickly.

Acceptance (`tests/test_rx_state.py`):

- Feed frames in random order with 30% random duplicates → `COMPLETE`, hash OK.
- Drop one chunk → never completes; missing list correct.
- Corrupt one chunk payload but keep a valid CRC (simulated) → `FAILED` on SHA-256 mismatch.
- Join mid-stream (no HEADER first) → completes after HEADER arrives.
- Malicious filename `../../x` → written as `x` inside `--out` only.

### Step 8 – End-to-end test

- Script `tests/test_e2e_offline.py`: run TX frame generation, render images to a temp folder, run RX with `FolderSource`, compare output file byte-for-byte.
- Manual test document in `README.md`: two PCs, TX fullscreen, RX with camera or screen region; recommended settings table (chunk size vs. distance/camera quality).

### Step 9 – Robustness and tuning

- `--auto-tune` in TX is **not** required. Instead document tuning: lower `--chunk-size` and `--fps` if RX reject count is high.
- RX statistics at the end: unique frames, duplicates, CRC rejects, decode failures, effective throughput (bytes/s).
- Optional: RX `--save-debug DIR` writing frames that failed decoding.

### Step 10 – Documentation and packaging

- `README.md`: install, usage examples, protocol summary, limits, troubleshooting (moire, reflections, camera focus, screen brightness, display scaling).
- Console entry points `qrxfer-tx`, `qrxfer-rx`, and `qrxfer` (desktop GUI) in `pyproject.toml`.

## 6. Coding rules for Copilot

- Type hints everywhere, `from __future__ import annotations`.
- No global state; pass configuration via dataclasses or arguments.
- No `print` inside library modules; use `logging`. CLI modules may print progress.
- Pure functions in `protocol.py` and `chunker.py` (no I/O except file reading in `chunker`).
- Do not add dependencies beyond section 2 without asking.
- Every public function has a docstring and at least one test.
- Keep the packet format exactly as specified in section 4. If a change seems necessary, stop and ask.

## 7. Risks and known limits

| Risk | Mitigation |
|---|---|
| Camera cannot resolve dense QR codes | smaller `--chunk-size`, `--ec Q`, larger `--scale` |
| Screen refresh vs. fps aliasing (frame blends) | keep `--fps` ≤ 5; show each frame for a fixed duration; RX relies on CRC to reject blends |
| Moire pattern when camera films screen | use `--source screen` (direct capture) when TX and RX share a desktop/remote session; otherwise adjust distance and angle |
| Large files take very long | document throughput estimate: `chunk_size * fps` bytes/s upper bound per loop; use `--compress` |
| One chunk never decodes | loop mode retransmits; RX reports missing indices on timeout |

## 8. Definition of done

- All tests in `tests/` pass.
- Offline end-to-end test reproduces a 100 KB random file byte-identical.
- Manual two-PC test transfers a 10 KB text file with SHA-256 verified.
- README documents usage and limits.
