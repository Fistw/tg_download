import socket
import time
import urllib.request

from src.config import WebDAVServerConfig
from src.webdav_server import ThreadingWSGIServer, WebDAVServer


def _wait_for_server(server: WebDAVServer, timeout: float = 3.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server._httpd is not None:
            return int(server._httpd.server_address[1])
        time.sleep(0.02)
    raise AssertionError("server did not start")


def test_threading_server_uses_configurable_backlog():
    class ConfiguredServer(ThreadingWSGIServer):
        request_queue_size = 321

    assert ConfiguredServer.request_queue_size == 321
    assert ConfiguredServer.daemon_threads is True


def test_slow_client_does_not_block_health_check(tmp_path):
    config = WebDAVServerConfig(
        enable=False,
        host="127.0.0.1",
        port=0,
        health_check_enabled=False,
        server_backlog=32,
    )
    server = WebDAVServer(config, str(tmp_path))
    server.start()
    slow_socket = None

    try:
        port = _wait_for_server(server)

        slow_socket = socket.create_connection(("127.0.0.1", port), timeout=1)
        slow_socket.sendall(b"GET ")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            assert response.status == 200
            assert response.read() == b"OK"
    finally:
        if slow_socket is not None:
            slow_socket.close()
        server.stop()
