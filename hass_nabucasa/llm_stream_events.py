"""Runtime stream event models for Cloud LLM Responses API.

These classes model only the subset of stream events Home Assistant Cloud
currently consumes. They enable `isinstance(...)` checks in Home Assistant while
keeping the transport (SSE JSON) parsing centralized in `hass_nabucasa`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ResponsesAPIStreamEventType(StrEnum):
    """Responses API stream event types used by Home Assistant."""

    OUTPUT_ITEM_ADDED = "response.output_item.added"
    OUTPUT_ITEM_DONE = "response.output_item.done"
    OUTPUT_TEXT_DELTA = "response.output_text.delta"
    REASONING_SUMMARY_TEXT_DELTA = "response.reasoning_summary_text.delta"
    FUNCTION_CALL_ARGUMENTS_DELTA = "response.function_call_arguments.delta"
    FUNCTION_CALL_ARGUMENTS_DONE = "response.function_call_arguments.done"
    WEB_SEARCH_CALL_SEARCHING = "response.web_search_call.searching"
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_INCOMPLETE = "response.incomplete"
    RESPONSE_FAILED = "response.failed"
    ERROR = "error"


class ResponseOutputItemType(StrEnum):
    """Response output item types used by Home Assistant."""

    FUNCTION_CALL = "function_call"
    MESSAGE = "message"
    REASONING = "reasoning"
    WEB_SEARCH_CALL = "web_search_call"
    IMAGE = "image"


@dataclass(slots=True, frozen=True)
class ResponseUnknownOutputItem:
    """Fallback for output items Home Assistant does not model."""

    type: str
    id: str
    raw: dict[str, Any]


@dataclass(slots=True)
class ResponseFunctionCallOutputItem:
    """Function call output item."""

    type: ResponseOutputItemType
    id: str
    call_id: str
    name: str
    arguments: str = ""
    status: str | None = None


@dataclass(slots=True, frozen=True)
class ResponseMessageOutputItem:
    """Message output item."""

    type: ResponseOutputItemType
    id: str


@dataclass(slots=True, frozen=True)
class ResponseReasoningOutputItem:
    """Reasoning output item."""

    type: ResponseOutputItemType
    id: str
    encrypted_content: str | None = None
    summary: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ResponseWebSearchCallOutputItem:
    """Web search call output item."""

    type: ResponseOutputItemType
    id: str
    action: dict[str, Any]
    status: str | None = None


@dataclass(slots=True, frozen=True)
class ResponseImageOutputItem:
    """Image output item."""

    type: ResponseOutputItemType
    id: str
    raw: dict[str, Any]


type ResponseOutputItem = (
    ResponseFunctionCallOutputItem
    | ResponseMessageOutputItem
    | ResponseReasoningOutputItem
    | ResponseWebSearchCallOutputItem
    | ResponseImageOutputItem
    | ResponseUnknownOutputItem
)


@dataclass(slots=True, frozen=True)
class ResponseOutputItemAddedEvent:
    """Event emitted when an output item is added to the response."""

    type: ResponsesAPIStreamEventType
    item: ResponseOutputItem


@dataclass(slots=True, frozen=True)
class ResponseOutputItemDoneEvent:
    """Event emitted when an output item is marked done."""

    type: ResponsesAPIStreamEventType
    item: ResponseOutputItem


@dataclass(slots=True, frozen=True)
class ResponseOutputTextDeltaEvent:
    """Event carrying a delta chunk of assistant output text."""

    type: ResponsesAPIStreamEventType
    delta: str


@dataclass(slots=True, frozen=True)
class ResponseReasoningSummaryTextDeltaEvent:
    """Event carrying a delta chunk of reasoning summary text."""

    type: ResponsesAPIStreamEventType
    delta: str
    summary_index: int


@dataclass(slots=True, frozen=True)
class ResponseFunctionCallArgumentsDeltaEvent:
    """Event carrying a delta chunk of function call arguments."""

    type: ResponsesAPIStreamEventType
    delta: str


@dataclass(slots=True, frozen=True)
class ResponseFunctionCallArgumentsDoneEvent:
    """Event emitted when function call arguments are complete."""

    type: ResponsesAPIStreamEventType
    arguments: str
    name: str | None
    item_id: str


@dataclass(slots=True, frozen=True)
class ResponseWebSearchCallSearchingEvent:
    """Event emitted when a web search call starts searching."""

    type: ResponsesAPIStreamEventType
    item_id: str


@dataclass(slots=True, frozen=True)
class ResponseCompletedEvent:
    """Event emitted when the overall response is completed."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ResponseIncompleteEvent:
    """Event emitted when the response is incomplete."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ResponseFailedEvent:
    """Event emitted when the response has failed."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ResponseErrorEvent:
    """Error event emitted by the streaming API."""

    type: ResponsesAPIStreamEventType
    message: str


