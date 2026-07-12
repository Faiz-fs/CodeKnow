"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_env: str = "development"
    app_port: int = 8080
    app_cors_origins: str = "http://localhost:5173"

    # --- Database (local Postgres for now; swap URL for Supabase later) ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/codeknow_db"

    # --- GitHub OAuth ---
    # Create an OAuth app at https://github.com/settings/developers
    # Authorization callback URL: http://localhost:8000/auth/github/callback
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8080/codeknow/auth/github/callback"

    # --- Frontend redirect after OAuth (optional) ---
    # If set, callback redirects here with ?token=<jwt>. If unset, returns JSON.
    frontend_redirect: str = ""

    # --- Security ---
    jwt_secret: str = "dev-insecure-secret-change-me"
    # Fernet key for encrypting stored GitHub tokens. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # --- Analysis tuning ---
    max_commits_to_analyze: int = 500
    github_concurrent_requests: int = 10

    # --- Decay detection thresholds ---
    decay_warning_days: int = 60
    decay_critical_days: int = 90
    decay_warning_commits: int = 1
    decay_critical_commits: int = 3
    decay_critical_change_pct: float = 30.0

    # --- Repo listing (GET /repos) ---
    max_repos_to_fetch: int = 200  # caps total repos pulled from GitHub's /user/repos

    # --- Knowledge Graph (Engine 2) ---
    max_files_to_parse: int = 300      # cap on files parsed per repo
    graph_fetch_concurrency: int = 15  # concurrent file content fetches

    # --- Correlation Layer (Engine 3) ---
    co_change_min_weight: float = 0.1
    co_change_max_commits: int = 500
    ppr_damping_factor: float = 0.85
    edge_type_weight_multiplier: dict[str, float] = {"imports": 1.0, "calls": 1.0, "inherits": 1.0, "co_changes_with": 1.0}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
