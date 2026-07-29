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
    sock = socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=120)
    
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


def pump(src, dst):
    """Unidirectional pump from src to dst. Runs until EOF or error."""
    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    timeout = 3600

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

            # Two dedicated pump threads (no select-on-same-socket race)
            up_thread = threading.Thread(
                target=pump, args=(self.connection, remote), daemon=True
            )
            down_thread = threading.Thread(
                target=pump, args=(remote, self.connection), daemon=True
            )
            up_thread.start()
            down_thread.start()
            down_thread.join(timeout=3600)
            # Force cleanup when downstream finishes
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                remote.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            up_thread.join(timeout=60)
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
            resp = urllib.request.urlopen(req, timeout=60)
            
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
        request_queue_size = 128
    
    with ThreadedServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
