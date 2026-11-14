"""Tests for desktop launcher command construction and validation."""

from __future__ import annotations

import sys

import pytest

from qrxfer import gui
from qrxfer.gui import build_command


def test_transmitter_command_includes_file_and_options(tmp_path) -> None:
    """Transmit settings become the matching CLI arguments."""
    file_path = tmp_path / "to send.bin"
    file_path.write_bytes(b"payload")
    command = build_command(
        "tx",
        {
            "file": str(file_path),
            "chunk_size": "400",
            "ec": "Q",
            "fps": "2",
            "scale": "6",
            "compress": True,
            "fullscreen": True,
        },
    )
    assert command[:4] == [sys.executable, "-u", "-m", "qrxfer.tx"]
    assert str(file_path) in command
    assert command[command.index("--chunk-size") + 1] == "400"
    assert command[command.index("--ec") + 1] == "Q"
    assert "--compress" in command
    assert "--fullscreen" in command


@pytest.mark.parametrize(
    ("source", "source_args"),
    [
        ("camera", ["--index", "2"]),
        ("screen", ["--monitor", "2", "--region", "10,20,800,600"]),
    ],
)
def test_receiver_command_for_live_source(source, source_args) -> None:
    """Camera and screen receiver settings are passed to the CLI."""
    command = build_command(
        "rx",
        {
            "source": source,
            "index": "2",
            "monitor": "2",
            "region": "10,20,800,600",
            "out": "received files",
            "timeout": "120",
        },
    )
    assert command[:4] == [sys.executable, "-u", "-m", "qrxfer.rx"]
    assert command[command.index("--source") + 1] == source
    assert command[command.index("--timeout") + 1] == "120.0"
    for argument in source_args:
        assert argument in command


def test_folder_receiver_uses_offline_mode(tmp_path) -> None:
    """Folder capture receives images without opening a preview window."""
    command = build_command(
        "rx",
        {"source": "folder", "path": str(tmp_path), "out": ".", "timeout": "30"},
    )
    assert command[command.index("--path") + 1] == str(tmp_path)
    assert "--no-preview" in command


def test_invalid_gui_settings_are_rejected(tmp_path) -> None:
    """The launcher gives clear validation errors before spawning a process."""
    with pytest.raises(ValueError, match="existing file"):
        build_command("tx", {"file": str(tmp_path / "missing")})
    with pytest.raises(ValueError, match="positive integer"):
        build_command(
            "tx",
            {"file": str(_make_file(tmp_path)), "chunk_size": "0"},
        )
    with pytest.raises(ValueError, match="Region"):
        build_command("rx", {"source": "screen", "region": "a,b,c,d"})
    with pytest.raises(ValueError, match="positive number"):
        build_command("rx", {"source": "camera", "timeout": "nan"})


def _make_file(folder) -> str:
    """Create a small fixture file for command validation tests."""
    path = folder / "input.bin"
    path.write_bytes(b"data")
    return str(path)


def test_main_starts_the_desktop_application(monkeypatch) -> None:
    """The module entry point creates the app and runs Tk's event loop."""
    class FakeRoot:
        called = False

        def mainloop(self) -> None:
            self.called = True

    root = FakeRoot()
    monkeypatch.setattr(gui.tk, "Tk", lambda: root)
    monkeypatch.setattr(gui, "QrXferApp", lambda _root: None)
    assert gui.main() == 0
    assert root.called
