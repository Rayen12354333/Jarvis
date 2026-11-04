"""GroqCloud provider tests with a local HTTP transport."""
from __future__ import annotations

import json

import httpx
from pydantic import BaseModel

from jarvis.groq import GroqProvider, _strict_json_schema


class OptionalTurn(BaseModel):
    speech: str
    query: str | None = None


def test_strict_schema_requires_nullable_fields_and_blocks_extra_properties() -> None:
    schema = _strict_json_schema(OptionalTurn)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["speech", "query"]
    assert "default" not in schema["properties"]["query"]


def test_structured_fallback_keeps_its_own_conversation_history() -> None:
    requests: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        number = len(requests)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                f'{{"speech":"answer {number}",'
                                '"action":"continue"}'
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = GroqProvider(model="test-model", client=client)

    first = provider.fallback("first")
    second = provider.fallback("follow up")

    assert first.speech == "answer 1"
    assert second.speech == "answer 2"
    assert requests[0]["model"] == "test-model"
    assert "Rayen" not in requests[0]["messages"][0]["content"]
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert [message["role"] for message in requests[1]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_specialist_call_is_isolated_from_fallback_history() -> None:
    payloads: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Specialist conclusion."}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = GroqProvider("Jarvis system prompt", client=client)

    answer = provider.consult("hard question")

    assert answer == "Specialist conclusion."
    assert [message["role"] for message in payloads[0]["messages"]] == [
        "system",
        "user",
    ]
    assert payloads[0]["messages"][1]["content"] == "hard question"
