"""
Security infrastructure hooks for Dev A.

Responsibilities:
  - Input guardrail: run OpenAI Moderation on user messages before they reach the model.
  - Output sanitizer: strip external links and markdown images from content that is about
    to be published to mooKIT (anti-exfil — the model must not be able to beacon external URLs).
  - The sanitizer is deterministic and does NOT call an LLM.

Dev B hooks into `check_input_guardrails` before sending user text to the LLM and into
`sanitize_for_publish` before constructing a ProposedAction payload.
"""

import re
import logging
from openai import AsyncOpenAI

from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input guardrail
# ---------------------------------------------------------------------------

_moderation_client: AsyncOpenAI | None = None


def _get_moderation_client() -> AsyncOpenAI:
    global _moderation_client
    if _moderation_client is None:
        _moderation_client = AsyncOpenAI(api_key=settings.openai.api_key.get_secret_value())
    return _moderation_client


async def check_input_guardrails(text: str) -> None:
    """Call the OpenAI Moderation endpoint; raise ValueError if the input is flagged.

    On any API error we log and allow through (fail-open for guardrails — block on
    hard policy violations, not transient network failures).
    """
    if not text or not text.strip():
        return
    try:
        client = _get_moderation_client()
        response = await client.moderations.create(input=text)
        result = response.results[0]
        if result.flagged:
            flagged_cats = [cat for cat, flagged in result.categories.__dict__.items() if flagged]
            logger.warning("Input flagged by moderation: categories=%s", flagged_cats)
            raise ValueError(f"Content policy violation: {', '.join(flagged_cats)}")
    except ValueError:
        raise
    except Exception as exc:
        logger.error("Moderation API error (allowing through): %s", exc)


# ---------------------------------------------------------------------------
# Output sanitizer — deterministic, no LLM
# ---------------------------------------------------------------------------

# Regex patterns for content that must not appear in published mooKIT content.
# These prevent the model from exfiltrating data via URLs embedded in published content.
_EXTERNAL_LINK_RE = re.compile(
    r'\[([^\]]*)\]\((https?://[^)]+)\)',   # [text](http://...)
    re.IGNORECASE,
)
_BARE_URL_RE = re.compile(
    r'(?<!\()(https?://\S+)',              # bare http(s) URL not inside a markdown link
    re.IGNORECASE,
)
_MARKDOWN_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\([^)]+\)',             # ![alt](src)
    re.IGNORECASE,
)
_HTML_LINK_RE = re.compile(
    r'<a\s[^>]*href=["\']https?://[^"\']*["\'][^>]*>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_IMG_RE = re.compile(
    r'<img\s[^>]*/?>',
    re.IGNORECASE,
)


def sanitize_for_publish(content: str) -> str:
    """Remove all external links and images from markdown/HTML content.

    Applied to any text field that will be published to mooKIT (announcement
    description, lecture description, question text, etc.) to prevent the model
    from inserting exfiltration beacons.

    Internal relative links are preserved; only absolute http(s) URLs are stripped.
    """
    # Replace markdown images with their alt text
    content = _MARKDOWN_IMAGE_RE.sub(r'[\1]', content)
    # Replace external markdown links with just the link text
    content = _EXTERNAL_LINK_RE.sub(r'\1', content)
    # Remove bare external URLs
    content = _BARE_URL_RE.sub('[link removed]', content)
    # Remove HTML anchor tags that wrap external URLs
    content = _HTML_LINK_RE.sub('', content)
    # Remove HTML img tags
    content = _HTML_IMG_RE.sub('', content)
    return content
