from __future__ import annotations

import argparse
import socket
import sys
import threading


def receive_messages(sock: socket.socket, stop_event: threading.Event) -> None:
    buffer = b""
    while not stop_event.is_set():
        try:
            data = sock.recv(4096)
        except OSError:
            break
        if not data:
            print("\nDisconnected from server.")
            stop_event.set()
            break
        buffer += data
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            print(line.decode("utf-8", errors="replace"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TCP chat client.")
    parser.add_argument("--host", default="127.0.0.1", help="Server host/IP.")
    parser.add_argument("--port", type=int, default=5000, help="Server TCP port.")
    parser.add_argument("--name", help="Username to send on connect.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stop_event = threading.Event()

    try:
        with socket.create_connection((args.host, args.port)) as sock:
            prompt = sock.recv(4096).decode("utf-8", errors="replace")
            if prompt:
                print(prompt, end="" if prompt.endswith(" ") else "\n")
            name = args.name or input().strip()
            sock.sendall(f"{name}\n".encode("utf-8"))

            receiver = threading.Thread(target=receive_messages, args=(sock, stop_event), daemon=True)
            receiver.start()

            while not stop_event.is_set():
                try:
                    message = input()
                except (EOFError, KeyboardInterrupt):
                    message = "/quit"
                try:
                    sock.sendall(f"{message}\n".encode("utf-8"))
                except OSError:
                    stop_event.set()
                    break
                if message.strip().lower() == "/quit":
                    stop_event.set()
                    break
    except ConnectionRefusedError:
        print(f"Could not connect to {args.host}:{args.port}. Is the server running?", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return 1
    return 0
