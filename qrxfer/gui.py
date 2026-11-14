"""Desktop launcher for the QR transmitter and receiver."""

from __future__ import annotations

import queue
import math
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Mapping


def build_command(mode: str, settings: Mapping[str, str | bool]) -> list[str]:
    """Build the CLI command for the selected mode and GUI settings."""
    if mode == "tx":
        file_path = Path(str(settings.get("file", "")))
        if not file_path.is_file():
            raise ValueError("Choose an existing file to transmit.")
        chunk_size = _positive_int(settings.get("chunk_size", "600"), "Chunk size")
        if chunk_size > 65535:
            raise ValueError("Chunk size cannot exceed 65535 bytes.")
        fps = _positive_float(settings.get("fps", "4"), "FPS")
        scale = _positive_int(settings.get("scale", "8"), "Display scale")
        ec = str(settings.get("ec", "M"))
        if ec not in ("L", "M", "Q", "H"):
            raise ValueError("Choose an error correction level: L, M, Q, or H.")
        command = [
            sys.executable, "-u", "-m", "qrxfer.tx", str(file_path),
            "--chunk-size", str(chunk_size),
            "--ec", ec,
            "--fps", str(fps),
            "--scale", str(scale),
        ]
        if bool(settings.get("compress", False)):
            command.append("--compress")
        if bool(settings.get("fullscreen", False)):
            command.append("--fullscreen")
        return command

    if mode != "rx":
        raise ValueError("Choose transmitter or receiver mode.")

    source = str(settings.get("source", "camera"))
    timeout = _positive_float(settings.get("timeout", "60"), "Timeout")
    command = [
        sys.executable, "-u", "-m", "qrxfer.rx",
        "--source", source,
        "--out", str(settings.get("out", ".")),
        "--timeout", str(timeout),
    ]
    if source == "camera":
        index = _nonnegative_int(settings.get("index", "0"), "Camera index")
        command.extend(["--index", str(index)])
    elif source == "screen":
        monitor = _positive_int(settings.get("monitor", "1"), "Monitor")
        command.extend(["--monitor", str(monitor)])
        region = str(settings.get("region", "")).strip()
        if region:
            _validate_region(region)
            command.extend(["--region", region])
    elif source == "folder":
        folder = str(settings.get("path", "")).strip()
        if not Path(folder).is_dir():
            raise ValueError("Choose an existing image folder for folder capture.")
        command.extend(["--path", folder, "--no-preview"])
    else:
        raise ValueError("Choose a supported receiver source.")
    if bool(settings.get("reset", False)):
        command.append("--reset")
    return command


