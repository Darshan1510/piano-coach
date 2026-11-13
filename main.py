"""Riyaz: start the local server and open the app window (same pattern as DocKit).

  uv run main.py             # app window
  uv run main.py --browser   # open in the default browser instead
  uv run main.py --server    # server only (tests, latency measurement)
  PORT=8123 uv run main.py   # other port (if busy, the app takes a free port)
"""

import logging
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from riyaz import config
from riyaz.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("riyaz")

app = create_app()


# midi.stop() can take up to about 15 s (10 s task timeout + 5 s thread join). Wait longer.
SHUTDOWN_WAIT_S = 25.0
STARTUP_WAIT_S = 20.0  # the first MIDI port scan can take up to 10 s


def bind_socket(preferred: int) -> socket.socket:
    """Bind the preferred port. If it is busy, bind a free port.

    The bound socket goes to uvicorn, so no other program can take the port between the
    check and the start of the server.
    """
    for port in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # same as uvicorn
        try:
            s.bind((config.HOST, port))
        except OSError:
            s.close()
            log.warning("Port %d is busy. The app uses a free port.", preferred)
            continue
        return s
    raise RuntimeError("No free port")


SOCKET = bind_socket(config.requested_port())
PORT = SOCKET.getsockname()[1]
URL = f"http://{config.HOST}:{PORT}"


server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=PORT, log_level="info"))


def run_server():
    server.run(sockets=[SOCKET])


def wait_for_server(thread: threading.Thread, timeout: float = STARTUP_WAIT_S) -> bool:
    """Open the window only when the server answers. False if it did not start."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not server.started and thread.is_alive():
        time.sleep(0.05)
    return server.started


def prevent_app_nap():
    """macOS App Nap can slow timers of a background app. Ask macOS not to do this."""
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import NSProcessInfo
    except ImportError:
        return None
    # NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical
    options = (0x00FFFFFF & ~(1 << 20)) | 0xFF00000000
    return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        options, "Riyaz listens to the MIDI keyboard")


if __name__ == "__main__":
    _activity = prevent_app_nap()  # keep a reference for the life of the app
    log.info("Riyaz at %s (data: %s)", URL, config.data_dir())

    if "--server" in sys.argv:
        run_server()
        sys.exit(0)

    if "--browser" in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=[URL]).start()
        run_server()
        sys.exit(0)

    import webview

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    if not wait_for_server(thread):
        log.error("The server did not start in %.0f s (%s). The app stops.", STARTUP_WAIT_S, URL)
        server.should_exit = True
        thread.join(timeout=SHUTDOWN_WAIT_S)
        sys.exit(1)
    webview.create_window("Riyaz", URL, width=1280, height=820, min_size=(1100, 680))
    webview.start()
    # Window closed: stop the server so that shutdown code runs (MIDI ports close, Local On).
    server.should_exit = True
    thread.join(timeout=SHUTDOWN_WAIT_S)
    if thread.is_alive():
        log.error("The server did not stop in %.0f s.", SHUTDOWN_WAIT_S)
