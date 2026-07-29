"""
TCP relay server (runs on the host / Mac side).

Watches for TCP connection requests in the shared filesystem,
establishes real TCP connections to the target hosts, and relays
data bidirectionally through the filesystem.
"""

import logging
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .tcp_protocol import TcpBridgeDirectory, TcpConnection
from .security import LOCAL_HOSTS, is_host_allowed

logger = logging.getLogger("virtio-bridge.tcp-relay")


class TcpRelayHandler:
    """Handles a single TCP connection relay."""

    def __init__(self, conn: TcpConnection, target_sock: socket.socket, dest: str = "", cid: str = ""):
        self.conn = conn
        self.target = target_sock
        self.dest = dest
        self.cid = cid

    def relay(self) -> None:
        """Run bidirectional relay. Blocks until connection closes."""
        conn_id = self.conn.conn_id
        label = f"{self.dest or '?'} [{self.cid or conn_id[:4]}]"
        stop_event = threading.Event()

        # Thread: read from upstream file → write to target socket
        def upstream_pump():
            try:
                for chunk in self.conn.iter_upstream(timeout=300):
                    if stop_event.is_set():
                        break
                    try:
                        self.target.sendall(chunk)
                    except (socket.error, OSError) as e:
                        logger.debug(f"↖ {label} upstream send error: {e}")
                        break
            except Exception as e:
                logger.warning(f"↖ {label} upstream pump error: {e}")
            finally:
                try:
                    self.target.shutdown(socket.SHUT_WR)
                except (socket.error, OSError):
                    pass

        # Thread: read from target socket → write to downstream file
        def downstream_pump():
            try:
                while True:
                    try:
                        data = self.target.recv(8192)
                    except (socket.error, OSError) as e:
                        logger.debug(f"↘ {label} downstream recv error: {e}")
                        stop_event.set()
                        break
                    if not data:
                        logger.debug(f"↘ {label} target closed (EOF)")
                        stop_event.set()
                        break
                    self.conn.write_downstream(data)
            except Exception as e:
                logger.warning(f"↘ {label} downstream pump error: {e}")
            finally:
                self.conn.close_downstream()

        up_thread = threading.Thread(target=upstream_pump, daemon=True)
        down_thread = threading.Thread(target=downstream_pump, daemon=True)
        up_thread.start()
        down_thread.start()

        up_thread.join(timeout=600)
        down_thread.join(timeout=600)

        self.target.close()
        logger.info(f"Relay finished: {self.dest or '?'}  [{self.cid or conn_id[:4]}]")


class TcpRelayServer:
    """
    Host-side TCP relay server.
    Watches for connection requests and establishes real TCP connections.
    """

    def __init__(self, bridge_dir: str | Path, allow_hosts: frozenset[str] | None = None, crypto=None):
        self.tcp_bridge = TcpBridgeDirectory(bridge_dir, crypto=crypto)
        self.allow_hosts = allow_hosts or LOCAL_HOSTS
        self._running = False
        self._active_conns: set[str] = set()

    def stop(self) -> None:
        self._running = False

    def _process_pending(self) -> None:
        """Process any pending connection requests."""
        pending = self.tcp_bridge.list_pending_connections()
        for conn_id in pending:
            if conn_id not in self._active_conns:
                self._active_conns.add(conn_id)
                self._handle_connection(conn_id)

    def _start_polling(self) -> None:
        """Poll for new connection requests."""
        cleanup_interval = 1200  # ~every 60s (1200 × 50ms)
        iteration = 0
        while self._running:
            pending = self.tcp_bridge.list_pending_connections()
            for conn_id in pending:
                if conn_id not in self._active_conns:
                    self._active_conns.add(conn_id)
                    self._handle_connection(conn_id)
            # Periodic cleanup of stale connection directories
            iteration += 1
            if iteration % cleanup_interval == 0:
                removed = self.tcp_bridge.cleanup_stale(max_age=300)
                if removed:
                    logger.info(f"Periodic cleanup: removed {removed} stale connections")
            time.sleep(0.05)  # 50ms poll interval
        logger.info("Polling loop exited, relay stopped")

    def _handle_connection(self, conn_id: str) -> None:
        """Handle a new connection request in a thread."""
        t = threading.Thread(
            target=self._do_handle_connection,
            args=(conn_id,),
            daemon=True,
        )
        t.start()

    def _do_handle_connection(self, conn_id: str) -> None:
        """Establish real TCP connection and start relay."""
        conn = self.tcp_bridge.new_connection(conn_id)
        try:
            req = conn.read_connect_request()
            if req is None:
                logger.warning(f"Connect request disappeared: {conn_id}")
                self._active_conns.discard(conn_id)
                return

            cid = conn_id[:4]
            scheme = {443: "HTTPS", 80: "HTTP", 22: "SSH", 5432: "PG"}.get(req.port, f":{req.port}")
            dest = f"{req.host}:{req.port}" if scheme.startswith(":") else f"{req.host} ({scheme})"
            start_time = time.time()

            logger.info(f"→ CONNECT {dest} [{cid}]")

            # Check host against allow list
            if not is_host_allowed(req.host, self.allow_hosts):
                msg = f"Host '{req.host}' is not in the allow list: {sorted(self.allow_hosts)}"
                logger.warning(f"✗ BLOCKED {dest} [{cid}]: {msg}")
                conn.signal_error(msg)
                return

            try:
                target_sock = socket.create_connection(
                    (req.host, req.port),
                    timeout=10,
                )
                target_sock.settimeout(None)  # Switch to blocking after connect
                # Disable Nagle — proxy should forward data immediately
                target_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # TCP keepalive: probe after 15s idle, every 15s, 3 probes max
                target_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    target_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
                if hasattr(socket, 'TCP_KEEPINTVL'):
                    target_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
                if hasattr(socket, 'TCP_KEEPCNT'):
                    target_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            except (socket.error, OSError) as e:
                logger.error(f"✗ FAILED {dest} [{cid}]: {e}")
                conn.signal_error(str(e))
                return

            conn.signal_established()
            elapsed = time.time() - start_time
            logger.info(f"✓ ESTABLISHED {dest} [{cid}] ({elapsed:.0f}s)")

            handler = TcpRelayHandler(conn, target_sock, dest, cid)
            handler.relay()

            elapsed = time.time() - start_time
            logger.info(f"← CLOSED {dest} [{cid}] ({elapsed:.0f}s)")
        finally:
            # Don't cleanup here — socks side may still need close_down.
            # cleanup_stale handles actual deletion when both sides are done.
            self._active_conns.discard(conn_id)

    def start(self) -> None:
        """Start the relay server using polling. Blocks until stopped."""
        self.tcp_bridge.init()

        removed = self.tcp_bridge.cleanup_stale(max_age=0)
        if removed:
            logger.info(f"Cleaned up {removed} stale connections")

        self._process_pending()

        self._running = True
        logger.info(f"TCP relay server started: watching {self.tcp_bridge.tcp_dir}")

        try:
            self._start_polling()
        except KeyboardInterrupt:
            logger.info("TCP relay interrupted")
        finally:
            self._running = False
            logger.info("TCP relay stopped")


def run_tcp_relay(bridge_dir: str, allow_hosts: frozenset[str] | None = None, crypto=None) -> None:
    """Entry point for running the TCP relay server."""
    server = TcpRelayServer(bridge_dir=bridge_dir, allow_hosts=allow_hosts, crypto=crypto)

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        server._running = False  # Causes _start_polling to exit

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("TCP relay stopped")
