"""Files under data/files, addressed by paths relative to that directory."""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from .config import settings


def files_dir() -> Path:
    return settings().data_dir / "files"


def save_bytes(project_id: str, subdir: str, name: str, data: bytes) -> str:
    rel = Path(project_id) / subdir / name
    path = files_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel.as_posix()


def abs_path(rel: str) -> Path:
    return files_dir() / rel


def url(rel: str | None) -> str | None:
    return f"/files/{rel}" if rel else None


def data_url(rel: str, max_side: int | None = 1280, fmt: str = "JPEG") -> str:
    """Image file -> data URL for the model, downscaled to keep tokens in check."""
    path = abs_path(rel)
    if max_side is None and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    img = Image.open(path)
    if fmt == "JPEG":
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, fmt, quality=85) if fmt == "JPEG" else img.save(buf, fmt)
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()
