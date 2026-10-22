"""The self-healing loop: unified budget, targeted re-query, repair prompt.

Every failed attempt -- static rejection, runtime failure, crash, or timeout --
costs exactly one unit of a single budget (FR-009a). That budget is *not*
duplicated per stage, so a case can exhaust it without ever executing. That is
an intended, reported outcome rather than a fault (spec Assumptions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from code_generator import SYSTEM_PROMPT, extract_python_code
from config import GenerationConfig
from llm_provider import DEFAULT_NUM_PREDICT, OllamaProvider
from rag_retriever import GrassToolsRetriever

from .inventory import MapInventory

# Failure modes for which an omitted inventory is a defect rather than a
# degradation. A missing-map failure is unhealable without knowing what maps
# exist, so FR-012a makes the inventory mandatory there (SC-006a).
_GROUNDING_REQUIRED_MODES = frozenset({"missing_input"})

# The repair prompt inherits the Zero-Chat contract. A model that answers with
# fences or prose has not produced a script; the extractor strips what it can
# and whatever remains still has to parse.
REPAIR_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You are repairing a GRASS Python script that failed. Produce ONLY the complete corrected
Python script. No explanations, no commentary, no markdown fences.

The previous script failed with the error shown below. Fix the cause of that specific
error. Keep the same imports and the same grass.tools interface. Do not change the task.
"""


@dataclass
class RepairContext:
    """Everything one repair attempt is allowed to see (FR-012, FR-012a).

    The four FR-012 elements are joined by an optional ``available_maps``
    block: the dataset's own map names. Without it, a ``missing_input`` failure
    tells the model only that some invented name was wrong, never what the
    right name could be.
    """

    original_prompt: str
    previous_code: str
    error_text: str
    tool_documentation: str
    available_maps: str = ""

    def to_user_message(self) -> str:
        grounding = f"{self.available_maps}\n\n" if self.available_maps.strip() else ""
        return (
            f"Task: {self.original_prompt}\n\n"
            f"Relevant GRASS tools documentation:\n\n{self.tool_documentation}\n\n"
            f"{grounding}"
            f"The previous script failed with this error:\n\n{self.error_text}\n\n"
            f"Previous script:\n\n{self.previous_code}\n\n"
            "Generate the corrected Python script:"
        )

    def missing_elements(self, failure_mode: str | None = None) -> list[str]:
        """Which required inputs are absent (SC-006, SC-006a).

        The four FR-012 elements are always required. The dataset inventory is
        required *only* when the failure being repaired is ``missing_input``:
        there, its absence is the reason the loop cannot converge, so a repair
        attempt without it is incomplete.
        """
        missing = []
        if not self.original_prompt.strip():
            missing.append("original task")
        if not self.previous_code.strip():
            missing.append("previous script")
        if not self.error_text.strip():
            missing.append("exact error")
        if not self.tool_documentation.strip():
            missing.append("targeted tool documentation")
        if failure_mode in _GROUNDING_REQUIRED_MODES and not self.available_maps.strip():
            missing.append("available dataset maps")
        return missing


@dataclass
class RepairAttempt:
    """One regeneration driven by a failure."""

    code: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    documentation_used: list[str] = field(default_factory=list)
    used_error_excerpt_fallback: bool = False


