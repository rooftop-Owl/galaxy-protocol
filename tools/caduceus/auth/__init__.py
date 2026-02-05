"""
Caduceus Auth — User authentication and session management.

Provides SQLite-backed user storage with bcrypt password hashing
and Telegram account linking.

Usage:
    from caduceus.auth.store import UserStore

    store = UserStore(db_path=".galaxy/users.db")
    user = store.create_user("owl", "password123")
    store.verify_password("owl", "password123")  # True
"""

from .store import UserStore, User

__all__ = ["UserStore", "User"]
