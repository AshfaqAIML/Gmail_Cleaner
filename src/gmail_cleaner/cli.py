"""Terminal interface for authenticating and running cleanup commands."""

from __future__ import annotations

import argparse
import json
import sys

from .command_parser import build_parser
from .config import Settings
from .database import Database
from .gmail_client import authenticate
from .service import GmailCleanerService


def _make_service(settings: Settings, database: Database) -> GmailCleanerService:
    return GmailCleanerService(
        settings=settings,
        database=database,
        parser=build_parser(settings.openai_api_key, settings.openai_model),
    )


def _print_senders(database: Database) -> None:
    senders = database.list_senders()
    if not senders:
        print("No saved senders.")
        return
    print("Saved senders:")
    for sender in senders:
        print(f"  {sender['name']:<24} {sender['email']}")


def _print_result(result: dict) -> None:
    if result.get("intent") == "list_senders":
        for sender in result["senders"]:
            print(f"  {sender['name']:<24} {sender['email']}")
        return
    if result.get("intent") == "help":
        print("Supported commands:")
        for command in result["commands"]:
            print(f"  - {command}")
        return
    if result.get("intent") in {"add_sender", "remove_sender"}:
        print(json.dumps(result, indent=2, default=str))
        return

    print(f"\nSearch query: {result['gmail_query']}")
    print(f"Matches: {result['total_matches']}")
    if result["status"] == "no_matches":
        print(result["note"])
        return
    print(f"Preview ID: {result['preview_id']}")
    print(f"Expires at: {result['expires_at']}")
    print("\nMessages selected:")
    for index, message in enumerate(result["messages"], start=1):
        print(f"{index:>3}. {message['subject'][:90]}")
        print(f"     From: {message['sender_name']} <{message['sender_email']}>")
        print(f"     Date: {message['date']}")
    print("\nNo messages have been moved yet.")


def _run_command(service: GmailCleanerService, command: str) -> None:
    result = service.execute_command(command)
    _print_result(result)
    if result.get("status") != "pending_confirmation":
        return
    print("\nThis action moves the listed messages to Gmail Trash. It does not permanently delete them.")
    answer = input("Type TRASH to confirm this exact preview (anything else cancels): ").strip()
    confirmed = answer == "TRASH"
    final_result = service.confirm_preview(result["preview_id"], confirmed)
    print(json.dumps(final_result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gmail-cleaner",
        description="Preview and clean Gmail messages by sender.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.add_parser("auth", help="Connect Gmail using Google OAuth.")
    subparsers.add_parser("senders", help="List your saved sender rules.")
    command_parser = subparsers.add_parser("command", help="Run a natural-language cleanup command.")
    command_parser.add_argument("text", nargs=argparse.REMAINDER, help="Command in natural language")
    args = parser.parse_args()

    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()

    try:
        if args.subcommand == "auth":
            authenticate(settings)
            print("Gmail OAuth connection completed. Token saved locally (and excluded from Git).")
            return
        if args.subcommand == "senders":
            _print_senders(database)
            return
        if args.subcommand == "command":
            command = " ".join(args.text).strip()
            if not command:
                parser.error("Provide a command after 'gmail-cleaner command'.")
            _run_command(_make_service(settings, database), command)
            return

        print("Gmail Cleaner Agent. Type 'help' for examples and 'exit' to quit.")
        service = _make_service(settings, database)
        while True:
            try:
                command = input("\ngmail-cleaner> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break
            if command.casefold() in {"exit", "quit"}:
                print("Goodbye.")
                break
            if not command:
                continue
            try:
                _run_command(service, command)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
