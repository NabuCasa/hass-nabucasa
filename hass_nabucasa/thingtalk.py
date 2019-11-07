"""ThingTalk helpers."""
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from . import Cloud


class ThingTalkConversionError(Exception):
    """Conversion error occurred."""


async def async_convert(cloud: "Cloud", query: str):
    """Convert sentence."""
    resp = await cloud.client.websession.post(
        f"{cloud.thingtalk_url}/convert", json={"query": query}
    )
    if resp.status == 200:
        return await resp.json()

    try:
        body = await resp.json()
    except ValueError:
        # Invalid JSON in body
        resp.raise_for_status()

    if not isinstance(body, dict) or "error" not in body:
        resp.raise_for_status()

    raise ThingTalkConversionError(body["error"])
