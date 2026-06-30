"""Security helpers: Fernet token encryption, JWT encode/decode, OAuth state signing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7
OAUTH_STATE_MAX_AGE = 600  # 10 minutes


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


# --- GitHub token encryption ---
def encrypt_token(plaintext: str) -> str:
    """Encrypt a GitHub access token for DB storage."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored GitHub access token. Raises ValueError on failure."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Failed to decrypt stored token") from e


# --- JWT ---
def create_jwt(subject: str) -> str:
    """Mint a JWT for the given user id (as string)."""
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def decode_jwt(token: str) -> str:
    """Decode a JWT and return the subject (user id). Raises ValueError on
    invalid/expired/missing-sub."""
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError as e:
        raise ValueError("Invalid or expired token") from e
    sub = payload.get("sub")
    if not sub:
        raise ValueError("Token missing subject")
    return sub


# --- OAuth state (stateless CSRF protection) ---
def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().jwt_secret)


def sign_state() -> str:
    """Produce a signed, timestamped OAuth state value."""
    return _state_serializer().dumps({"oauth": True})


def verify_state(state: str) -> None:
    """Verify a signed OAuth state. Raises ValueError on bad/expired."""
    try:
        _state_serializer().loads(state, max_age=OAUTH_STATE_MAX_AGE)
    except SignatureExpired as e:
        raise ValueError("OAuth state expired") from e
    except BadSignature as e:
        raise ValueError("Invalid OAuth state") from e
