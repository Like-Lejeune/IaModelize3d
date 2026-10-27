from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent


def _default_orca() -> str:
    for candidate in (
        shutil.which("orca-slicer"),
        r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
        "/opt/orca/orca-slicer",
        "/usr/bin/orca-slicer",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return ""


class Settings(BaseSettings):
    # The key may live in the repo .env or one level up (kept outside the repo).
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR.parent / ".env", REPO_DIR / ".env"),
        env_prefix="FW_",
        extra="ignore",
    )

    meta_api_key: str = Field(default="", validation_alias=AliasChoices("META_API_KEY", "META_KEY", "FW_META_API_KEY"))
    meta_base_url: str = "https://api.meta.ai/v1"

    data_dir: Path = REPO_DIR / "data"
    public_url: str = "http://localhost:5173"

    # model routing
    model_designer: str = "muse-spark-1.3"
    model_designer_hard: str = "muse-wonder-1.0"
    model_fast: str = "muse-spark-1.3"
    model_free: str = "muse-spark-1.3-contributor"
    model_audio: str = "muse-spark-1.2"
    model_sam: str = "sam-3.1"
    model_image: str = "muse-image-1.0"
    model_voice: str = "muse-voice-transcribe-1.0"
    # optional open-weights endpoint (OpenAI-compatible: vLLM/SGLang on Modal or Baseten)
    open_base_url: str = ""
    open_api_key: str = ""
    open_model: str = ""
    # route the independent critic to another model, e.g. the open-weights one
    model_critic: str = ""

    # budgets (USD)
    job_budget_usd: float = 0.60
    daily_budget_usd: float = 25.0
    max_iterations: int = 8

    node_bin: str = Field(default_factory=lambda: shutil.which("node") or "node")
    geom_workers: int = 2
    orca_bin: str = Field(default_factory=_default_orca)
    orca_profiles: Path = Path(r"C:\Program Files\OrcaSlicer\resources\profiles")

    axo_api_url: str = ""
    axo_api_key: str = ""
    telegram_token: str = ""

    @property
    def geom_dir(self) -> Path:
        return REPO_DIR / "packages" / "geom"

    @property
    def standards_path(self) -> Path:
        return self.geom_dir / "src" / "standards.json"


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "files").mkdir(exist_ok=True)
    return s
