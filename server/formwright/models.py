"""API contracts shared by the server and the web client."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AssetKind = Literal["photo", "video", "audio", "sketch", "caliper", "concept", "render", "print"]
Role = Literal["target", "reference", "mating", "caliper", "ignore", "context"]


class AssetOut(BaseModel):
    id: str
    kind: str
    url: str
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    meta: dict[str, Any] = {}


class SelectionOut(BaseModel):
    id: str
    asset_id: str
    role: str
    name: str
    mask_url: str | None = None
    data: dict[str, Any] = {}


class ProgramOut(BaseModel):
    version: int
    source: str
    params: dict[str, Any] = {}
    inputs: dict[str, Any] = {}
    summary: str | None = None
    checks: dict[str, Any] | None = None
    author: str = "agent"
    created_at: float


class MessageOut(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    text: str
    data: dict[str, Any] = {}
    created_at: float


class ProjectOut(BaseModel):
    id: str
    title: str
    pack: str | None = None
    status: str
    version: int
    public: bool = False
    cover: str | None = None
    forked_from: str | None = None
    created_at: float
    updated_at: float


class ProjectDetail(ProjectOut):
    assets: list[AssetOut] = []
    selections: list[SelectionOut] = []
    program: ProgramOut | None = None
    messages: list[MessageOut] = []
    last_seq: int = 0
    job: dict[str, Any] | None = None


class EventOut(BaseModel):
    seq: int
    job_id: str | None = None
    type: str
    data: dict[str, Any]
    ts: float


class CreateProject(BaseModel):
    title: str | None = None
    pack: str | None = None


class SendMessage(BaseModel):
    text: str = ""
    asset_ids: list[str] = []
    # auto: agent picks; hard: allow the strongest (costlier) designer model
    effort: Literal["auto", "hard"] = "auto"
    # picked in the composer; None keeps the old rule (account consent + effort)
    model: Literal["contributor", "spark", "wonder"] | None = None
    # how long the designer thinks on each turn; every Muse model accepts these
    reasoning: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = "medium"


class Point(BaseModel):
    x: float
    y: float
    positive: bool = True


class SelectRequest(BaseModel):
    points: list[Point] = []
    box: list[float] | None = Field(default=None, description="[x1, y1, x2, y2] in image pixels")
    text: str | None = Field(default=None, description="concept prompt instead of points/box")
    role: Role = "target"
    name: str | None = None


class ParamsUpdate(BaseModel):
    params: dict[str, Any]


class ExportRequest(BaseModel):
    format: Literal["stl", "3mf"] = "3mf"
    params: dict[str, Any] | None = None


class SliceRequest(BaseModel):
    printer: str | None = None
    material: str = "PLA"
    goals: list[Literal["fast", "strong", "pretty", "quiet", "cheap"]] = []
    params: dict[str, Any] | None = None


class OrderRequest(BaseModel):
    quantity: int = 1
    material: str = "PLA"
    color: str | None = None
    comment: str | None = None


class AnswerRequest(BaseModel):
    answer: str


class ConceptRequest(BaseModel):
    prompt: str
    n: int = 4


class VisualEditRequest(BaseModel):
    instruction: str
    sketch_png: str = Field(description="base64 PNG: the current render with the user's strokes drawn on it")


class BreedRequest(BaseModel):
    parents: list[int] = Field(description="program versions the user liked")
    n: int = 6


class ModelOption(BaseModel):
    key: Literal["contributor", "spark", "wonder"]
    id: str
    available: bool


class Usage(BaseModel):
    user_id: str
    tier: str
    today_usd: float
    limit_usd: float
    jobs_today: int
    contributor_consent: bool
    models: list[ModelOption] = []
