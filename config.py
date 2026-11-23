import os
from dataclasses import dataclass


@dataclass
class GenerationConfig:
    model: str = "qwen2.5-coder:7b"
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"
    rag_db_path: str = "data/grass_knowledge.db"
    rag_top_k: int = 5
    output_dir: str = "generated"

    # ---- Feature 004 additive fields (defaults preserve legacy behavior) ----
    # The pipeline mode is a property of the run, not of a single prompt. The
    # database shape and validation gate read it, so it lives on the generation
    # config where every existing caller already has it.
    pipeline: str = "legacy"
    num_ctx: int = 8192
    manual_context_tokens: int | None = None
    # ``None`` means "resolve from the pipeline": always True for manual-kb and
    # planned, and the explicit legacy opt-in (default False) for legacy.
    strict_options: bool | None = None
    shortlist_k: int = 12
    planner_model: str | None = None
    planner_timeout: int = 60

    @classmethod
    def from_env(cls) -> "GenerationConfig":
        return cls(
            model=os.environ.get("GRASS_OLLAMA_MODEL", "qwen2.5-coder:7b"),
            embedding_model=os.environ.get("GRASS_OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            ollama_base_url=os.environ.get("GRASS_OLLAMA_BASE_URL", "http://localhost:11434"),
            rag_db_path=os.environ.get("GRASS_RAG_DB", "data/grass_knowledge.db"),
            rag_top_k=int(os.environ.get("GRASS_RAG_TOP_K", os.environ.get("RAG_TOP_K", "5"))),
            output_dir=os.environ.get("GRASS_OUTPUT_DIR", "generated"),
        )

    def resolve_manual_budget(self) -> int:
        """Documentation budget in tokens (45% of the context by default)."""
        if self.manual_context_tokens is not None:
            return self.manual_context_tokens
        return int(0.45 * self.num_ctx)

    def effective_strict_options(self) -> bool:
        """Strict closed-enum validation is mandatory in the new modes."""
        if self.pipeline in ("manual-kb", "planned"):
            return True
        return bool(self.strict_options)
