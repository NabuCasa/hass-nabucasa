"""Runtime stream event models for Cloud LLM Responses API.

These classes model only a subset of stream events and not the full Responses API
stream events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import LLMStreamEventParseError


class ResponsesAPIStreamEventType(StrEnum):
    """Responses API stream event types used by Home Assistant."""

    ERROR = "error"
    FUNCTION_CALL_ARGUMENTS_DELTA = "response.function_call_arguments.delta"
    FUNCTION_CALL_ARGUMENTS_DONE = "response.function_call_arguments.done"
    OUTPUT_ITEM_ADDED = "response.output_item.added"
    OUTPUT_ITEM_DONE = "response.output_item.done"
    OUTPUT_TEXT_DELTA = "response.output_text.delta"
    REASONING_SUMMARY_TEXT_DELTA = "response.reasoning_summary_text.delta"
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_FAILED = "response.failed"
    RESPONSE_INCOMPLETE = "response.incomplete"
    WEB_SEARCH_CALL_SEARCHING = "response.web_search_call.searching"


class ResponseOutputItemType(StrEnum):
    """Response output item types used by Home Assistant."""

    FUNCTION_CALL = "function_call"
    IMAGE = "image"
    MESSAGE = "message"
    REASONING = "reasoning"
    WEB_SEARCH_CALL = "web_search_call"


@dataclass(slots=True, frozen=True)
class LLMResponseUnknownOutputItem:
    """Fallback for output items Home Assistant does not model."""

    type: str
    id: str
    raw: dict[str, Any]


# The Responses API sends function calls in different events (DELTA and DONE). Not
# freezing this class allows the caller to aggregate the delta and done events into a
# single dataclass.
@dataclass(slots=True)
class LLMResponseFunctionCallOutputItem:
    """Function call output item."""

    type: ResponseOutputItemType
    id: str
    call_id: str
    name: str
    arguments: str = ""
    status: str | None = None


@dataclass(slots=True, frozen=True)
class LLMResponseMessageOutputItem:
    """Message output item."""

    type: ResponseOutputItemType
    id: str


@dataclass(slots=True, frozen=True)
class LLMResponseReasoningOutputItem:
    """Reasoning output item."""

    type: ResponseOutputItemType
    id: str
    encrypted_content: str | None = None
    summary: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class LLMResponseWebSearchCallOutputItem:
    """Web search call output item."""

    type: ResponseOutputItemType
    id: str
    action: dict[str, Any]
    status: str | None = None


@dataclass(slots=True, frozen=True)
class LLMResponseImageOutputItem:
    """Image output item."""

    type: ResponseOutputItemType
    id: str
    raw: dict[str, Any]


type ResponseOutputItem = (
    LLMResponseFunctionCallOutputItem
    | LLMResponseMessageOutputItem
    | LLMResponseReasoningOutputItem
    | LLMResponseWebSearchCallOutputItem
    | LLMResponseImageOutputItem
    | LLMResponseUnknownOutputItem
)


@dataclass(slots=True, frozen=True)
class LLMResponseOutputItemAddedEvent:
    """Event emitted when an output item is added to the response."""

    type: ResponsesAPIStreamEventType
    item: ResponseOutputItem


@dataclass(slots=True, frozen=True)
class LLMResponseOutputItemDoneEvent:
    """Event emitted when an output item is marked done."""

    type: ResponsesAPIStreamEventType
    item: ResponseOutputItem


@dataclass(slots=True, frozen=True)
class LLMResponseOutputTextDeltaEvent:
    """Event carrying a delta chunk of assistant output text."""

    type: ResponsesAPIStreamEventType
    delta: str


@dataclass(slots=True, frozen=True)
class LLMResponseReasoningSummaryTextDeltaEvent:
    """Event carrying a delta chunk of reasoning summary text."""

    type: ResponsesAPIStreamEventType
    delta: str
    summary_index: int


@dataclass(slots=True, frozen=True)
class LLMResponseFunctionCallArgumentsDeltaEvent:
    """Event carrying a delta chunk of function call arguments."""

    type: ResponsesAPIStreamEventType
    delta: str


@dataclass(slots=True, frozen=True)
class LLMResponseFunctionCallArgumentsDoneEvent:
    """Event emitted when function call arguments are complete."""

    type: ResponsesAPIStreamEventType
    arguments: str
    name: str | None
    item_id: str


@dataclass(slots=True, frozen=True)
class LLMResponseWebSearchCallSearchingEvent:
    """Event emitted when a web search call starts searching."""

    type: ResponsesAPIStreamEventType
    item_id: str


@dataclass(slots=True, frozen=True)
class LLMResponseCompletedEvent:
    """Event emitted when the overall response is completed."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class LLMResponseIncompleteEvent:
    """Event emitted when the response is incomplete."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class LLMResponseFailedEvent:
    """Event emitted when the response has failed."""

    type: ResponsesAPIStreamEventType
    response: dict[str, Any]


@dataclass(slots=True, frozen=True)
class LLMResponseErrorEvent:
    """Error event emitted by the streaming API."""

    type: ResponsesAPIStreamEventType
    message: str


@dataclass(slots=True, frozen=True)
class LLMResponseUnhandledEvent:
    """Fallback for stream events Home Assistant does not model."""

    type: str
    raw: dict[str, Any]


# Pylint expects type aliases to use snake_case; we keep this name for API clarity.
type ResponsesAPIStreamEvent = (  # pylint: disable=invalid-name
    LLMResponseOutputItemAddedEvent
    | LLMResponseOutputItemDoneEvent
    | LLMResponseOutputTextDeltaEvent
    | LLMResponseReasoningSummaryTextDeltaEvent
    | LLMResponseFunctionCallArgumentsDeltaEvent
    | LLMResponseFunctionCallArgumentsDoneEvent
    | LLMResponseWebSearchCallSearchingEvent
    | LLMResponseCompletedEvent
    | LLMResponseIncompleteEvent
    | LLMResponseFailedEvent
    | LLMResponseErrorEvent
    | LLMResponseUnhandledEvent
)


def _parse_output_item(item: dict[str, Any]) -> ResponseOutputItem:
    """Parse a response output item dict into a typed output item."""
    item_type = item.get("type")
    item_id = item.get("id")
    if not isinstance(item_type, str):
        raise LLMStreamEventParseError("Missing or invalid output item 'type'")
    if not isinstance(item_id, str):
        return LLMResponseUnknownOutputItem(type=item_type, id="", raw=item)

    match item_type:
        case ResponseOutputItemType.FUNCTION_CALL:
            call_id = item.get("call_id")
            name = item.get("name")
            if not isinstance(call_id, str):
                raise LLMStreamEventParseError(
                    "Missing or invalid function call 'call_id'"
                )
            if not isinstance(name, str):
                raise LLMStreamEventParseError(
                    "Missing or invalid function call 'name'"
                )
            arguments = item.get("arguments", "")
            if not isinstance(arguments, str):
                raise LLMStreamEventParseError("Invalid function call 'arguments'")
            status = item.get("status")
            if status is not None and not isinstance(status, str):
                raise LLMStreamEventParseError("Invalid function call 'status'")
            return LLMResponseFunctionCallOutputItem(
                type=ResponseOutputItemType.FUNCTION_CALL,
                id=item_id,
                call_id=call_id,
                name=name,
                arguments=arguments,
                status=status,
            )
        case ResponseOutputItemType.MESSAGE:
            return LLMResponseMessageOutputItem(
                type=ResponseOutputItemType.MESSAGE,
                id=item_id,
            )
        case ResponseOutputItemType.REASONING:
            encrypted_content = item.get("encrypted_content")
            if encrypted_content is not None and not isinstance(encrypted_content, str):
                raise LLMStreamEventParseError("Invalid reasoning 'encrypted_content'")
            summary = item.get("summary", [])
            if not isinstance(summary, list):
                raise LLMStreamEventParseError("Invalid reasoning 'summary'")
            return LLMResponseReasoningOutputItem(
                type=ResponseOutputItemType.REASONING,
                id=item_id,
                encrypted_content=encrypted_content,
                summary=summary,
            )
        case ResponseOutputItemType.WEB_SEARCH_CALL:
            action = item.get("action", {})
            if not isinstance(action, dict):
                raise LLMStreamEventParseError("Invalid web search call 'action'")
            if (status := item.get("status")) is not None and not isinstance(
                status, str
            ):
                raise LLMStreamEventParseError("Invalid web search call 'status'")
            return LLMResponseWebSearchCallOutputItem(
                type=ResponseOutputItemType.WEB_SEARCH_CALL,
                id=item_id,
                action=action,
                status=status,
            )
        case ResponseOutputItemType.IMAGE:
            return LLMResponseImageOutputItem(
                type=ResponseOutputItemType.IMAGE,
                id=item_id,
                raw=item,
            )
        case _:
            # Preserve unknown item types so consumers can ignore them.
            return LLMResponseUnknownOutputItem(type=item_type, id=item_id, raw=item)


def _parse_item_event(
    payload: dict[str, Any],
    *,
    event_type: ResponsesAPIStreamEventType,
) -> LLMResponseOutputItemAddedEvent | LLMResponseOutputItemDoneEvent:
    item = payload.get("item")
    if not isinstance(item, dict):
        raise LLMStreamEventParseError("Missing or invalid 'item'")
    parsed_item = _parse_output_item(item)

    if event_type is ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED:
        return LLMResponseOutputItemAddedEvent(type=event_type, item=parsed_item)
    return LLMResponseOutputItemDoneEvent(type=event_type, item=parsed_item)


def _parse_delta_event(
    payload: dict[str, Any],
    *,
    event_type: ResponsesAPIStreamEventType,
) -> (
    LLMResponseOutputTextDeltaEvent
    | LLMResponseReasoningSummaryTextDeltaEvent
    | LLMResponseFunctionCallArgumentsDeltaEvent
):
    delta = payload.get("delta")
    if not isinstance(delta, str):
        raise LLMStreamEventParseError("Missing or invalid 'delta'")

    if event_type is ResponsesAPIStreamEventType.OUTPUT_TEXT_DELTA:
        return LLMResponseOutputTextDeltaEvent(type=event_type, delta=delta)

    if event_type is ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DELTA:
        return LLMResponseFunctionCallArgumentsDeltaEvent(type=event_type, delta=delta)

    summary_index = payload.get("summary_index")
    if not isinstance(summary_index, int):
        raise LLMStreamEventParseError("Missing or invalid 'summary_index'")
    return LLMResponseReasoningSummaryTextDeltaEvent(
        type=event_type,
        delta=delta,
        summary_index=summary_index,
    )


def _parse_function_call_arguments_done_event(
    payload: dict[str, Any],
) -> LLMResponseFunctionCallArgumentsDoneEvent:
    arguments = payload.get("arguments")
    name = payload.get("name")
    item_id = payload.get("item_id")
    if not isinstance(arguments, str):
        raise LLMStreamEventParseError("Missing or invalid 'arguments'")
    if name is not None and not isinstance(name, str):
        raise LLMStreamEventParseError("Invalid 'name'")
    if not isinstance(item_id, str):
        raise LLMStreamEventParseError("Missing or invalid 'item_id'")
    return LLMResponseFunctionCallArgumentsDoneEvent(
        type=ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DONE,
        arguments=arguments,
        name=name if isinstance(name, str) else None,
        item_id=item_id,
    )


def _parse_web_search_call_searching_event(
    payload: dict[str, Any],
) -> LLMResponseWebSearchCallSearchingEvent:
    item_id = payload.get("item_id")
    if not isinstance(item_id, str):
        raise LLMStreamEventParseError("Missing or invalid 'item_id'")
    return LLMResponseWebSearchCallSearchingEvent(
        type=ResponsesAPIStreamEventType.WEB_SEARCH_CALL_SEARCHING,
        item_id=item_id,
    )


def _parse_completion_event(
    payload: dict[str, Any],
    *,
    event_type: ResponsesAPIStreamEventType,
) -> LLMResponseCompletedEvent | LLMResponseIncompleteEvent | LLMResponseFailedEvent:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise LLMStreamEventParseError("Missing or invalid 'response'")

    if event_type is ResponsesAPIStreamEventType.RESPONSE_COMPLETED:
        return LLMResponseCompletedEvent(type=event_type, response=response)
    if event_type is ResponsesAPIStreamEventType.RESPONSE_INCOMPLETE:
        return LLMResponseIncompleteEvent(type=event_type, response=response)
    return LLMResponseFailedEvent(type=event_type, response=response)


def _parse_error_event(payload: dict[str, Any]) -> LLMResponseErrorEvent:
    message = payload.get("message")
    if not isinstance(message, str):
        raise LLMStreamEventParseError("Missing or invalid 'message'")
    return LLMResponseErrorEvent(
        type=ResponsesAPIStreamEventType.ERROR,
        message=message,
    )


def parse_response_stream_event(payload: dict[str, Any]) -> ResponsesAPIStreamEvent:
    """Parse a SSE JSON payload into a typed stream event.

    Raises LLMStreamEventParseError if the payload does not match a supported
    event type/shape.
    """
    event_type = payload.get("type")
    if not isinstance(event_type, str):
        raise LLMStreamEventParseError("Missing or invalid 'type'")

    if event_type == ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED.value:
        result: ResponsesAPIStreamEvent = _parse_item_event(
            payload,
            event_type=ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED,
        )
    elif event_type == ResponsesAPIStreamEventType.OUTPUT_ITEM_DONE.value:
        result = _parse_item_event(
            payload,
            event_type=ResponsesAPIStreamEventType.OUTPUT_ITEM_DONE,
        )
    elif event_type in {
        ResponsesAPIStreamEventType.OUTPUT_TEXT_DELTA.value,
        ResponsesAPIStreamEventType.REASONING_SUMMARY_TEXT_DELTA.value,
        ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DELTA.value,
    }:
        try:
            event_enum = ResponsesAPIStreamEventType(event_type)
        except ValueError as err:
            raise LLMStreamEventParseError("Unsupported event 'type'") from err
        result = _parse_delta_event(payload, event_type=event_enum)
    elif event_type == ResponsesAPIStreamEventType.FUNCTION_CALL_ARGUMENTS_DONE.value:
        result = _parse_function_call_arguments_done_event(payload)
    elif event_type == ResponsesAPIStreamEventType.WEB_SEARCH_CALL_SEARCHING.value:
        result = _parse_web_search_call_searching_event(payload)
    elif event_type in {
        ResponsesAPIStreamEventType.RESPONSE_COMPLETED.value,
        ResponsesAPIStreamEventType.RESPONSE_INCOMPLETE.value,
        ResponsesAPIStreamEventType.RESPONSE_FAILED.value,
    }:
        try:
            event_enum = ResponsesAPIStreamEventType(event_type)
        except ValueError as err:
            raise LLMStreamEventParseError("Unsupported event 'type'") from err
        result = _parse_completion_event(payload, event_type=event_enum)
    elif event_type == ResponsesAPIStreamEventType.ERROR.value:
        result = _parse_error_event(payload)
    else:
        result = LLMResponseUnhandledEvent(type=event_type, raw=payload)

    return result
