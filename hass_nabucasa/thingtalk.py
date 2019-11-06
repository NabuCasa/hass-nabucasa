"""ThingTalk helpers."""
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from . import Cloud


async def async_convert(cloud: "Cloud", query: str):
    """Convert sentence."""
    resp = await cloud.client.websession.post(
        f"{cloud.thingtalk_url}/convert", json={"query": query}
    )
    resp.raise_for_status()
    return await resp.json()
