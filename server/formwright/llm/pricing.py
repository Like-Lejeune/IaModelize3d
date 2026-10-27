"""Meta Model API prices (USD), from the public pricing page."""
from __future__ import annotations

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


def token_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    if model not in TOKEN_PRICES:
        return 0.0  # self-hosted open weights: billed by GPU time, not tokens
    p_in, p_cached, p_out = TOKEN_PRICES[model]
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1_000_000
