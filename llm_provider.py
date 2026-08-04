import json
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import ollama as ollama_lib

from config import AgentConfig, OllamaConfig, APIConfig

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    raw: Any = None


class LLMProvider(ABC):

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        ...

    @abstractmethod
    def supports_tool_calling(self) -> bool:
        ...

    @abstractmethod
    def generate_embeddings(self, text: str) -> list[float]:
        ...


def _parse_tool_calls_from_text(text: str) -> list[ToolCall] | None:
    """Robust fallback parser: extract tool calls from raw LLM text output."""
    cleaned = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Try to find JSON objects in the text
    # First, try parsing the whole cleaned text as JSON
    candidates = []

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            candidates.append(obj)
    except json.JSONDecodeError:
        pass

    # If that failed, find all {...} blocks via regex
    if not candidates:
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    candidates.append(obj)
            except json.JSONDecodeError:
                continue

    # Look for a candidate with "name" key (tool call pattern)
    for obj in candidates:
        if "name" in obj:
            args = obj.get("arguments", obj.get("args", obj.get("parameters", {})))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            return [ToolCall(name=obj["name"], arguments=args)]

    return None


class OllamaProvider(LLMProvider):

    def __init__(self, config: OllamaConfig):
        self.model = config.model
        self.embedding_model = config.embedding_model
        self.base_url = config.base_url

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = ollama_lib.chat(**kwargs)

        tool_calls = None
        if response.message.tool_calls:
            tool_calls = [
                ToolCall(name=tc.function.name, arguments=tc.function.arguments)
                for tc in response.message.tool_calls
            ]
        elif response.message.content:
            # Fallback: try to extract tool calls from text output
            parsed = _parse_tool_calls_from_text(response.message.content)
            if parsed:
                logger.info("Fallback parser activated: extracted tool call from text")
                tool_calls = parsed

        return LLMResponse(
            content=response.message.content,
            tool_calls=tool_calls,
            raw=response,
        )

    def supports_tool_calling(self) -> bool:
        return True

    def generate_embeddings(self, text: str) -> list[float]:
        response = ollama_lib.embeddings(model=self.embedding_model, prompt=text)
        return response["embedding"]


class APIProvider(LLMProvider):

    def __init__(self, config: APIConfig):
        self.model = config.model
        self.api_key = config.api_key
        self.provider = config.provider

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for API provider. "
                "Install it with: pip install openai"
            )

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        else:
            base_url = config.get_base_url()
            if base_url:
                kwargs["base_url"] = base_url

        self.client = OpenAI(**kwargs)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = []
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, arguments=args))
        elif choice.message.content:
            parsed = _parse_tool_calls_from_text(choice.message.content)
            if parsed:
                logger.info("Fallback parser activated: extracted tool call from text")
                tool_calls = parsed

        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            raw=response,
        )

    def supports_tool_calling(self) -> bool:
        return True

    def generate_embeddings(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Embeddings via API provider not yet supported. "
            "Use OllamaProvider for RAG embedding needs."
        )


def create_provider(config: AgentConfig) -> LLMProvider:
    if config.use_api:
        return APIProvider(config.api)
    return OllamaProvider(config.ollama)
