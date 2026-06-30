"""JWT authentication dependency for protecting routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_jwt
from app.db import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate a Bearer JWT and return the corresponding user.

    Raises 401 if the header is missing, the token is invalid/expired, or the
    user no longer exists.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = decode_jwt(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
