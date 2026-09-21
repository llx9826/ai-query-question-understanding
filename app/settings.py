from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded once by ``app.main``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIQ_",
        extra="ignore",
    )

    demo_mode: bool = True
    http_host: str = "0.0.0.0"
    http_port: int = Field(default=8000, ge=1, le=65535)
    http_workers: int = Field(default=1, ge=1, le=8)
    api_token: SecretStr = SecretStr("demo-local-key")
    api_users_path: Path | None = None
    control_database: Path = Path("runtime/control.duckdb")
    session_workspace: Path = Path("runtime/session-workspaces")
    workspace_id: str = "conference-2026"
    dataset_root: Path = Path("runtime/datasets")
    dataset_max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1,
        le=500 * 1024 * 1024,
    )
    wren_http_base_url: str = "http://wren-http:8001"
    wren_http_admin_token: SecretStr | None = None
    wren_workspace_token: SecretStr | None = None
    wren_http_timeout_seconds: float = Field(default=90, gt=0, le=180)
    checkpoint_timeout_seconds: float = Field(default=3, gt=0, le=10)
