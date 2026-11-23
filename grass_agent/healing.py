"""The self-healing loop: stateful history, no-op detection, and parameter pivots.

Gate 2 used one shared budget and a "last error only" context. Gate 3 keeps the
ordered attempt history across both repair tiers, rejects byte- or AST-identical
duplicates before execution, and pivots to an explicit knowledge-base parameter
list when a repair repeats itself.

The four FR-012 prompt elements are unchanged: when no history is supplied the
rendered message is byte-for-byte the Gate 2 prompt.
"""

from __future__ import annotations

import ast
import hashlib
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

# History code and excerpts share a bounded context budget. Metadata (ordinal,
# tier, stage, mode, duplicate flag) is never truncated.
HISTORY_CONTEXT_BUDGET = 6000
HISTORY_EXCERPT_LIMIT = 600
HISTORY_EXCERPT_LINES = 12
HISTORY_DIGEST_PREFIX = 12

NO_REPEAT_INSTRUCTION = "DO NOT repeat previous scripts or failed parameter combinations."

# The repair prompt inherits the Zero-Chat contract. A model that answers with
# fences or prose has not produced a script; the extractor strips what it can
# and whatever remains still has to parse.
REPAIR_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You are repairing a GRASS Python script that failed. Produce ONLY the complete corrected
Python script. No explanations, no commentary, no markdown fences.