class Healer:
    """Builds repair prompts and re-queries documentation for the failing tool."""

    def __init__(
        self,
        config: GenerationConfig,
        provider: OllamaProvider,
        retriever: GrassToolsRetriever,
        top_k: int = 5,
        num_predict: int = DEFAULT_NUM_PREDICT,
        inventory_provider: "Callable[[], MapInventory] | None" = None,
    ):
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.top_k = top_k
        self.num_predict = num_predict
        # Lazily invoked and cached: reading the inventory once per case would
        # be wasteful, and a provider that reads it must never be called before
        # the dataset is known to exist.
        self._inventory_provider = inventory_provider
        self._inventory: MapInventory | None = None

    def inventory(self) -> MapInventory:
        """The dataset map inventory, read once and cached.

        A provider that raises is treated as "no inventory" -- grounding is an
        enhancement, and failing to read it must not take down the healing loop
        that it exists to improve.
        """
        if self._inventory is not None:
            return self._inventory
        if self._inventory_provider is None:
            self._inventory = MapInventory()
            return self._inventory
        try:
            self._inventory = self._inventory_provider()
        except Exception:  # noqa: BLE001 - grounding must never be fatal
            self._inventory = MapInventory()
        return self._inventory

    def targeted_documentation(
        self, failing_tool: str | None, error_text: str, original_prompt: str
    ) -> tuple[str, list[str], bool]:
        """Re-query the knowledge base for the tool named in the failure (FR-011).

        When no tool can be identified -- a bare AttributeError on a typo, a
        Python TypeError -- this falls back to querying with the error text
        itself. That fallback is required behaviour, not an error path.
        """
        from code_generator import format_context

        used_fallback = False
        if failing_tool:
            doc = self.retriever.get_tool(failing_tool)
            docs = [doc] if doc is not None else []
            if not docs:
                # The error named a tool the knowledge base does not have.
                docs = self.retriever.retrieve(
                    f"{failing_tool} {error_text}", self._embed(failing_tool), k=self.top_k
                )
        else:
            used_fallback = True
            docs = self.retriever.retrieve(
                f"{error_text} {original_prompt}", self._embed(error_text or original_prompt), k=self.top_k
            )

        names = [d.name for d in docs]
        return format_context(docs), names, used_fallback

    def _embed(self, text: str) -> list[float]:
        return self.provider.generate_embeddings(text)

    def build_context(
        self,
        original_prompt: str,
        previous_code: str,
        error_text: str,
        failing_tool: str | None,
        failure_mode: str | None = None,
    ) -> RepairContext:
        documentation, _, _ = self.targeted_documentation(
            failing_tool, error_text, original_prompt
        )
        # The inventory is included whenever it is known, not only for
        # missing_input: grounding against hallucinated names helps every
        # repair. It is merely *required* for missing_input (FR-012a).
        return RepairContext(
            original_prompt=original_prompt,
            previous_code=previous_code,
            error_text=error_text,
            tool_documentation=documentation,
            available_maps=self.inventory().format_block(),
        )

    def repair(self, context: RepairContext) -> RepairAttempt:
        """One regeneration. Output goes through the Zero-Chat extractor."""
        messages = [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": context.to_user_message()},
        ]
        options = {"num_predict": self.num_predict}
        try:
            text, stats = self.provider.chat_with_stats(messages, options=options)
        except TypeError:
            # Provider without options support: degrade, never fabricate counts.
            text, stats = self.provider.chat(messages), {}

        code = extract_python_code(text)
        code = _normalise_dotted_calls(code)
        return RepairAttempt(
            code=code,
            prompt_tokens=int(stats.get("prompt_tokens", 0) or 0),
            completion_tokens=int(stats.get("completion_tokens", 0) or 0),
        )


def _normalise_dotted_calls(code: str) -> str:
    """tools.v.buffer -> tools.v_buffer, matching Gate 1 normalisation."""
    import re

    def replace(match):
        return f"tools.{match.group(1).replace('.', '_')}("

    return re.sub(r"\btools\.([a-zA-Z0-9_.]+)\s*\(", replace, code)


def legacy_interface_issues(code: str) -> list[str]:
    """Reject legacy and shell-based invocations (FR-015, constitution II).

    Generated code must use grass.tools exclusively. `grass.script.run_command`,
    `gs.run_command`, `subprocess`, and `os.system` are all violations -- they
    are rejected as a failed attempt so the healing loop gets a turn, not
    raised as a harness error.
    """
    import re

    issues: list[str] = []
    banned_patterns = {
        r"\bgrass\.script\.run_command\b": "grass.script.run_command",
        r"\bgs\.run_command\b": "gs.run_command",
        r"\brun_command\s*\(": "run_command",
        r"\bsubprocess\.(?:run|call|check_output|Popen)\b": "subprocess",
        r"\bos\.system\s*\(": "os.system",
        r"\bos\.popen\s*\(": "os.popen",
    }
    for pattern, label in banned_patterns.items():
        if re.search(pattern, code):
            issues.append(
                f"legacy interface violation: {label} is prohibited; "
                f"use only the grass.tools interface (from grass.tools import Tools)"
            )
    return issues


def write_script(path: Path, code: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8")
    return path