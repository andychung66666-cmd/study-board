import os
import socket
import threading
import math
import struct
import time
import wave

import pytest
import uvicorn

from talkboard.config import Settings
from talkboard.server import create_app

playwright_sync = pytest.importorskip("playwright.sync_api")

FAKE_MEDIA_FLAGS = [
    "--no-sandbox",
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "server did not start"
        time.sleep(0.05)
    yield type("Live", (), {"url": f"http://127.0.0.1:{port}", "app": app})
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def launch_browser():
    """Returns a function that opens a page with a fake microphone.

    CHROMIUM_PATH points at an installed Chromium when Playwright's own
    pinned browser is not available (the cloud sandbox).
    """
    with playwright_sync.sync_playwright() as playwright:
        browsers = []

        def launch(extra_flags=()):
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                args=[*FAKE_MEDIA_FLAGS, *extra_flags],
            )
            browsers.append(browser)
            context = browser.new_context(permissions=["microphone"])
            return context.new_page()

        yield launch
        for browser in browsers:
            browser.close()


@pytest.fixture
def silent_wav(tmp_path):
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 16000 * 30)
    return path


@pytest.fixture
def tone_wav(tmp_path):
    """A steady 440 Hz tone: unlike Chrome's default beep, it is loud in every window."""
    path = tmp_path / "tone.wav"
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * n / 16000)))
        for n in range(16000 * 30)
    )
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(frames)
    return path
