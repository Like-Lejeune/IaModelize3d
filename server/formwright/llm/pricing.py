"""Meta Model API prices (USD), from the public pricing page."""
from __future__ import annotations

from ..config import settings

# per 1M tokens: input, cached input, output
TOKEN_PRICES: dict[str, tuple[float, float, float]] = {
    "muse-wonder-1.0": (4.00, 0.20, 20.00),
    "muse-spark-1.3": (1.25, 0.15, 4.25),
    "muse-spark-1.2": (1.25, 0.15, 4.25),
    "muse-spark-1.1": (1.25, 0.15, 4.25),
    "muse-spark-1.3-contributor": (0.10, 0.002, 0.20),
    "muse-spark-1.2-contributor": (0.10, 0.002, 0.20),
}
WEB_SEARCH_PER_CALL = 2.50 / 1000
SAM_PER_IMAGE = 2.50 / 1000
SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50
IMAGE_PER_IMAGE = 0.01
VOICE_PER_SECOND = 0.18 / 3600


def open_prices() -> tuple[float, float, float] | None:
    """The open-weights endpoint's row (settings.open_price_*_per_m): a hosted provider such as Baseten bills tokens,
    a self-hosted GPU bills time (both prices 0)."""
    s = settings()
    if not s.open_model:
        return None
    p_in = float(getattr(s, "open_price_in_per_m", 0.0) or 0.0)
    return p_in, p_in, float(getattr(s, "open_price_out_per_m", 0.0) or 0.0)


def token_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    row = TOKEN_PRICES.get(model) or (open_prices() if model == settings().open_model else None)
    if row is None:
        return 0.0
    p_in, p_cached, p_out = row
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1_000_000
