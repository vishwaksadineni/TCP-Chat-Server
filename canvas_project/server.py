from __future__ import annotations

import argparse
import logging
import re
import signal
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque


HELP_TEXT = """Commands:
  /list                 Show connected users
  /dm <user> <message>  Send a private message
  /rename <name>        Change your display name
  /history [count]      Show recent public chat history
  /stats                Show server statistics
  /help                 Show this help
  /quit                 Disconnect"""


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", name.strip())
    return cleaned[:24] or "guest"


class RateLimiter:
    def __init__(self, max_messages: int, window_seconds: float) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.events: Deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        while self.events and current - self.events[0] > self.window_seconds:
            self.events.popleft()
        if len(self.events) >= self.max_messages:
            return False
        self.events.append(current)
        return True


@dataclass
class ClientSession:
    conn: socket.socket
    address: tuple[str, int]
    name: str
    connected_at: float
    limiter: RateLimiter
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, message: str) -> None:
        with self.send_lock:
            self.conn.sendall(f"{message}\n".encode("utf-8"))


class ChatServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        history_size: int = 100,
        rate_limit: int = 8,
        rate_window: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.history: Deque[str] = deque(maxlen=history_size)
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self.clients: dict[str, ClientSession] = {}
        self.clients_lock = threading.RLock()
        self.shutdown_event = threading.Event()
        self.server_socket: socket.socket | None = None
        self.started_at = time.time()
        self.total_connections = 0
        self.total_messages = 0

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self.server_socket = server
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen()
            server.settimeout(0.5)
            logging.info("Server listening on %s:%s", self.host, self.port)
            print(f"Chat server listening on {self.host}:{self.port}")

            while not self.shutdown_event.is_set():
                try:
                    conn, address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                thread = threading.Thread(target=self.handle_client, args=(conn, address), daemon=True)
                thread.start()

        self.shutdown()

    def shutdown(self) -> None:
        if self.shutdown_event.is_set():
            return
        self.shutdown_event.set()
        logging.info("Server shutdown started")
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
        with self.clients_lock:
            sessions = list(self.clients.values())
        for session in sessions:
            self.safe_send(session, "[server] Server is shutting down.")
            self.disconnect(session)
        logging.info("Server shutdown complete")

    def handle_client(self, conn: socket.socket, address: tuple[str, int]) -> None:
        session: ClientSession | None = None
        try:
            conn.settimeout(300)
            conn.sendall(b"Enter username: \n")
            requested_name = self.read_line(conn)
            if requested_name is None:
                conn.close()
                return

            name = self.reserve_name(requested_name)
            session = ClientSession(
                conn=conn,
                address=address,
                name=name,
                connected_at=time.time(),
                limiter=RateLimiter(self.rate_limit, self.rate_window),
            )
            with self.clients_lock:
                self.clients[name] = session
                self.total_connections += 1

            logging.info("%s connected from %s:%s", name, address[0], address[1])
            self.safe_send(session, f"[server] Welcome, {name}. Type /help for commands.")
            self.broadcast(f"[{timestamp()}] [server] {name} joined the chat.", exclude=name)

            while not self.shutdown_event.is_set():
                line = self.read_line(conn)
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                if not session.limiter.allow():
                    self.safe_send(session, "[server] Rate limit exceeded. Slow down for a moment.")
                    logging.warning("Rate limit exceeded by %s", session.name)
                    continue
                if line.startswith("/"):
                    if self.handle_command(session, line):
                        break
                else:
                    self.post_public_message(session, line)
        except (ConnectionError, OSError) as exc:
            if session is not None:
                logging.info("%s disconnected with socket error: %s", session.name, exc)
        finally:
            if session is not None:
                self.disconnect(session)

    def read_line(self, conn: socket.socket) -> str | None:
        chunks: list[bytes] = []
        while not self.shutdown_event.is_set():
            try:
                chunk = conn.recv(1)
            except socket.timeout:
                continue
            if not chunk:
                return None
            if chunk == b"\n":
                break
            chunks.append(chunk)
            if len(chunks) > 4096:
                break
        if not chunks and self.shutdown_event.is_set():
            return None
        return b"".join(chunks).decode("utf-8", errors="replace").rstrip("\r")

    def reserve_name(self, requested_name: str) -> str:
        base = sanitize_name(requested_name)
        with self.clients_lock:
            if base not in self.clients:
                return base
            suffix = 2
            while f"{base}{suffix}" in self.clients:
                suffix += 1
            return f"{base}{suffix}"

    def handle_command(self, session: ClientSession, line: str) -> bool:
        command, _, rest = line.partition(" ")
        command = command.lower()
        if command == "/quit":
            self.safe_send(session, "[server] Goodbye.")
            return True
        if command == "/help":
            self.safe_send(session, HELP_TEXT)
        elif command == "/list":
            self.send_user_list(session)
        elif command == "/dm":
            self.send_dm(session, rest)
        elif command == "/rename":
            self.rename(session, rest)
        elif command == "/history":
            self.send_history(session, rest)
        elif command == "/stats":
            self.send_stats(session)
        else:
            self.safe_send(session, "[server] Unknown command. Type /help.")
        return False

    def post_public_message(self, session: ClientSession, message: str) -> None:
        formatted = f"[{timestamp()}] {session.name}: {message}"
        self.history.append(formatted)
        self.total_messages += 1
        logging.info("public %s: %s", session.name, message)
        self.broadcast(formatted)

    def broadcast(self, message: str, exclude: str | None = None) -> None:
        with self.clients_lock:
            sessions = list(self.clients.values())
        for client in sessions:
            if client.name != exclude:
                self.safe_send(client, message)

    def send_user_list(self, session: ClientSession) -> None:
        with self.clients_lock:
            users = sorted(self.clients)
        self.safe_send(session, "[server] Online users: " + ", ".join(users))

    def send_dm(self, session: ClientSession, rest: str) -> None:
        target_name, _, message = rest.strip().partition(" ")
        if not target_name or not message:
            self.safe_send(session, "[server] Usage: /dm <user> <message>")
            return
        with self.clients_lock:
            target = self.clients.get(target_name)
        if target is None:
            self.safe_send(session, f"[server] User not found: {target_name}")
            return
        formatted = f"[{timestamp()}] [dm] {session.name} -> {target.name}: {message}"
        self.total_messages += 1
        logging.info("dm %s -> %s: %s", session.name, target.name, message)
        self.safe_send(target, formatted)
        self.safe_send(session, formatted)

    def rename(self, session: ClientSession, requested_name: str) -> None:
        new_name = sanitize_name(requested_name)
        if new_name == session.name:
            self.safe_send(session, f"[server] You are already named {new_name}.")
            return
        with self.clients_lock:
            if new_name in self.clients:
                self.safe_send(session, f"[server] Name already in use: {new_name}")
                return
            old_name = session.name
            del self.clients[old_name]
            session.name = new_name
            self.clients[new_name] = session
        logging.info("%s renamed to %s", old_name, new_name)
        self.safe_send(session, f"[server] You are now known as {new_name}.")
        self.broadcast(f"[{timestamp()}] [server] {old_name} is now {new_name}.", exclude=new_name)

    def send_history(self, session: ClientSession, rest: str) -> None:
        try:
            count = int(rest.strip()) if rest.strip() else 20
        except ValueError:
            self.safe_send(session, "[server] Usage: /history [count]")
            return
        count = max(1, min(count, len(self.history)))
        if not self.history:
            self.safe_send(session, "[server] No public messages yet.")
            return
        lines = list(self.history)[-count:]
        self.safe_send(session, "[server] Recent history:\n" + "\n".join(lines))

    def send_stats(self, session: ClientSession) -> None:
        uptime = int(time.time() - self.started_at)
        with self.clients_lock:
            active = len(self.clients)
        stats = (
            "[server] Stats: "
            f"active={active}, total_connections={self.total_connections}, "
            f"messages={self.total_messages}, uptime_seconds={uptime}"
        )
        self.safe_send(session, stats)

    def disconnect(self, session: ClientSession) -> None:
        removed = False
        with self.clients_lock:
            if self.clients.get(session.name) is session:
                del self.clients[session.name]
                removed = True
        try:
            session.conn.close()
        except OSError:
            pass
        if removed and not self.shutdown_event.is_set():
            logging.info("%s disconnected", session.name)
            self.broadcast(f"[{timestamp()}] [server] {session.name} left the chat.")

    def safe_send(self, session: ClientSession, message: str) -> None:
        try:
            session.send(message)
        except OSError:
            logging.info("Failed to send to %s", session.name)


def configure_logging(log_file: str) -> None:
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-threaded TCP chat server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/IP to bind.")
    parser.add_argument("--port", type=int, default=5000, help="TCP port to bind.")
    parser.add_argument("--history-size", type=int, default=100, help="Number of public messages to retain.")
    parser.add_argument("--rate-limit", type=int, default=8, help="Messages allowed per rate window.")
    parser.add_argument("--rate-window", type=float, default=5.0, help="Rate window in seconds.")
    parser.add_argument("--log-file", default="chat_server.log", help="Log file path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_file)
    server = ChatServer(
        host=args.host,
        port=args.port,
        history_size=args.history_size,
        rate_limit=args.rate_limit,
        rate_window=args.rate_window,
    )

    def stop(_signum: int, _frame: object) -> None:
        print("\nShutting down chat server...")
        server.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0
