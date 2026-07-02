"""Shared exception classes with standardized JSON error responses."""

from __future__ import annotations

from fastapi import HTTPException


# --- Base exception class ---

class CodeKnowException(HTTPException):
    """Base exception with an error code for consistent error responses."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


# --- Specific exception classes ---

class RepoNotFoundError(CodeKnowException):
    def __init__(self, message: str):
        super().__init__(status_code=404, code="REPO_NOT_FOUND", message=message)


class GitHubAPIError(CodeKnowException):
    def __init__(self, message: str):
        super().__init__(status_code=502, code="GITHUB_API_ERROR", message=message)


class TokenDecryptionError(CodeKnowException):
    def __init__(self, message: str):
        super().__init__(status_code=500, code="TOKEN_ERROR", message=message)


class InvalidRepoURLError(CodeKnowException):
    def __init__(self, message: str):
        super().__init__(status_code=400, code="INVALID_REPO_URL", message=message)


class AuthError(CodeKnowException):
    def __init__(self, message: str):
        super().__init__(
            status_code=401,
            code="AUTH_ERROR",
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )