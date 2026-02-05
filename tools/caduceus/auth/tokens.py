"""JWT token creation and verification helpers.

Uses PyJWT with HS256 algorithm for signing.
Tokens carry user_id, username, and expiry timestamp.
"""

from datetime import datetime, timedelta, timezone

import jwt


def create_token(
    user_id: str,
    username: str,
    secret: str,
    expiry_hours: int = 24,
) -> str:
    """Create a signed JWT token for a user.

    Args:
        user_id: Unique identifier for the user.
        username: Display name of the user.
        secret: Secret key used for HS256 signing.
        expiry_hours: Token validity duration in hours (default 24).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str, secret: str) -> dict | None:
    """Verify a JWT token and extract the payload.

    Args:
        token: Encoded JWT string to verify.
        secret: Secret key used for HS256 verification.

    Returns:
        Dict with ``user_id`` and ``username`` on success, or ``None``
        if the token is expired, malformed, or has an invalid signature.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return {
            "user_id": payload["user_id"],
            "username": payload["username"],
        }
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
        return None
