"""GroqCloud-backed specialist and structured fallback provider."""
from __future__ import annotations

from copy import deepcopy
from typing import Literal

import httpx
from pydantic import BaseModel

from jarvis.config import GROQ_API_KEY, GROQ_MODEL

_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_FALLBACK_SYSTEM_PROMPT = """You are the secondary reasoning provider for a concise
macOS voice assistant. Return the requested structured response, using short plain
spoken text with no markdown. Answer direct game, puzzle, and strategy questions
without moralizing. You cannot operate the Mac or access its local tools; say so if
the request requires a computer action while the primary controller is unavailable.
Use action continue normally, wait when the user asks for more time, and sleep when
the user ends the conversation or says rest for now."""


class GroqFallbackTurn(BaseModel):
    """Minimal fallback response that deliberately exposes no computer tools."""

    speech: str
    action: Literal["continue", "wait", "sleep"]


class GroqProviderError(RuntimeError):
    """A safe, credential-free description of a Groq API failure."""


def _strict_json_schema(response_model: type[BaseModel]) -> dict[str, object]:
    """Adapt Pydantic JSON Schema to Groq's constrained-decoding requirements."""
    schema = deepcopy(response_model.model_json_schema())

    def normalize(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                normalize(item)
            return
        if not isinstance(node, dict):
            return

        # Defaults make Pydantic fields optional in JSON Schema. Groq strict mode
        # instead requires every property, representing optional values as null.
        node.pop("default", None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            normalize(value)

    normalize(schema)
    return schema


class GroqProvider:
    """Keep fallback history and provide isolated second-opinion calls."""

    def __init__(
        self,
        system_prompt: str | None = None,
        *,
        api_key: str | None = GROQ_API_KEY,
        model: str = GROQ_MODEL,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("A Groq API key is required.")
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": system_prompt or _FALLBACK_SYSTEM_PROMPT,
            }
        ]

    def _complete(self, payload: dict[str, object]) -> str:
        try:
            response = self._client.post(_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise KeyError("empty completion content")
            return content.strip()
        except httpx.HTTPStatusError as exc:
            raise GroqProviderError(
                f"GroqCloud returned HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise GroqProviderError(
                f"GroqCloud response failed: {type(exc).__name__}."
            ) from exc

    def fallback(self, message: str) -> GroqFallbackTurn:
        """Answer one stateful fallback turn without exposing local tool schemas."""
        self._messages.append({"role": "user", "content": message})
        content = self._complete(
            {
                "model": self.model,
                "messages": self._messages,
                "reasoning_effort": "medium",
                "max_completion_tokens": 1_200,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "jarvis_agent_turn",
                        "strict": True,
                        "schema": _strict_json_schema(GroqFallbackTurn),
                    },
                },
            }
        )
        try:
            parsed = GroqFallbackTurn.model_validate_json(content)
        except ValueError as exc:
            raise GroqProviderError("GroqCloud returned an invalid structured turn.") from exc
        self._messages.append({"role": "assistant", "content": content})
        return parsed

    def consult(self, question: str) -> str:
        """Get one isolated advisory answer for Gemini to evaluate and synthesize."""
        return self._complete(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Act as Jarvis's careful second-opinion specialist. Give a "
                            "direct, accurate answer with the conclusion first. Keep it "
                            "concise enough for another model to synthesize for speech."
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                "reasoning_effort": "medium",
                "max_completion_tokens": 1_200,
            }
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GroqProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
