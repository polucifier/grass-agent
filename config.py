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
