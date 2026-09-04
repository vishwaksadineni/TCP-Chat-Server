import argparse
import sys


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the TCP chat server or client.")
    parser.add_argument("command", choices=["server", "client"], help="Program to run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    args = parse_args(arguments[:1])
    forwarded_args = arguments[1:]
    if args.command == "server":
        from .server import main as server_main

        return server_main(forwarded_args)

    from .client import main as client_main

    return client_main(forwarded_args)
