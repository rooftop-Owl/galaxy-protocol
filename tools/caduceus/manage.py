#!/usr/bin/env python3
"""CLI management tool for user accounts and Telegram linking.

Provides commands to:
- Add users with bcrypt-hashed passwords
- Link Telegram IDs to user accounts
- List all users with their Telegram linkage status
- Remove users by username
"""

import argparse
import getpass
import sys
from pathlib import Path

# Ensure caduceus package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from caduceus.auth.store import UserStore


def add_user(args, store: UserStore) -> int:
    """Add a new user with optional password prompt."""
    username = args.username

    # Prompt for password if not provided
    if args.password:
        password = args.password
    else:
        password = getpass.getpass(f"Password for {username}: ")
        if not password:
            print("Error: Password cannot be empty", file=sys.stderr)
            return 1

    # Create user
    user = store.create_user(username, password)
    if user is None:
        # Check if validation failed vs duplicate
        if len(username) < 3 or len(username) > 32:
            print(f"Error: Username must be 3-32 characters", file=sys.stderr)
        elif len(password) < 6:
            print(f"Error: Password must be at least 6 characters", file=sys.stderr)
        else:
            print(f"Error: Username '{username}' already exists or validation failed", file=sys.stderr)
        return 1

    print(f"✓ User created: {user.id} ({username})")
    return 0


def link_telegram(args, store: UserStore) -> int:
    """Link a Telegram ID to an existing user."""
    username = args.username
    telegram_id = args.telegram_id

    # Look up user
    user = store.get_by_username(username)
    if user is None:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        return 1

    # Link Telegram ID
    success = store.link_telegram(user.id, telegram_id)
    if not success:
        print(
            f"Error: Telegram ID {telegram_id} is already linked to another account",
            file=sys.stderr,
        )
        return 1

    print(f"✓ Linked {username} ({user.id}) to Telegram {telegram_id}")
    return 0


def list_users(args, store: UserStore) -> int:
    """List all users with their Telegram linkage status."""
    users = store.list_users()

    if not users:
        print("No users found")
        return 0

    # Print header
    print(f"{'ID':<10} {'Username':<20} {'Telegram':<15}")
    print("-" * 45)

    # Print each user
    for user in users:
        telegram_str = str(user.telegram_id) if user.telegram_id else "None"
        print(f"{user.id:<10} {user.username:<20} {telegram_str:<15}")

    return 0


def remove_user(args, store: UserStore) -> int:
    """Remove a user by username."""
    username = args.username

    # Look up user
    user = store.get_by_username(username)
    if user is None:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        return 1

    # Delete user
    success = store.delete_user(user.id)
    if not success:
        print(f"Error: Failed to delete user '{username}'", file=sys.stderr)
        return 1

    print(f"✓ Removed user {user.id} ({username})")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage Galaxy Protocol user accounts and Telegram linking"
    )
    parser.add_argument(
        "--db-path",
        default=".galaxy/users.db",
        help="Path to SQLite database (default: .galaxy/users.db)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # add-user command
    add_parser = subparsers.add_parser("add-user", help="Add a new user")
    add_parser.add_argument("--username", required=True, help="Username")
    add_parser.add_argument("--password", help="Password (prompted if omitted)")

    # link-telegram command
    link_parser = subparsers.add_parser(
        "link-telegram", help="Link Telegram ID to user"
    )
    link_parser.add_argument("--username", required=True, help="Username")
    link_parser.add_argument(
        "--telegram-id", type=int, required=True, help="Telegram user ID"
    )

    # list-users command
    subparsers.add_parser("list-users", help="List all users")

    # remove-user command
    remove_parser = subparsers.add_parser("remove-user", help="Remove a user")
    remove_parser.add_argument("--username", required=True, help="Username")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Initialize store
    store = UserStore(db_path=args.db_path)

    try:
        # Dispatch to command handler
        if args.command == "add-user":
            return add_user(args, store)
        elif args.command == "link-telegram":
            return link_telegram(args, store)
        elif args.command == "list-users":
            return list_users(args, store)
        elif args.command == "remove-user":
            return remove_user(args, store)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
