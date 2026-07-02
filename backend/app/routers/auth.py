"""GitHub OAuth login flow.

GET /codeknow/auth/github/login  -> 307 redirect to GitHub authorize URL (signed state)
GET /codeknow/auth/github/callback  -> verify state, exchange code, upsert user, mint JWT
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import GitHubAPIError, AuthError
from app.core.security import (
    create_jwt,
    encrypt_token,
    sign_state,
    verify_state,
)
from app.db import get_db
from app.models.user import User
from app.services import github

router = APIRouter()
settings = get_settings()

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"


@router.get("/github/login")
def github_login():
    """Redirect the browser to GitHub's OAuth consent screen."""
    if not settings.github_client_id:
        raise AuthError("GitHub OAuth client ID not configured")

    state = sign_state()
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "repo",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    authorization_url = f"{GITHUB_AUTH_URL}?{query}"
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/github/callback")
async def github_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    """Handle GitHub's OAuth callback: verify state, exchange code, upsert user,
    mint a JWT, then redirect to the frontend (or return JSON)."""
    # 1. Verify CSRF state (bad/expired -> 400)
    try:
        verify_state(state)
    except ValueError as e:
        raise AuthError(f"OAuth state error: {e}") from e

    if not code:
        raise AuthError("Missing authorization code")

    # 2. Exchange code for a GitHub access token
    try:
        access_token = github.exchange_code_for_token(code)
    except (ValueError, Exception) as e:
        raise GitHubAPIError(f"GitHub token exchange failed: {e}") from e

    # 3. Fetch the GitHub user profile
    try:
        profile = github.fetch_user_profile(access_token)
    except Exception as e:
        raise GitHubAPIError(f"GitHub profile fetch failed: {e}") from e

    github_id = profile.get("id")
    login = profile.get("login")
    email = profile.get("email")
    name = profile.get("name") or login

    # 4. Upsert the user (encrypt the token before storing)
    encrypted_token = encrypt_token(access_token)
    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalars().first()

    if user is None:
        user = User(
            github_id=github_id,
            email=email,
            name=name,
            github_access_token_encrypted=encrypted_token,
        )
        db.add(user)
    else:
        user.email = email
        user.name = name
        user.github_access_token_encrypted = encrypted_token

    await db.commit()
    await db.refresh(user)

    # 5. Mint our own JWT
    token = create_jwt(str(user.id))

    # 6. Deliver: redirect (browser flow) or JSON (API/testing flow)
    if settings.frontend_redirect:
        separator = "&" if "?" in settings.frontend_redirect else "?"
        return RedirectResponse(
            url=f"{settings.frontend_redirect}{separator}token={token}",
            status_code=307,
        )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "github_id": user.github_id,
        },
    }
