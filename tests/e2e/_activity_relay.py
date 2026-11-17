"""A controllable network relay for the real activity SSE endpoint."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from threading import Lock, Thread

from tests.e2e._api import ApiClient


class ActivityRelay:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client
        self.lock = Lock()
        self.blocked = False
        self.clients: set[socket.socket] = set()
        self.url = ''

    def disconnect(self) -> None:
        with self.lock:
            self.blocked = True
            for client in self.clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()

    def resume(self) -> None:
        with self.lock:
            self.blocked = False


@contextmanager
def activity_relay(api_client: ApiClient):
    relay = ActivityRelay(api_client)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', 'X-Requested-With')
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_GET(self):
            with relay.lock:
                blocked = relay.blocked
                if not blocked:
                    relay.clients.add(self.connection)
            if blocked:
                # Refuse the connection instead of responding with a terminal
                # HTTP status: native EventSource must keep retrying.
                self.close_connection = True
                return
            try:
                with relay.api_client.open_stream('GET', '/api/chat/activity', timeout=30) as upstream:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    while line := upstream.readline():
                        self.wfile.write(line)
                        self.wfile.flush()
            except (OSError, ValueError):
                pass
            finally:
                with relay.lock:
                    relay.clients.discard(self.connection)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    relay.url = f'http://127.0.0.1:{server.server_port}/api/chat/activity'
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield relay
    finally:
        relay.disconnect()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
