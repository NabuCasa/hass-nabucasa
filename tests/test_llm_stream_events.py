"""Unit tests for hass_nabucasa.llm_stream_events."""

from __future__ import annotations

import pytest

from hass_nabucasa.llm.stream_events import (
    LLMStreamEventParseError,
    ResponseFunctionCallOutputItem,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemType,
    ResponseOutputTextDeltaEvent,
    ResponsesAPIStreamEventType,
    ResponseUnhandledEvent,
    parse_response_stream_event,
)


def test_parse_response_stream_event_output_text_delta() -> None:
    """Parse output text delta events."""
    event = parse_response_stream_event(
        {"type": "response.output_text.delta", "delta": "hello"}
    )
    assert isinstance(event, ResponseOutputTextDeltaEvent)
    assert event.type == ResponsesAPIStreamEventType.OUTPUT_TEXT_DELTA
    assert event.delta == "hello"


def test_parse_response_stream_event_output_item_added_function_call() -> None:
    """Parse output item added events containing function calls."""
    event = parse_response_stream_event(
        {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "id": "item-1",
                "call_id": "call-1",
                "name": "do_thing",
                "arguments": '{"x":1}',
                "status": "in_progress",
            },
        }
    )
    assert isinstance(event, ResponseOutputItemAddedEvent)
    assert event.type == ResponsesAPIStreamEventType.OUTPUT_ITEM_ADDED
    assert isinstance(event.item, ResponseFunctionCallOutputItem)
    assert event.item.type == ResponseOutputItemType.FUNCTION_CALL
    assert event.item.id == "item-1"
    assert event.item.call_id == "call-1"
    assert event.item.name == "do_thing"
    assert event.item.arguments == '{"x":1}'
    assert event.item.status == "in_progress"


def test_parse_response_stream_event_unhandled_type_is_preserved() -> None:
    """Preserve unknown event types as ResponseUnhandledEvent."""
    event = parse_response_stream_event({"type": "response.unknown", "foo": "bar"})
    assert isinstance(event, ResponseUnhandledEvent)
    assert event.type == "response.unknown"
    assert event.raw == {"type": "response.unknown", "foo": "bar"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"delta": "hello"},
        {"type": "response.output_text.delta"},  # missing delta
        {"type": "response.output_text.delta", "delta": 1},  # wrong delta type
        {"type": "response.output_item.added", "item": "nope"},  # wrong item type
    ],
)
def test_parse_response_stream_event_invalid_payload_raises_typeerror(
    payload: dict[str, object],
) -> None:
    """Raise TypeError for invalid payload shapes."""
    with pytest.raises(LLMStreamEventParseError):
        parse_response_stream_event(payload)  # type: ignore[arg-type]
