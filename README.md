# QR File Transfer

`qrxfer` transfers a file one way between computers using a looping sequence of
QR codes. Every frame has a CRC32, and the complete uncompressed file is
verified with SHA-256 before the receiver writes it.

## Install

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Or install the package and its command-line entry points:

```powershell
python -m pip install .
```

## Usage

Launch the desktop interface:

```powershell
python -m qrxfer.gui
```

Choose **Transmit a file** to browse for a file and configure QR settings, or
choose **Receive a file** to select a camera, screen, or folder of QR images.
The GUI starts the existing command-line tool in the background, shows its
progress, and provides a Stop button. After installing the package,
`qrxfer` opens the same interface.

Transmit a file, repeating until stopped with `q` or `Esc`:

```powershell
python -m qrxfer.tx .\document.pdf --chunk-size 600 --ec M --fps 4
```

Receive from a camera:

```powershell
python -m qrxfer.rx --source camera --index 0 --out .\received --timeout 300
```

Receive from the screen (useful when both ends run in one desktop session):

```powershell
python -m qrxfer.rx --source screen --monitor 1 --region 100,100,900,900 --out .\received
```

Offline receive from a folder of QR images:

```powershell
python -m qrxfer.rx --source folder --path .\frames --out .\received --no-preview
```

The transmitter accepts `--compress`, `--loops N` (`0` means repeat forever),
`--header-every N`, `--fullscreen`, and `--scale N`. The receiver accepts
`--reset` to allow a later transfer header to replace its currently selected
transfer. The `qrxfer-tx` and `qrxfer-rx` commands are also available after
installing the package.

## Protocol summary

Each QR contains unpadded URL-safe Base64 text for a binary frame. Frame
integers are big-endian. The fixed prefix contains magic `QX`, version `1`,
frame type, transfer ID, chunk index, total chunks, and payload length. The
payload is followed by CRC32 over the prefix and payload. Header payloads are
UTF-8 JSON; data payloads contain raw file bytes (or a zlib stream when
compression is enabled). The header records the original file size and
SHA-256, so compressed transfers are checked after decompression.

The transmitter starts each loop with a header and repeats it every ten data
frames by default. Frames from other transfer IDs are ignored unless reset
behavior is enabled. Missing frames are recovered by subsequent loops; there
is no return channel or encryption.

## Tuning and limits

| Chunk size | Typical use |
|---:|---|
| 200–400 bytes | Longer distance, smaller or noisier camera view |
| 600 bytes | Default balance for screen and camera capture |
| 800+ bytes | Short distance, sharp focus, high-resolution capture |

QR density rises with chunk size. If the receiver reports many CRC rejects,
reduce `--chunk-size` and/or `--fps`; keep the frame rate at or below 5 fps to
reduce display/camera refresh aliasing. `--compress` is useful for compressible
content. A rough upper bound is `chunk_size * fps` bytes per second, before QR
overhead, repeated headers, and retransmission loops.

For a manual two-PC test, start the receiver first, then display the
transmitter fullscreen. Keep the whole QR and its quiet zone inside the
camera's view. Adjust distance and angle to avoid reflections and moire,
improve focus and screen brightness, and disable display scaling where
possible. Screen capture can be used instead of a camera when both processes
share a desktop.

## Tests

```powershell
python -m pip install pytest
python -m pytest
```

The offline end-to-end test renders a 100 KB random file into QR images,
receives them through the folder source, and compares the output byte for
byte. A manual two-PC test should additionally verify a 10 KB text file by
checking the receiver's reported SHA-256.
