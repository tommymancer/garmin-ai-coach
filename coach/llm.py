"""
Claude API wrapper.

The deterministic work (ACWR, thresholds, verdicts) happens in load_model.py.
Claude's job here is interpretation and phrasing, plus reading meal/screenshot
photos — so responses are short and effort is tunable.
"""

import base64
import logging
import mimetypes
from pathlib import Path

import anthropic

from .config import config

logger = logging.getLogger("coach.llm")

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    return _client


def _image_block(image_path: Path) -> dict:
    media_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def generate(prompt: str, image_path: Path | None = None, max_tokens: int = 1024) -> str | None:
    """
    Ask Claude for a short coaching message. Returns None on failure so the
    caller can fall back to a deterministic message instead of going silent.
    """
    content: list = []
    if image_path is not None:
        content.append(_image_block(image_path))
    content.append({"type": "text", "text": prompt})

    try:
        response = _get_client().messages.create(
            model=config.model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": config.effort},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.RateLimitError:
        logger.error("Claude API rate limited")
        return None
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        logger.error("Claude API connection error: %s", exc)
        return None

    if response.stop_reason == "refusal":
        logger.error("Claude declined the request")
        return None

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return text or None
