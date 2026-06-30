"""GitHub OAuth login flow.

Sprint 1 wires the redirect + callback shape. Token exchange and JWT minting
are filled in once the GitHub OAuth app credentials are configured.
"""

from fastapi import APIRouter, HTTPException
from requests_oauthlib import OAuth2Session

from app.config import get_settings

router = APIRouter()
settings = get_settings()

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_code"


@router.get("/auth/github")
def github_login():
    """Redirect the browser to GitHub's OAuth consent screen."""
    if not settings.github_client_id:
        raise HTTPException(500, "GitHub OAuth client ID not configured")
    oauth = OAuth2Session(settings.github_client_id,
                          redirect_uri=settings.github_oauth_redirect_uri,
                          scope=["read:user", "repo"])
    authorization_url, state = oauth.authorization_url(GITHUB_AUTH_URL)
    return {"authorization_url": authorization_url, "state": state}


@router.get("/auth/github/callback")
def github_callback(code: str, state: str):
    """Handle GitHub's callback: exchange code for a token, mint a JWT."""
    # TODO Sprint 1: token exchange + JWT minting + set httponly cookie
    return {"code": code, "state": state, "status": "not-implemented"}
