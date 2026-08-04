import json
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import ollama as ollama_lib

from config import AgentConfig, OllamaConfig, APIConfig

logger = logging.getLogger(__name__)

JSON_SCHEMA_TYPE_MAP = {
    "float": "number",
    "int": "integer",
    "str": "string",
    "bool": "boolean",
}


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

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    candidates = []

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            candidates.append(obj)
    except json.JSONDecodeError:
        pass

    if not candidates:
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    candidates.append(obj)
            except json.JSONDecodeError:
                continue

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


def _convert_schema_type(python_type: str) -> str:
    return JSON_SCHEMA_TYPE_MAP.get(python_type, python_type)


def _format_tool(tool_def) -> dict:
    properties = {}
    required = []
    for param_name, param_info in tool_def.parameters.items():
        param_type = _convert_schema_type(param_info["type"])
        properties[param_name] = {
            "type": param_type,
            "description": param_info["description"],
        }
        if param_info.get("required"):
            required.append(param_name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": schema,
        },
    }


def _format_server_tool(name: str, server_tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": server_tool.description or "",
            "parameters": server_tool.inputSchema,
        },
    }


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


class GeminiProvider(LLMProvider):

    def __init__(self, config: APIConfig):
        self.model = config.model
        self.api_key = config.api_key

        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "The 'google-generativeai' package is required for Gemini provider. "
                "Install it with: pip install google-generativeai"
            )

        genai.configure(api_key=self.api_key)
        self._genai = genai

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        genai = self._genai
        model = genai.GenerativeModel(
            model_name=self.model,
            tools=tools if tools else [],
        )

        gemini_messages = self._convert_messages(messages)

        response = model.generate_content(gemini_messages)

        tool_calls = None
        if response.function_calls:
            tool_calls = [
                ToolCall(name=fc.name, arguments=dict(fc.args))
                for fc in response.function_calls
            ]
        elif response.text:
            parsed = _parse_tool_calls_from_text(response.text)
            if parsed:
                logger.info("Fallback parser activated: extracted tool call from text")
                tool_calls = parsed

        return LLMResponse(
            content=response.text,
            tool_calls=tool_calls,
            raw=response,
        )

    def _convert_messages(self, messages: list[dict]) -> list:
        gemini_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                gemini_messages.append(self._genai.types.Content(
                    role="user",
                    parts=[self._genai.types.Part.from_text(msg["content"])],
                ))
            elif role == "user":
                gemini_messages.append(self._genai.types.Content(
                    role="user",
                    parts=[self._genai.types.Part.from_text(msg["content"])],
                ))
            elif role == "assistant":
                if msg.get("tool_calls"):
                    parts = []
                    for tc in msg["tool_calls"]:
                        args_str = json.dumps(tc["arguments"]) if isinstance(tc["arguments"], dict) else tc["arguments"]
                        parts.append(self._genai.types.Part.from_function_call(
                            name=tc["function"]["name"],
                            args=json.loads(args_str) if isinstance(args_str, str) else args_str,
                        ))
                    gemini_messages.append(self._genai.types.Content(
                        role="model",
                        parts=parts,
                    ))
                elif msg.get("content"):
                    gemini_messages.append(self._genai.types.Content(
                        role="model",
                        parts=[self._genai.types.Part.from_text(msg["content"])],
                    ))
            elif role == "tool":
                gemini_messages.append(self._genai.types.Content(
                    role="tool",
                    parts=[self._genai.types.Part.from_text(msg["content"])],
                ))
        return gemini_messages

    def supports_tool_calling(self) -> bool:
        return True

    def generate_embeddings(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Embeddings via Gemini API not yet supported. "
            "Use OllamaProvider for RAG embedding needs."
        )


def create_provider(config: AgentConfig) -> LLMProvider:
    if config.use_api:
        if config.api.provider == "gemini":
            return GeminiProvider(config.api)
        return APIProvider(config.api)
    return OllamaProvider(config.ollama)
