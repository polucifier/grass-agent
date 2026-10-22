import ollama as ollama_lib

from config import GenerationConfig

# Generation cap for the Gate 2 harness. A correct GRASS script is well under
# 100 lines; 1024 tokens is generous. Without a cap a small local model can
# degenerate into an unbounded repeat loop -- observed at 19,579 generated
# tokens for a 15-line script -- which stalls the suite indefinitely. The
# execution timeout does not help: the model never reaches execution.
DEFAULT_NUM_PREDICT = 1024


class OllamaProvider:

    def __init__(self, config: GenerationConfig, default_options: dict | None = None):
        self.model = config.model
        self.embedding_model = config.embedding_model
        self.base_url = config.ollama_base_url
        # Merged into any request that does not pass explicit options. Left as
        # None by the Gate 1 caller, so run_gate1.py behaviour is unchanged.
        self.default_options = default_options
        # Stats from the most recent call. Recorded as a side effect because
        # GrassCodeGenerator.generate() returns only the code, so re-issuing the
        # request just to read the counters would double inference cost.
        self.last_stats: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    def _options(self, options: dict | None) -> dict | None:
        if self.default_options is None:
            return options
        merged = dict(self.default_options)
        if options:
            merged.update(options)
        return merged

    def chat(self, messages: list[dict], options: dict | None = None) -> str:
        response = ollama_lib.chat(
            model=self.model, messages=messages, options=self._options(options)
        )
        self._record(response)
        return response.message.content or ""

    def chat_with_stats(self, messages: list[dict], options: dict | None = None) -> tuple[str, dict[str, int]]:
        """Chat and return the local service's own token counters alongside the text.

        Added for Gate 2 so per-attempt token accounting is measured rather than
        estimated (FR-018, SC-008). Additive: the Gate 1 call site in
        code_generator.py keeps working unchanged.

        Returns (text, stats) where stats carries `prompt_tokens` and
        `completion_tokens`. Both are 0 when the service omits the counters --
        never estimated, so a run's token totals cannot silently overstate cost.
        """
        response = ollama_lib.chat(
            model=self.model, messages=messages, options=self._options(options)
        )
        stats = self._record(response)
        return response.message.content or "", stats

    def _record(self, response) -> dict[str, int]:
        stats = {
            "prompt_tokens": int(getattr(response, "prompt_eval_count", 0) or 0),
            "completion_tokens": int(getattr(response, "eval_count", 0) or 0),
        }
        self.last_stats = stats
        return stats

    def generate_embeddings(self, text: str) -> list[float]:
        response = ollama_lib.embeddings(model=self.embedding_model, prompt=text)
        return response["embedding"]
