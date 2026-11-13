from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

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


# The AI providers the server can talk to. Every one of them speaks the OpenAI Responses API (text, vision, tools,
# structured output), which is what the designer, the intake desk and the critic use. What only Meta's API offers:
# SAM 3.1 (measuring a part on its A4 sheet, face blur, QC photos), Voice Transcribe and Muse Image. On another
# provider those features are switched off: the designer works from the photos as an image model sees them and asks the
# customer for the dimensions it cannot read, voice notes are refused, uploads are kept without a face pass.
PROVIDERS: dict[str, dict[str, Any]] = {
    "meta": {"base_url": "https://api.meta.ai/v1", "sam": True, "voice": True, "image": True},
    "openai": {"base_url": "https://api.openai.com/v1", "sam": False, "voice": False, "image": False},
    # any other endpoint that serves /v1/responses (a gateway, vLLM, a self-hosted model): FW_LLM_BASE_URL is required
    "custom": {"base_url": "", "sam": False, "voice": False, "image": False},
}


class Settings(BaseSettings):
    # The key may live in the repo .env or one level up (kept outside the repo).
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR.parent / ".env", REPO_DIR / ".env"),
        env_prefix="FW_",
        extra="ignore",
    )

    # which provider serves the models (PROVIDERS above); FW_LLM_BASE_URL / FW_LLM_API_KEY override its address and key
    llm_provider: str = "meta"
    llm_base_url: str = ""
    llm_api_key: str = ""
    # prices per million tokens for models the built-in table (llm/pricing.py) does not know, so budgets still count
    llm_price_in_per_m: float = 0.0
    llm_price_cached_per_m: float = 0.0
    llm_price_out_per_m: float = 0.0

    meta_api_key: str = Field(default="", validation_alias=AliasChoices("META_API_KEY", "META_KEY", "FW_META_API_KEY"))
    meta_base_url: str = "https://api.meta.ai/v1"

    @property
    def provider(self) -> dict[str, Any]:
        """The provider's preset: its default address and what it offers beyond the Responses API."""
        name = (self.llm_provider or "meta").strip().lower()
        if name not in PROVIDERS:
            raise ValueError(f"FW_LLM_PROVIDER={self.llm_provider!r}: expected one of {', '.join(PROVIDERS)}")
        return {"name": name, **PROVIDERS[name]}

    @property
    def api_base_url(self) -> str:
        """Where the models are called: FW_LLM_BASE_URL, else the Meta address (FW_META_BASE_URL) on Meta, else the preset's."""
        p = self.provider
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        return self.meta_base_url if p["name"] == "meta" else p["base_url"]

    @property
    def api_key(self) -> str:
        """The provider's key: FW_LLM_API_KEY, else META_API_KEY on Meta (the original setting keeps working)."""
        return self.llm_api_key or (self.meta_api_key if self.provider["name"] == "meta" else "")

    def can(self, feature: str) -> bool:
        """Whether this server can use a provider-specific feature ('sam', 'voice', 'image'): the provider offers it
        and a key is set."""
        return bool(self.api_key) and bool(self.provider.get(feature))

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
    model_designer: str = "muse-spark-1.3-contributor"
    model_designer_hard: str = "muse-wonder-1.0"
    model_fast: str = "muse-spark-1.3-contributor"
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
    p = s.provider  # an unknown FW_LLM_PROVIDER stops the server here, not at the first model call
    if p["name"] == "custom" and not s.llm_base_url:
        raise ValueError("FW_LLM_PROVIDER=custom needs FW_LLM_BASE_URL (an endpoint that serves /v1/responses)")
    if p["name"] != "meta":
        meta_models = [k for k in ("model_designer", "model_designer_hard", "model_fast", "model_free")
                       if str(getattr(s, k)).startswith("muse-")]
        if meta_models:
            logging.getLogger(__name__).warning(
                "FW_LLM_PROVIDER=%s but %s still name Meta models: set FW_MODEL_DESIGNER, FW_MODEL_DESIGNER_HARD, FW_MODEL_FAST "
                "and FW_MODEL_FREE to this provider's models", p["name"], ", ".join(m.upper() for m in meta_models))
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "files").mkdir(exist_ok=True)
    return s
