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
    printer: str | None = None  # brief.printer: the printer the agent checks this project for (a probe sets it)
    material: str | None = None  # brief.material: what it is meant to print in (a ready example's: PETG for the dishwasher wheel)
    # whether this browser may change the project (send messages, save edits): the rule the write routes' 403 follows;
    # a visitor's studio opens read-only with a Remix offer
    can_edit: bool = False


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
    # picked in the composer; None keeps the old rule (account consent + effort). spark_open: the open-weights model
    # (settings.open_model), when one is configured
    model: Literal["contributor", "spark", "wonder", "spark_open"] | None = None
    # how long the designer thinks on each turn; every Muse model accepts these
    reasoning: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = "medium"
    # the run's answer language ('ru', 'en', ...); set by callers that know it (a shop order's intake).
    # None: the loop detects it from the message (loop.message_language).
    language: str | None = None
    # what the person sees as their own message when `text` is written for the model (a shop order's English brief):
    # the run shows these words and keeps `text` in the message's data.brief, which the reviewer reads. None: `text` is both.
    shown: str | None = None


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
    replace: bool = Field(default=False, description="drop the earlier selections of this role on the photo")
    by: Literal["user", "auto"] | None = None  # who outlined it; set by the server


class SpotRequest(BaseModel):
    hint: str | None = Field(default=None, description="the request text, so the right object is found")
    lang: str = "en"


class ParamsUpdate(BaseModel):
    params: dict[str, Any]
    # the browser already built the model and ran the full checks; the server stores them
    checks: dict[str, Any] | None = None
    client: str | None = None  # echoed in the event so the sender can skip its own update


class ProgramUpdate(BaseModel):
    """A program edited in the studio (mesh documents: operation list, strokes sculpted by hand)."""
    source: str = Field(max_length=2_000_000)
    params: dict[str, Any] = {}
    checks: dict[str, Any] | None = None
    summary: str = Field("edited in the studio", max_length=200)
    client: str | None = None


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
    key: Literal["contributor", "spark", "wonder", "spark_open"]
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
