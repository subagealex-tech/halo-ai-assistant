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


def main():
    port = _find_free_port()
    t = threading.Thread(target=_start_server, args=(port,), daemon=True)
    t.start()

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


if __name__ == "__main__":
    main()
