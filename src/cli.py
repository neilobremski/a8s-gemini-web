"""CLI for a8s-gemini-web: serve a8s wakes, or drive one turn by hand."""
import argparse
import os
import sys

import handler
from store import SessionStore


def _seat(args):
    return args.seat or os.environ.get("A8S_GEMINI_SEAT") or "gemini"


def _node_options(parser):
    parser.add_argument(
        "--browser-seat",
        help="a8s-browser seat holding the signed-in profile; "
        "overrides A8S_GEMINI_BROWSER_SEAT",
    )
    parser.add_argument(
        "--browser-cmd",
        help="path to the a8s-browser launcher; overrides A8S_GEMINI_BROWSER_CMD",
    )
    parser.add_argument(
        "--allow",
        help="comma-separated senders this seat answers; overrides A8S_GEMINI_ALLOW",
    )
    parser.add_argument(
        "--model",
        help="model to pick when a conversation is created; overrides A8S_GEMINI_MODEL",
    )


def _print_reply(recipient, body):
    print(f"--- reply to {recipient} ---")
    print(body)


def _sessions(seat):
    store = SessionStore(seat)
    sessions = store.all()
    if store.warning:
        print(store.warning, file=sys.stderr)
    if not sessions:
        print(f"{seat}: no conversations yet ({store.path})")
        return 0
    for name in sorted(sessions):
        entry = sessions[name]
        print(f"{name}\t{entry.get('url', '')}\t{entry.get('created', '')}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="a8s-gemini-web",
        description="Gemini Web as an a8s seat: a tell in, Gemini's answer back.",
    )
    parser.add_argument("--seat", help="a8s node name (default: $A8S_GEMINI_SEAT or 'gemini')")
    sub = parser.add_subparsers(dest="command")

    parser_handle = sub.add_parser("handle", help="a8s wake entry point")
    parser_handle.add_argument("--from", dest="sender", required=True)
    parser_handle.add_argument("--message", required=True)
    _node_options(parser_handle)

    parser_ask = sub.add_parser(
        "ask", help="run one turn by hand and print the reply instead of telling it"
    )
    parser_ask.add_argument("--from", dest="sender", default="operator")
    parser_ask.add_argument("message")
    _node_options(parser_ask)

    sub.add_parser("sessions", help="list this seat's conversations")

    parser_forget = sub.add_parser(
        "forget", help="drop a correspondent's conversation; the next tell starts a new one"
    )
    parser_forget.add_argument("sender")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    seat = _seat(args)
    if args.command == "sessions":
        return _sessions(seat)
    if args.command == "forget":
        store = SessionStore(seat)
        dropped = store.forget(args.sender)
        print(f"{seat}: {'forgot' if dropped else 'had no conversation for'} {args.sender}")
        return 0

    return handler.handle(
        seat,
        args.sender,
        args.message,
        browser_seat=args.browser_seat,
        browser_cmd=args.browser_cmd,
        allow=args.allow,
        model=args.model,
        send=None if args.command == "handle" else _print_reply,
        # `deliver` is deliberately left alone: a hand-run `ask` prints its own
        # reply, and still hands held replies to their correspondents by `tell`.
    )