def _positive_int(value: str | bool, label: str) -> int:
    """Parse a positive integer setting or report a GUI-friendly error."""
    try:
        number = int(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a positive integer.") from exc
    if number <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return number


def _nonnegative_int(value: str | bool, label: str) -> int:
    """Parse a non-negative integer setting or report a GUI-friendly error."""
    try:
        number = int(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a non-negative integer.") from exc
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer.")
    return number


def _positive_float(value: str | bool, label: str) -> float:
    """Parse a positive floating-point setting or report a GUI-friendly error."""
    try:
        number = float(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must be a positive number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive number.")
    return number


def _validate_region(region: str) -> None:
    """Validate a screen capture region before starting the receiver."""
    try:
        values = [int(value) for value in region.split(",")]
    except ValueError as exc:
        raise ValueError("Region must use x,y,width,height integer values.") from exc
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("Region must use x,y,width,height with positive dimensions.")


class QrXferApp:
    """Tkinter application for starting and stopping QR transfers."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QR File Transfer")
        self.root.minsize(680, 650)
        self.root.geometry("760x760")
        self.mode = tk.StringVar(value="tx")
        self.file = tk.StringVar()
        self.chunk_size = tk.StringVar(value="600")
        self.ec = tk.StringVar(value="M")
        self.fps = tk.StringVar(value="4")
        self.scale = tk.StringVar(value="8")
        self.compress = tk.BooleanVar(value=False)
        self.fullscreen = tk.BooleanVar(value=True)
        self.source = tk.StringVar(value="camera")
        self.index = tk.StringVar(value="0")
        self.monitor = tk.StringVar(value="1")
        self.region = tk.StringVar()
        self.path = tk.StringVar()
        self.out = tk.StringVar(value=str(Path.cwd() / "received"))
        self.timeout = tk.StringVar(value="300")
        self.reset = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready")
        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.reader_thread: threading.Thread | None = None
        self.closing = False

        self._configure_style()
        self._build_layout()
        self._show_mode()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_process)
        self.root.after(100, self._drain_output)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Start.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 8))

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=(24, 20))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="QR File Transfer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Send a file as QR codes or receive one from a screen or camera.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        mode_frame = ttk.LabelFrame(
            outer, text="Choose a mode", style="Section.TLabelframe", padding=12
        )
        mode_frame.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(
            mode_frame, text="Transmit a file", value="tx", variable=self.mode,
            command=self._show_mode,
        ).pack(side="left", padx=(2, 24))
        ttk.Radiobutton(
            mode_frame, text="Receive a file", value="rx", variable=self.mode,
            command=self._show_mode,
        ).pack(side="left")

        self.tx_frame = ttk.LabelFrame(
            outer, text="Transmitter settings", style="Section.TLabelframe", padding=12
        )
        self._build_tx_settings()
        self.rx_frame = ttk.LabelFrame(
            outer, text="Receiver settings", style="Section.TLabelframe", padding=12
        )
        self._build_rx_settings()

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(12, 8))
        self.start_button = ttk.Button(
            controls, text="Start transfer", style="Start.TButton", command=self._start
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls, text="Stop", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Label(controls, textvariable=self.status).pack(side="right")

        log_frame = ttk.LabelFrame(
            outer, text="Activity", style="Section.TLabelframe", padding=8
        )
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(
            log_frame, height=10, wrap="word", state="disabled",
            font=("Consolas", 9), relief="flat", padx=8, pady=8,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._append_log("Choose a mode and configure the transfer.")

    def _build_tx_settings(self) -> None:
        self.tx_frame.columnconfigure(1, weight=1)
        ttk.Label(self.tx_frame, text="File to send").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        ttk.Entry(self.tx_frame, textvariable=self.file).grid(
            row=0, column=1, sticky="ew", pady=5
        )
        ttk.Button(self.tx_frame, text="Browse...", command=self._browse_file).grid(
            row=0, column=2, padx=(8, 0), pady=5
        )
        options = ttk.Frame(self.tx_frame)
        options.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self._labeled_entry(options, "Chunk size", self.chunk_size, 0, width=8)
        ttk.Label(options, text="Error correction").grid(
            row=0, column=2, sticky="w", padx=(14, 5)
        )
        ttk.Combobox(
            options, textvariable=self.ec, values=("L", "M", "Q", "H"),
            state="readonly", width=5,
        ).grid(row=0, column=3, sticky="w")
        self._labeled_entry(options, "FPS", self.fps, 0, column=4, width=6, pad=14)
        self._labeled_entry(options, "Display scale", self.scale, 0, column=6, width=5, pad=14)
        ttk.Checkbutton(
            self.tx_frame, text="Compress data", variable=self.compress
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            self.tx_frame, text="Fullscreen QR display", variable=self.fullscreen
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))

    def _build_rx_settings(self) -> None:
        self.rx_frame.columnconfigure(1, weight=1)
        ttk.Label(self.rx_frame, text="Capture source").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        source_box = ttk.Combobox(
            self.rx_frame, textvariable=self.source,
            values=("camera", "screen", "folder"), state="readonly", width=16,
        )
        source_box.grid(row=0, column=1, sticky="w", pady=5)
        source_box.bind("<<ComboboxSelected>>", lambda _event: self._show_source_fields())

        self.camera_fields = ttk.Frame(self.rx_frame)
        self.camera_fields.grid(row=1, column=0, columnspan=3, sticky="ew")
        self._labeled_entry(self.camera_fields, "Camera index", self.index, 0, width=8)

        self.screen_fields = ttk.Frame(self.rx_frame)
        self.screen_fields.grid(row=1, column=0, columnspan=3, sticky="ew")
        self._labeled_entry(self.screen_fields, "Monitor", self.monitor, 0, width=8)
        self._labeled_entry(
            self.screen_fields, "Region x,y,w,h (optional)", self.region, 0,
            column=2, width=22, pad=14,
        )

        self.folder_fields = ttk.Frame(self.rx_frame)
        self.folder_fields.columnconfigure(1, weight=1)
        ttk.Label(self.folder_fields, text="Image folder").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        ttk.Entry(self.folder_fields, textvariable=self.path).grid(
            row=0, column=1, sticky="ew", pady=5
        )
        ttk.Button(
            self.folder_fields, text="Browse...", command=self._browse_folder
        ).grid(row=0, column=2, padx=(8, 0), pady=5)

        ttk.Label(self.rx_frame, text="Save received file in").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=5
        )
        ttk.Entry(self.rx_frame, textvariable=self.out).grid(
            row=2, column=1, sticky="ew", pady=5
        )
        ttk.Button(
            self.rx_frame, text="Browse...", command=self._browse_output
        ).grid(row=2, column=2, padx=(8, 0), pady=5)
        self._labeled_entry(
            self.rx_frame, "Timeout (seconds)", self.timeout, 3, width=10,
        )
        ttk.Checkbutton(
            self.rx_frame, text="Allow a new transfer to replace the current one",
            variable=self.reset,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._show_source_fields()

    @staticmethod
    def _labeled_entry(
        parent: ttk.Frame | ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        row: int,
        column: int = 0,
        width: int = 8,
        pad: int = 0,
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=column, sticky="w", padx=(pad, 5), pady=5
        )
        ttk.Entry(parent, textvariable=variable, width=width).grid(
            row=row, column=column + 1, sticky="w", pady=5
        )

    def _show_mode(self) -> None:
        self.tx_frame.pack_forget()
        self.rx_frame.pack_forget()
        if self.mode.get() == "tx":
            self.tx_frame.pack(fill="x")
        else:
            self.rx_frame.pack(fill="x")

    def _show_source_fields(self) -> None:
        for frame in (self.camera_fields, self.screen_fields, self.folder_fields):
            frame.grid_remove()
        selected = {
            "camera": self.camera_fields,
            "screen": self.screen_fields,
            "folder": self.folder_fields,
        }.get(self.source.get())
        if selected is not None:
            selected.grid()

    def _browse_file(self) -> None:
        selected = filedialog.askopenfilename(title="Choose a file to transmit")
        if selected:
            self.file.set(selected)

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose a folder of QR images")
        if selected:
            self.path.set(selected)

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose where received files are saved")
        if selected:
            self.out.set(selected)

    def _start(self) -> None:
        try:
            command = build_command(self.mode.get(), self._settings())
        except ValueError as exc:
            messagebox.showerror("Check transfer settings", str(exc), parent=self.root)
            return
        try:
            self.process = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parent.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            messagebox.showerror("Unable to start transfer", str(exc), parent=self.root)
            self.process = None
            return

        self.status.set("Transmitting..." if self.mode.get() == "tx" else "Receiving...")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._append_log(f"Started: {subprocess.list2cmdline(command)}")
        self.reader_thread = threading.Thread(
            target=self._read_output, args=(self.process,), daemon=True
        )
        self.reader_thread.start()

    def _settings(self) -> dict[str, str | bool]:
        return {
            "file": self.file.get(),
            "chunk_size": self.chunk_size.get(),
            "ec": self.ec.get(),
            "fps": self.fps.get(),
            "scale": self.scale.get(),
            "compress": self.compress.get(),
            "fullscreen": self.fullscreen.get(),
            "source": self.source.get(),
            "index": self.index.get(),
            "monitor": self.monitor.get(),
            "region": self.region.get(),
            "path": self.path.get(),
            "out": self.out.get(),
            "timeout": self.timeout.get(),
            "reset": self.reset.get(),
        }

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        line: list[str] = []
        while True:
            character = process.stdout.read(1)
            if not character:
                break
            if character in ("\r", "\n"):
                if line:
                    self.output_queue.put("".join(line))
                    line.clear()
            else:
                line.append(character)
        if line:
            self.output_queue.put("".join(line))
        process.stdout.close()

    def _drain_output(self) -> None:
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
        if self.root.winfo_exists():
            self.root.after(100, self._drain_output)

    def _poll_process(self) -> None:
        if self.process is not None:
            return_code = self.process.poll()
            if return_code is not None:
                self._append_log(f"Process finished with exit code {return_code}.")
                self.process = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set("Ready" if return_code == 0 else "Finished with errors")
        if self.closing and self.process is None:
            self.root.destroy()
            return
        if self.root.winfo_exists():
            self.root.after(150, self._poll_process)

    def _stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.status.set("Stopping...")
        self._append_log("Stopping transfer...")
        self.process.terminate()
        self.stop_button.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self.closing = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.status.set("Stopping before exit...")
        else:
            self.root.destroy()


def main() -> int:
    """Start the desktop application."""
    root = tk.Tk()
    QrXferApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
