#!/usr/bin/env python3
"""HTTP proxy → SOCKS5 bridge. Listens for HTTP proxy requests and forwards through SOCKS5."""

import http.server
import socketserver
import socket
import select
import struct
import sys
import threading

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 1080
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8080


def socks5_connect(host, port):
    """Establish a TCP connection through SOCKS5 proxy."""
    sock = socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=30)
    
    # SOCKS5 handshake
    sock.sendall(b"\x05\x01\x00")  # VER=5, NMETHODS=1, METHOD=0 (no auth)
    resp = sock.recv(2)
    if resp != b"\x05\x00":
        sock.close()
        raise ConnectionError(f"SOCKS5 handshake failed: {resp!r}")
    
    # SOCKS5 CONNECT request
    host_bytes = host.encode()
    req = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", port)
    sock.sendall(req)
    resp = sock.recv(10)
    if resp[1] != 0x00:
        sock.close()
        raise ConnectionError(f"SOCKS5 connect failed for {host}:{port}, code={resp[1]}")
    
    return sock


def relay(src, dst):
    """Bidirectional relay between two sockets."""
    sockets = [src, dst]
    while True:
        r, _, _ = select.select(sockets, [], [], 1)
        for s in r:
            try:
                data = s.recv(8192)
            except Exception:
                return
            if not data:
                return
            if s is src:
                dst.sendall(data)
            else:
                src.sendall(data)


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    timeout = 60

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

    def do_CONNECT(self):
        """Handle HTTPS CONNECT tunneling."""
        host, port = self.path.split(":")
        port = int(port)
        try:
            remote = socks5_connect(host, port)
            self.send_response(200, "Connection Established")
            self.end_headers()
            
            relay_thread = threading.Thread(target=relay, args=(self.connection, remote))
            relay_thread.daemon = True
            relay_thread.start()
            relay(remote, self.connection)
        except Exception as e:
            self.send_error(502, f"Connection failed: {e}")

    def _handle(self, method):
        """Handle HTTP proxied requests."""
        import urllib.request
        import urllib.error
        
        url = self.path
        body = None
        if method in ("POST", "PUT"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len else None
        
        # Use PySocks to route through SOCKS5
        original_socket = socket.socket
        import socks
        socket.socket = socks.socksocket
        socks.set_default_proxy(socks.SOCKS5, SOCKS_HOST, SOCKS_PORT)
        
        try:
            headers = {}
            for k, v in self.headers.items():
                if k.lower() not in ("host", "proxy-connection", "proxy-authorization"):
                    headers[k] = v
            
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            resp = urllib.request.urlopen(req, timeout=30)
            
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            
            chunk = resp.read(8192)
            while chunk:
                self.wfile.write(chunk)
                chunk = resp.read(8192)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, str(e))
        finally:
            socket.socket = original_socket

    def log_message(self, format, *args):
        sys.stderr.write(f"[http→socks] {self.address_string()} - {format % args}\n")


def main():
    import socks
    print(f"HTTP→SOCKS5 bridge: {LISTEN_HOST}:{LISTEN_PORT} → socks5://{SOCKS_HOST}:{SOCKS_PORT}")
    
    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True
    
    with ThreadedServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
