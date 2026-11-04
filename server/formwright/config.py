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
    public_url: str = "http://localhost:5400"
    # reverse proxies in front of the API that append the address they see to X-Forwarded-For: the visitor's address is
    # the entry this many places from the right, so whatever a visitor writes further left never counts. The container
    # sets 1 (one TLS proxy in front, see Containerfile). -1: one when uvicorn trusts every sender (FORWARDED_ALLOW_IPS="*":
    # uvicorn then takes the leftmost entry, which the visitor writes), else none (uvicorn's pick stands)
    proxy_hops: int = -1
    # vite's port when it serves the web app next to the API (dev.ps1 sets it): pages opened here go there
    web_dev_port: int = 0

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
    # roles the open model takes when it is configured (comma-separated); snap naming stays on Muse Spark (latency)
    open_roles: str = "critic,classify,english"
    open_timeout_s: float = 60.0
    # its price per million tokens (0: self-hosted or unknown)
    open_price_in_per_m: float = 0.0
    open_price_out_per_m: float = 0.0
    # route the independent critic to another model, e.g. the open-weights one
    model_critic: str = ""
    # the LLM device reviewer (agent/device_review.py) gating a device's finish: off since 2026-11-03 (it passed broken
    # devices and raised false majors); the designer checks itself against device_checklists instead. FW_DEVICE_REVIEWER=1
    device_reviewer: bool = False

    # budgets (USD)
    daily_budget_usd: float = 25.0
    # what anonymous visitors may spend of it together: the rest stays for people with a sign-in link (judges, Telegram)
    # however many addresses the anonymous traffic comes from
    anon_budget_share: float = 0.75
    max_iterations: int = 8
    # wall-clock deadlines (s): past it a job wraps up, a minute later it is stopped
    design_deadline_s: float = 600
    device_deadline_s: float = 1200  # a whole device: board, case, firmware and its tests; 4 of 13 harder ones ran out at 600 on 2026-11-04
    side_deadline_s: float = 180
    # how long a question waits for an answer; the wait does not count toward the deadline
    ask_timeout_s: float = 180

    # blur faces in uploaded photos before any model sees them
    blur_faces: bool = True

    node_bin: str = Field(default_factory=lambda: shutil.which("node") or "node")
    geom_workers: int = 2
    # PCB pipeline (packages/pcb, its own npm package): the server runs only <pcb_dir>/dist (npm run bundle)
    pcb_dir: Path = REPO_DIR / "packages" / "pcb"
    pcb_pool_size: int = 1
    pcb_timeout: float = 90.0
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