@dataclass(slots=True, frozen=True)
class ResponseUnhandledEvent:
    """Fallback for stream events Home Assistant does not model."""

    type: str
    raw: dict[str, Any]


type ResponsesAPIStreamEvent = (
    ResponseOutputItemAddedEvent
    | ResponseOutputItemDoneEvent
    | ResponseOutputTextDeltaEvent
    | ResponseReasoningSummaryTextDeltaEvent
    | ResponseFunctionCallArgumentsDeltaEvent
    | ResponseFunctionCallArgumentsDoneEvent
    | ResponseWebSearchCallSearchingEvent
    | ResponseCompletedEvent
    | ResponseIncompleteEvent
    | ResponseFailedEvent
    | ResponseErrorEvent
    | ResponseUnhandledEvent
)


def parse_response_stream_event(payload: dict[str, Any]) -> ResponsesAPIStreamEvent:  # noqa: C901, PLR0911, PLR0915
    """Parse a SSE JSON payload into a typed stream event.

    Raises TypeError if the payload does not match a supported event type/shape.
    """
    def _parse_output_item(item: dict[str, Any]) -> ResponseOutputItem:
        item_type = item.get("type")
        item_id = item.get("id")
        if not isinstance(item_type, str):
            raise TypeError("Missing or invalid output item 'type'")
        # Some upstream item types may not include an `id` in early/partial events.
        # If we can't validate a usable ID, preserve the raw item and let the
        # consumer ignore it.
        if not isinstance(item_id, str):
            return ResponseUnknownOutputItem(type=item_type, id="", raw=item)

        match item_type:
            case ResponseOutputItemType.FUNCTION_CALL:
                call_id = item.get("call_id")
                name = item.get("name")
                if not isinstance(call_id, str):
                    raise TypeError(
                        "Missing or invalid function call 'call_id'")
                if not isinstance(name, str):
                    raise TypeError("Missing or invalid function call 'name'")
                arguments = item.get("arguments", "")
                if not isinstance(arguments, str):
                    raise TypeError("Invalid function call 'arguments'")
                status = item.get("status")
                if status is not None and not isinstance(status, str):
                    raise TypeError("Invalid function call 'status'")
                return ResponseFunctionCallOutputItem(
                    type=ResponseOutputItemType.FUNCTION_CALL,
                    id=item_id,
                    call_id=call_id,
                    name=name,
                    arguments=arguments,
                    status=status,
                )
            case ResponseOutputItemType.MESSAGE:
                return ResponseMessageOutputItem(
                    type=ResponseOutputItemType.MESSAGE,
                    id=item_id,
                )
            case ResponseOutputItemType.REASONING:
                encrypted_content = item.get("encrypted_content")
                if encrypted_content is not None and not isinstance(
                    encrypted_content, str
                ):
                    raise TypeError("Invalid reasoning 'encrypted_content'")
                summary = item.get("summary", []) or []
                if not isinstance(summary, list):
                    raise TypeError("Invalid reasoning 'summary'")
                return ResponseReasoningOutputItem(
                    type=ResponseOutputItemType.REASONING,
                    id=item_id,
                    encrypted_content=encrypted_content,
                    summary=summary,
                )
            case ResponseOutputItemType.WEB_SEARCH_CALL:
                action = item.get("action", {})
                if not isinstance(action, dict):
                    raise TypeError("Invalid web search call 'action'")
                status = item.get("status")
                if status is not None and not isinstance(status, str):
                    raise TypeError("Invalid web search call 'status'")
                return ResponseWebSearchCallOutputItem(
                    type=ResponseOutputItemType.WEB_SEARCH_CALL,
                    id=item_id,
                    action=action,
                    status=status,
                )
            case ResponseOutputItemType.IMAGE:
                return ResponseImageOutputItem(
                    type=ResponseOutputItemType.IMAGE,
                    id=item_id,
                    raw=item,
                )
            case _:
                # Preserve unknown item types so consumers can ignore them.
                return ResponseUnknownOutputItem(type=item_type, id=item_id, raw=item)

    match payload.get("type"):
        case ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED:
            item = payload.get("item")
            if not isinstance(item, dict):
                raise TypeError("Missing or invalid 'item'")
            return ResponseOutputItemAddedEvent(
                type=ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED,
                item=_parse_output_item(item),
            )
        case ResponsesAPIStreamEventType.OUTPUT_ITEM_DONE:
            item = payload.get("item")
            if not isinstance(item, dict):
                raise TypeError("Missing or invalid 'item'")
            return ResponseOutputItemDoneEvent(
                type=ResponsesAPIStreamEventType.OUTPUT_ITEM_DONE,
                item=_parse_output_item(item),
            )
        case ResponsesAPIStreamEventType.OUTPUT_TEXT_DELTA:
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise TypeError("Missing or invalid 'delta'")
            return ResponseOutputTextDeltaEvent(
                type=ResponsesAPIStreamEventType.OUTPUT_TEXT_DELTA, delta=delta
            )
        case ResponsesAPIStreamEventType.REASONING_SUMMARY_TEXT_DELTA:
            delta = payload.get("delta")
            summary_index = payload.get("summary_index")
            if not isinstance(delta, str):
                raise TypeError("Missing or invalid 'delta'")
            if not isinstance(summary_index, int):
                raise TypeError("Missing or invalid 'summary_index'")
            return ResponseReasoningSummaryTextDeltaEvent(
                type=ResponsesAPIStreamEventType.REASONING_SUMMARY_TEXT_DELTA,
                delta=delta,
                summary_index=summary_index,
            )
        case ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DELTA:
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise TypeError("Missing or invalid 'delta'")
            return ResponseFunctionCallArgumentsDeltaEvent(
                type=ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DELTA,
                delta=delta,
            )
        case ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DONE:
            arguments = payload.get("arguments")
            name = payload.get("name")
            item_id = payload.get("item_id")
            if not isinstance(arguments, str):
                raise TypeError("Missing or invalid 'arguments'")
            if name is not None and not isinstance(name, str):
                raise TypeError("Invalid 'name'")
            if not isinstance(item_id, str):
                raise TypeError("Missing or invalid 'item_id'")
            return ResponseFunctionCallArgumentsDoneEvent(
                type=ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DONE,
                arguments=arguments,
                name=name if isinstance(name, str) else None,
                item_id=item_id,
            )
        case ResponsesAPIStreamEventType.WEB_SEARCH_CALL_SEARCHING:
            item_id = payload.get("item_id")
            if not isinstance(item_id, str):
                raise TypeError("Missing or invalid 'item_id'")
            return ResponseWebSearchCallSearchingEvent(
                type=ResponsesAPIStreamEventType.WEB_SEARCH_CALL_SEARCHING,
                item_id=item_id,
            )
        case ResponsesAPIStreamEventType.RESPONSE_COMPLETED:
            response = payload.get("response")
            if not isinstance(response, dict):
                raise TypeError("Missing or invalid 'response'")
            return ResponseCompletedEvent(
                type=ResponsesAPIStreamEventType.RESPONSE_COMPLETED, response=response
            )
        case ResponsesAPIStreamEventType.RESPONSE_INCOMPLETE:
            response = payload.get("response")
            if not isinstance(response, dict):
                raise TypeError("Missing or invalid 'response'")
            return ResponseIncompleteEvent(
                type=ResponsesAPIStreamEventType.RESPONSE_INCOMPLETE, response=response
            )
        case ResponsesAPIStreamEventType.RESPONSE_FAILED:
            response = payload.get("response")
            if not isinstance(response, dict):
                raise TypeError("Missing or invalid 'response'")
            return ResponseFailedEvent(
                type=ResponsesAPIStreamEventType.RESPONSE_FAILED, response=response
            )
        case ResponsesAPIStreamEventType.ERROR:
            message = payload.get("message")
            if not isinstance(message, str):
                raise TypeError("Missing or invalid 'message'")
            return ResponseErrorEvent(
                type=ResponsesAPIStreamEventType.ERROR, message=message
            )
        case _:
            event_type = payload.get("type")
            if not isinstance(event_type, str):
                raise TypeError("Missing or invalid 'type'")
            return ResponseUnhandledEvent(type=event_type, raw=payload)
