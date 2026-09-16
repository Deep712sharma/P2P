"""Runtime configuration for PaperToPpt.

Configuration is intentionally environment-based so the same image can run
locally, in CI, and on Hugging Face Spaces without source edits.
"""

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def _positive_int(name: str, default: int) -> int:
    """Read a positive integer environment variable with a useful error."""
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer; got {value!r}.") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer; got {value!r}.")
    return parsed


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_size_mb: int
    cors_origins: list[str]
    frontend_dist_dir: Path

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_DIR / "data"))).resolve()
    origins = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    return Settings(
        data_dir=data_dir,
        max_upload_size_mb=_positive_int("MAX_UPLOAD_SIZE_MB", 50),
        cors_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
        frontend_dist_dir=PROJECT_DIR / "frontend" / "dist",
    )


settings = load_settings()
