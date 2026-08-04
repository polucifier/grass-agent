import os
from dataclasses import dataclass, field


@dataclass
class OllamaConfig:
    model: str = "qwen2.5-coder:3b"
    embedding_model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


@dataclass
class APIConfig:
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""

    def get_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        return {
            "anthropic": "https://api.anthropic.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        }.get(self.provider, "")


@dataclass
class AgentConfig:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    api: APIConfig = field(default_factory=APIConfig)
    use_api: bool = False
    max_tool_calls_per_turn: int = 10
    similarity_threshold: float = 0.4

    @classmethod
    def from_env(cls) -> "AgentConfig":
        use_api = os.environ.get("GRASS_AGENT_USE_API", "").lower() in ("1", "true", "yes")

        ollama = OllamaConfig(
            model=os.environ.get("GRASS_OLLAMA_MODEL", "qwen2.5-coder:3b"),
            embedding_model=os.environ.get("GRASS_OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            base_url=os.environ.get("GRASS_OLLAMA_BASE_URL", "http://localhost:11434"),
        )

        api = APIConfig(
            provider=os.environ.get("GRASS_API_PROVIDER", "openai"),
            model=os.environ.get("GRASS_API_MODEL", "gpt-4o"),
            api_key=os.environ.get("GRASS_API_KEY", ""),
            base_url=os.environ.get("GRASS_API_BASE_URL", ""),
        )

        max_tools = int(os.environ.get("GRASS_MAX_TOOL_CALLS", "10"))
        threshold = float(os.environ.get("GRASS_SIMILARITY_THRESHOLD", "0.4"))

        return cls(
            ollama=ollama,
            api=api,
            use_api=use_api,
            max_tool_calls_per_turn=max_tools,
            similarity_threshold=threshold,
        )