The previous script failed with the error shown below. Fix the cause of that specific
error. Keep the same imports and the same grass.tools interface. Do not change the task.
"""

PIVOT_INSTRUCTION = (
    "This attempt must change the approach. Use the parameter table above and do not "
    "resubmit a previous program. Pick different tool parameters that address the "
    "reported failure."
)


@dataclass
class RepairTurn:
    """One entry in the ordered attempt history supplied to a repair prompt."""

    ordinal: int
    budget_tier: str = "initial"
    code: str = ""
    failure_mode: str | None = None
    error_excerpt: str = ""
    stage: str = "runtime"  # "static" | "runtime" | "success"
    duplicate: bool = False

    # ---- Feature 004 diagnostics (defaults preserve the rendered history)
    pipeline: str = "legacy"
    plan_revision: int = 0
    plan_repair_count: int = 0
    replan_count: int = 0
    planned_tools: list[str] = field(default_factory=list)
    tool_swap: str | None = None


@dataclass
class RepairContext:
    """Everything one repair attempt is allowed to see (FR-012, FR-012a).

    The four FR-012 elements are joined by an optional ``available_maps``
    block: the dataset's own map names. Without it, a ``missing_input`` failure
    tells the model only that some invented name was wrong, never what the
    right name could be.

    `attempt_history` is the stateful memory added by Gate 3 (FR-003, FR-005).
    It defaults to empty, in which case the prompt is byte-for-byte the Gate 2
    four-element prompt. Feature 004 adds optional manual-card and plan blocks;
    they are empty by default, so the byte-for-byte guarantee is unchanged.
    """

    original_prompt: str
    previous_code: str
    error_text: str
    tool_documentation: str
    available_maps: str = ""
    attempt_history: list[RepairTurn] = field(default_factory=list)
    pivot: bool = False
    parameter_table: str = ""

    # ---- Feature 004 (all defaulted)
    pipeline: str = "legacy"
    plan_revision: int = 0
    plan_repair_count: int = 0
    replan_count: int = 0
    planned_tools: list[str] = field(default_factory=list)
    plan: object | None = None
    manual_card: str = ""
    tool_swap_candidates: list[str] = field(default_factory=list)
    tool_swap: str | None = None

    def _feature_block(self) -> str:
        """Optional manual/plan context; empty for a legacy default context."""
        blocks: list[str] = []
        if self.manual_card.strip():
            blocks.append(f"### Manual card (authoritative)\n\n{self.manual_card.strip()}")
        if self.plan is not None:
            blocks.append(f"### Current Plan (advisory)\n\n{_format_plan(self.plan)}")
        if self.tool_swap_candidates:
            alternatives = "\n".join(
                f"  - {candidate}" for candidate in self.tool_swap_candidates
            )
            blocks.append(f"### Documented Alternatives\n\n{alternatives}")
        if self.tool_swap:
            blocks.append(
                f"The previous tool `{self.tool_swap.split(' -> ')[0]}` is "
                f"excluded. Use the documented alternative above."
            )
        return "\n\n".join(blocks) + ("\n\n" if blocks else "")

    def to_user_message(self) -> str:
        grounding = f"{self.available_maps}\n\n" if self.available_maps.strip() else ""
        feature_block = self._feature_block()
        if not self.attempt_history:
            return (
                f"Task: {self.original_prompt}\n\n"
                f"Relevant GRASS tools documentation:\n\n{self.tool_documentation}\n\n"
                f"{feature_block}"
                f"{grounding}"
                f"The previous script failed with this error:\n\n{self.error_text}\n\n"
                f"Previous script:\n\n{self.previous_code}\n\n"
                "Generate the corrected Python script:"
            )

        history_block = _render_history(self.attempt_history)
        pivot_block = (
            f"### Failing Tool Parameters\n\n{self.parameter_table}\n\n"
            f"{PIVOT_INSTRUCTION}\n\n"
            if self.pivot and self.parameter_table.strip()
            else ""
        )
        if self.pivot and not self.parameter_table.strip():
            pivot_block = f"{PIVOT_INSTRUCTION}\n\n"
        return (
            f"Task: {self.original_prompt}\n\n"
            f"Relevant GRASS tools documentation:\n\n{self.tool_documentation}\n\n"
            f"{feature_block}"
            f"{grounding}"
            f"### Previous Attempts\n\n{history_block}\n"
            f"{NO_REPEAT_INSTRUCTION}\n\n"
            f"{pivot_block}"
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
    pivot_used: bool = False


# --------------------------------------------------------------------------
# No-op detection (FR-006, research R6)
# --------------------------------------------------------------------------


def normalized_code(code: str) -> str:
    return code.replace("\r\n", "\n").replace("\r", "\n")


def byte_digest(code: str) -> str:
    """SHA-256 of line-ending-normalized bytes."""
    return hashlib.sha256(normalized_code(code).encode("utf-8")).hexdigest()


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]


def ast_digest(code: str) -> str | None:
    """SHA-256 of a docstring-stripped, attribute-free AST dump.

    Returns None when the candidate does not parse; it then participates by
    byte digest only (the static guard rejects it anyway).
    """
    try:
        tree = ast.parse(normalized_code(code))
    except (SyntaxError, ValueError):
        return None
    _strip_docstrings(tree)
    dumped = ast.dump(tree, annotate_fields=False, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


@dataclass
class NoOpDigest:
    """The two deterministic fingerprints of one candidate."""

    code_sha256: str
    ast_sha256: str | None
    ordinal: int


@dataclass
class NoOpIndex:
    """Case-level duplicate index seeded with the initial candidate.

    A candidate is a duplicate if either digest matches any prior attempt,
    including attempts from the other repair tier (FR-006c).
    """

    by_code: dict[str, int] = field(default_factory=dict)
    by_ast: dict[str, int] = field(default_factory=dict)

    def add(self, code: str, ordinal: int) -> NoOpDigest:
        digest = NoOpDigest(
            code_sha256=byte_digest(code),
            ast_sha256=ast_digest(code),
            ordinal=ordinal,
        )
        self.by_code.setdefault(digest.code_sha256, ordinal)
        if digest.ast_sha256 is not None:
            self.by_ast.setdefault(digest.ast_sha256, ordinal)
        return digest

    def match(self, code: str) -> NoOpDigest | None:
        """Return the first matching prior digest, or None."""
        code_sha = byte_digest(code)
        ast_sha = ast_digest(code)
        ordinal = self.by_code.get(code_sha)
        if ordinal is not None:
            return NoOpDigest(code_sha, ast_sha, ordinal)
        if ast_sha is not None:
            ordinal = self.by_ast.get(ast_sha)
            if ordinal is not None:
                return NoOpDigest(code_sha, ast_sha, ordinal)
        return None

    def __len__(self) -> int:
        return len(self.by_code)


def _digest_prefix(code: str) -> str:
    return byte_digest(code)[:HISTORY_DIGEST_PREFIX]


def _bounded_excerpt(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    excerpt = "\n".join(lines[:HISTORY_EXCERPT_LINES])
    if len(excerpt) > HISTORY_EXCERPT_LIMIT:
        excerpt = excerpt[:HISTORY_EXCERPT_LIMIT]
    if len(excerpt) < len(text):
        excerpt += "\n[excerpt truncated]"
    return excerpt


def _render_history(turns: list[RepairTurn]) -> str:
    """Render metadata for every turn; full code only for the newest.

    Older code is replaced by a deterministic digest plus a bounded excerpt
    once the history would exceed HISTORY_CONTEXT_BUDGET characters.
    """
    blocks: list[str] = []
    used = 0
    newest = len(turns) - 1
    for index, turn in enumerate(turns):
        mode = turn.failure_mode or "success"
        header = (
            f"#### Attempt {turn.ordinal} — tier={turn.budget_tier}, "
            f"stage={turn.stage}, failure={mode}, "
            f"duplicate={'yes' if turn.duplicate else 'no'}"
        )
        excerpt = turn.error_excerpt or "(no diagnostic)"
        if index != newest:
            excerpt = _bounded_excerpt(excerpt)
        blocks.append(header)
        blocks.append(f"Error excerpt: {excerpt}")

        code = normalized_code(turn.code or "")
        if index == newest:
            # The newest failed code is always present in full.
            blocks.append("Full code:")
            blocks.append(code)
            used += len(code)
        else:
            remaining = max(0, HISTORY_CONTEXT_BUDGET - used)
            if remaining <= 0:
                blocks.append(
                    f"Code digest: sha256:{_digest_prefix(code)} "
                    f"({len(code.splitlines())} lines, omitted: history budget)"
                )
            else:
                snippet = code[:remaining]
                if len(snippet) < len(code):
                    snippet += "\n[code truncated]"
                blocks.append(
                    f"Code digest: sha256:{_digest_prefix(code)} "
                    f"({len(code.splitlines())} lines)"
                )
                blocks.append("Code excerpt:")
                blocks.append(snippet)
                used += len(snippet)
        blocks.append("")
    return "\n".join(blocks)


def _format_plan(plan) -> str:
    """Render an ExecutionPlan (or dict) as compact advisory text."""
    if plan is None:
        return ""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps", [])
    lines: list[str] = []
    for step in steps or []:
        if isinstance(step, dict):
            identifier = step.get("id", "?")
            tool = step.get("tool", "?")
            intent = step.get("intent", "")
            outputs = step.get("outputs", [])
        else:
            identifier = getattr(step, "id", "?")
            tool = getattr(step, "tool", "?")
            intent = getattr(step, "intent", "")
            outputs = getattr(step, "outputs", [])
        lines.append(f"{identifier}. {tool} — {intent} -> {', '.join(outputs) or '—'}")
    return "\n".join(lines)


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
        pipeline: str = "legacy",
        manual_renderer=None,
        manual_budget: int | None = None,
    ):
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.top_k = top_k
        self.num_predict = num_predict
        self.pipeline = pipeline
        self.manual_renderer = manual_renderer
        self.manual_budget = manual_budget
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

        In ``manual-kb``/``planned`` the failing tool's complete manual card is
        used as repair context; legacy keeps ``format_context()`` byte for byte.
        """
        from code_generator import format_context

        used_fallback = False
        if failing_tool:
            doc = self.retriever.get_manual(failing_tool) if self.pipeline != "legacy" else self.retriever.get_tool(failing_tool)
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
        if self.pipeline != "legacy" and docs:
            return self.manual_card(docs[0].name) or "", names, used_fallback
        return format_context(docs), names, used_fallback

    def manual_card(self, tool: str | None) -> str | None:
        """Render the failing tool's manual card (repair rung 1)."""
        if not tool:
            return None
        doc = self.retriever.get_manual(tool) if hasattr(self.retriever, "get_manual") else None
        if doc is None:
            doc = self.retriever.get_tool(tool)
        if doc is None:
            return None
        try:
            from grass_agent.manual_context import render_manual_cards

            renderer = self.manual_renderer or render_manual_cards
            budget = self.manual_budget
            if budget is None:
                budget = int(0.45 * getattr(self.config, "num_ctx", 8192))
            return renderer([doc], budget=budget, num_ctx=getattr(self.config, "num_ctx", 8192)).text
        except Exception:  # noqa: BLE001 - a card failure degrades to the old path
            from code_generator import format_context

            return format_context([doc])

    def tool_swap_candidates(self, failing_tool: str | None, limit: int = 2) -> list[str]:
        """Documented alternatives for the failing functional step."""
        if not failing_tool:
            return []
        from rag_retriever import family_alternatives

        return [
            doc.name
            for doc in family_alternatives(failing_tool, self.retriever, limit=limit)
            if doc.name != failing_tool
        ]

    def _embed(self, text: str) -> list[float]:
        return self.provider.generate_embeddings(text)

    def parameter_list(self, tool: str | None) -> str | None:
        """A deterministic parameter table for the failing tool (FR-006b).

        Read from the knowledge base: signature, required/optional parameters,
        and defaults. Returns None when the tool is unknown, so the pivot
        degrades to the generic no-repeat instruction rather than inventing a
        table.
        """
        if not tool or self.retriever is None:
            return None
        doc = self.retriever.get_tool(tool)
        if doc is None:
            # The failure text may name the module form (v.buffer) while the
            # knowledge base keys the wrapper form (v_buffer), or vice versa.
            alternatives = (
                tool.replace(".", "_"),
                tool.replace("_", "."),
                tool.replace(".", "_").replace("_", ".", 1),
            )
            for alternative in alternatives:
                doc = self.retriever.get_tool(alternative)
                if doc is not None:
                    break
        if doc is None:
            return None

        lines = [f"Tool: `{doc.name}`", "", f"Signature: `{doc.signature}`", ""]
        params = doc.params or {}
        if params:
            lines.append("| Parameter | Type | Required | Default | Allowed values |")
            lines.append("|---|---|---|---|---|")
            for name in sorted(params):
                entry = params[name] or {}
                allowed = ""
                options = getattr(doc, "options", {}) or {}
                if name in options:
                    allowed = ", ".join(
                        str(option.get("value") if isinstance(option, dict) else getattr(option, "value", ""))
                        for option in options[name]
                    )
                lines.append(
                    f"| `{name}` | {entry.get('type', '')} | "
                    f"{'yes' if entry.get('required') else 'no'} | "
                    f"{entry.get('default', '')} | {allowed} |"
                )
        flags = []
        for flag in getattr(doc, "flags", []) or []:
            if isinstance(flag, dict):
                name, generic = flag.get("flag", ""), bool(flag.get("generic", False))
                description = flag.get("description", "")
            else:
                name, generic = getattr(flag, "flag", ""), bool(getattr(flag, "generic", False))
                description = getattr(flag, "description", "")
            if name and not generic:
                flags.append(f"- `-{name}` {description}".rstrip())
        if flags:
            lines.extend(["", "Flags:", *flags])
        return "\n".join(lines)

    def build_context(
        self,
        original_prompt: str,
        previous_code: str,
        error_text: str,
        failing_tool: str | None,
        failure_mode: str | None = None,
        history: list[RepairTurn] | None = None,
        pivot: bool = False,
        plan=None,
        plan_revision: int = 0,
        plan_repair_count: int = 0,
        replan_count: int = 0,
        planned_tools: list[str] | None = None,
        tool_swap_candidates: list[str] | None = None,
        tool_swap: str | None = None,
        manual_card: str | None = None,
    ) -> RepairContext:
        documentation, _, _ = self.targeted_documentation(
            failing_tool, error_text, original_prompt
        )
        # The inventory is included whenever it is known, not only for
        # missing_input: grounding against hallucinated names helps every
        # repair. It is merely *required* for missing_input (FR-012a).
        feature_card = manual_card
        documentation_text = documentation
        if self.pipeline != "legacy":
            if feature_card is None:
                feature_card = documentation
            documentation_text = (
                "The authoritative manual card is included below."
                if feature_card
                else documentation
            )
        return RepairContext(
            original_prompt=original_prompt,
            previous_code=previous_code,
            error_text=error_text,
            tool_documentation=documentation_text,
            available_maps=self.inventory().format_block(),
            attempt_history=list(history or []),
            pivot=pivot,
            parameter_table=(self.parameter_list(failing_tool) or "") if pivot else "",
            pipeline=self.pipeline,
            plan_revision=plan_revision,
            plan_repair_count=plan_repair_count,
            replan_count=replan_count,
            planned_tools=list(planned_tools or []),
            plan=plan,
            manual_card=feature_card or "",
            tool_swap_candidates=list(tool_swap_candidates or []),
            tool_swap=tool_swap,
        )

    def repair(self, context: RepairContext, pivot: bool = False) -> RepairAttempt:
        """One regeneration. Output goes through the Zero-Chat extractor."""
        if pivot:
            context.pivot = True
            if not context.parameter_table:
                # The context may not have been built with the failing tool's
                # table; a pivot still changes the prompt shape.
                context.parameter_table = ""
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
            pivot_used=bool(context.pivot),
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