import ollama as ollama_lib

from config import GenerationConfig


class OllamaProvider:

    def __init__(self, config: GenerationConfig):
        self.model = config.model
        self.embedding_model = config.embedding_model
        self.base_url = config.ollama_base_url

    def chat(self, messages: list[dict]) -> str:
        response = ollama_lib.chat(model=self.model, messages=messages)
        return response.message.content or ""

    def generate_embeddings(self, text: str) -> list[float]:
        response = ollama_lib.embeddings(model=self.embedding_model, prompt=text)
        return response["embedding"]
