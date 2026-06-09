#!/usr/bin/env python3
"""HALO Desktop — native window wrapper for the HALO dashboard."""

import os, sys, threading, socket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port):
    from wsgiref.simple_server import make_server
    from server import handle
    httpd = make_server("127.0.0.1", port, handle)
    httpd.serve_forever()


def _wait_for_server(port, timeout=10):
    import time
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            time.sleep(0.2)
    return False


def main():
    port = _find_free_port()
    t = threading.Thread(target=_start_server, args=(port,), daemon=True)
    t.start()

    if not _wait_for_server(port):
        import sys
        print("ERROR: Server failed to start within 10s", file=sys.stderr)
        sys.exit(1)

    import webview
    webview.create_window(
        title="HALO — AI Assistant",
        url=f"http://127.0.0.1:{port}",
        width=1400,
        height=900,
        min_size=(960, 600),
        resizable=True,
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
