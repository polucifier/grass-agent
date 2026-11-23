import ast
import re
from dataclasses import dataclass, field

from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever

SYNTHETIC_FLAG_PARAMS = {"flags", "overwrite", "verbose", "quiet", "superquiet"}

SYSTEM_PROMPT = """You are a GRASS expert. Generate a pure Python script that uses the
grass.tools API (GRASS 8.5+).

Rules:
1. Start the script exactly like this:
   from grass.tools import Tools
   tools = Tools()
2. Do NOT assign attributes on the tools object (e.g. never write "tools.overwrite = ...").
3. Tool names become methods with underscores instead of dots.
   CORRECT: tools.v_buffer(...), tools.r_slope_aspect(...)
   INCORRECT: tools.v.buffer(...), tools.r.slope.aspect(...)
   Never use dotted method chains. Every dot in a tool name (like v.buffer) MUST be replaced with an underscore (_).
4. Pass all parameters as keyword arguments strictly using parameter names defined in the RAG documentation context below. Do NOT hallucinate parameter names (e.g., use correct parameters from signature).
5. One GRASS parameter is named after a Python keyword: `from` in v.distance. It CANNOT be written as `from=value`. Pass it by unpacking a dict, and never invent a renamed variant such as `from_`.
   CORRECT:   tools.v_distance(**{"from": "a_points", "to": "b_points", "upload": "cat"})
   INCORRECT: tools.v_distance(from="a_points", to="b_points")
   INCORRECT: tools.v_distance(from_="a_points", to="b_points", upload="cat")
   If the task does not need such a parameter, simply omit it.
6. r.mapcalc takes exactly one parameter, "expression". Reference every raster inside the expression string. Do NOT pass raster names as separate keyword arguments.
   CORRECT:   tools.r_mapcalc(expression="ndvi = (nir - red) / (nir + red)")
   INCORRECT: tools.r_mapcalc(expression="ndvi = (nir - red) / (nir + red)", nir="nir", red="red")
7. Include every numeric value from the task (distances, resolutions, thresholds) as an
   actual parameter value, not a placeholder.
8. Coordinate pairs (x,y) and bounding box extents (n,s,e,w) MUST be passed as comma-separated string literals (e.g. "635000,216500" or "0,10,0,10").
9. For multi-step tasks, chain multiple tool calls sequentially, assigning intermediate raster or vector outputs to variables and passing them as input parameters to subsequent tools.
10. Output ONLY executable Python code. No conversational text, no explanations, and no markdown fences.
"""


AGENTIC_SYSTEM_PROMPT = SYSTEM_PROMPT + """
Planning rules:
1. The plan below is advisory. The per-step manual cards are authoritative.
2. If the planned tool cannot satisfy a step as documented, substitute a
   documented alternative from the same manual card family.
3. Use flags and option values exactly as the manual cards document them.
4. File-based parameters (rules, tables, datasets) must be created before the
   tool call that reads them.
5. The final output remains executable Python only. Never print or embed the
   plan JSON or manual prose in the script.
"""


CANONICAL_EXAMPLES = {
    "r.mapcalc": 'tools.r_mapcalc(expression="elevation_double = elevation * 2")',
    "r.mapcalc.simple": 'tools.r_mapcalc_simple(expression="A * 2", a="elevation", output="elevation_double")',
    # The four scraped examples below are not valid Python. `from`, `lambda`
    # and `yield` are reserved keywords, and m.nviz.image lost the quoting
    # around its size pair. Override them so the model is never shown a call
    # that cannot execute.
    "v.distance": 'tools.v_distance(**{"from": "buildings", "to": "fire_stations", "upload": "cat"})',
    "r.smooth.edgepreserve": 'tools.r_smooth_edgepreserve(input="dem", output="dem_smoothed", threshold=5, steps=10, function="tukey")',
    "r3.gwflow": 'tools.r3_gwflow(**{"phead": "head", "status": "status", "yield": "gw_yield", "output": "gwflow", "dtime": 86400})',
    "m.nviz.image": 'tools.m_nviz_image(output="view", format="ppm", size=(640, 480))',
}


def clean_signature(sig: str) -> str:
    if not sig:
        return sig
    lines = sig.splitlines()
    cleaned_lines = []
    excluded = {"flags", "overwrite", "verbose", "quiet", "superquiet"}
    for line in lines:
        stripped = line.strip()
        param_name = stripped.split("=")[0].strip()
        if param_name in excluded:
            continue
        cleaned_lines.append(line)
    result = "\n".join(cleaned_lines)
    result = re.sub(r",\s*\)", ")", result)
    return result


def format_context(docs) -> str:
    excluded = {"flags", "overwrite", "verbose", "quiet", "superquiet"}
    sections = []
    for doc in docs:
        parts = [f"### {doc.name}"]
        if doc.category:
            parts.append(f"Category: {doc.category}")
        parts.append(f"Description: {doc.description}")
        if doc.signature:
            cleaned_sig = clean_signature(doc.signature)
            parts.append(f"grass.tools signature: {cleaned_sig}")
        example_code = CANONICAL_EXAMPLES.get(doc.name) or doc.example
        if example_code:
            parts.append(f"Example:\n{example_code}")
        if doc.params:
            required = [p for p, info in doc.params.items() if info.get("required") and p not in excluded]
            if required:
                parts.append(f"Required parameters: {', '.join(required)}")
        sections.append("\n".join(parts))
    return "\n\n".join(sections)


@dataclass
class PipelineGenerationResult:
    """One generation candidate plus pipeline diagnostics (data-model 11).

    Legacy callers keep receiving a plain ``str`` from ``generate()``; the
    harness consumes this richer result so plan/card evidence can be persisted
    without changing the candidate budget.
    """

    code: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    plan: object | None = None
    plan_fallback: bool = False
    plan_repair_count: int = 0
    replan_count: int = 0
    planner_invocations: int = 0
    shortlist_shortfall: bool = False
    manual_cards: list = field(default_factory=list)
    manual_tokens: int = 0
    manual_omissions: list = field(default_factory=list)
    tool_swaps: list = field(default_factory=list)
    planner_prompt_tokens: int = 0
    planner_completion_tokens: int = 0
    retrieved_docs: list = field(default_factory=list)
    shortlist: list = field(default_factory=list)
    plan_validation: dict = field(default_factory=dict)
    planned_tools: list = field(default_factory=list)


class GrassCodeGenerator:

    def __init__(self, config: GenerationConfig, provider: OllamaProvider, retriever: GrassToolsRetriever):
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.api_issues: list[str] = []
        self.last_retrieved_docs: list = []
        self.last_system_prompt: str = ""
        self.last_user_message: str = ""
        self.last_response: str = ""
        self.last_code: str = ""
        self.last_request: str = ""
        self.last_manual_cards: list = []
        self.last_generation_result: "PipelineGenerationResult | None" = None

    def generate(self, request: str, inventory_block: str = "") -> str:
        if getattr(self.config, "pipeline", "legacy") != "legacy":
            return self.generate_result(request, inventory_block=inventory_block).code

        self.last_request = request
        query_embedding = self.provider.generate_embeddings(request)
        docs = self.retriever.retrieve(request, query_embedding, k=self.config.rag_top_k)
        self.last_retrieved_docs = docs

        context = format_context(docs)
        # Initial-prompt grounding (FR-012b): the dataset's real map names are
        # injected exactly as in the repair prompt, so attempt 1 can choose an
        # existing map instead of inventing one. An empty block is omitted
        # rather than rendered as an empty heading (graceful degradation).
        grounding = f"{inventory_block}\n\n" if inventory_block.strip() else ""
        user_message = (
            f"Relevant GRASS tools documentation:\n\n{context}\n\n"
            f"{grounding}"
            f"Task: {request}\n\nGenerate the Python script:"
        )
        self.last_system_prompt = SYSTEM_PROMPT
        self.last_user_message = user_message
        self.last_manual_cards = []

        response = self.provider.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ])
        self.last_response = response

        code = extract_python_code(response)
        code = normalize_dotted_calls(code)
        self.last_code = code
        validate_syntax(code)
        self.api_issues = validate_api(code, self.retriever)
        self.last_generation_result = PipelineGenerationResult(
            code=code,
            prompt_tokens=int((getattr(self.provider, "last_stats", None) or {}).get("prompt_tokens", 0) or 0),
            completion_tokens=int((getattr(self.provider, "last_stats", None) or {}).get("completion_tokens", 0) or 0),
        )
        return code

    # ------------------------------------------------------ Feature 004
    def generate_result(
        self,
        request: str,
        inventory_block: str = "",
        manual_renderer=None,
        agentic_pipeline=None,
        inventory_maps=None,
    ) -> "PipelineGenerationResult":
        """Generate one candidate and return every diagnostic the harness needs.

        ``legacy`` delegates to :meth:`generate` and therefore keeps the exact
        existing prompt, validation, and budget behavior. ``manual-kb`` renders
        compact cards; ``planned`` delegates to the agentic orchestrator.
        """
        pipeline = getattr(self.config, "pipeline", "legacy")
        if pipeline == "legacy":
            code = self.generate(request, inventory_block=inventory_block)
            result = self.last_generation_result or PipelineGenerationResult(code=code)
            result.code = code
            return result

        if pipeline == "planned" and agentic_pipeline is not None:
            result = agentic_pipeline.generate(
                request,
                inventory_block=inventory_block,
                inventory_maps=inventory_maps,
            )
            self.last_request = request
            self.last_generation_result = result
            self.last_code = result.code
            self.last_manual_cards = list(result.manual_cards)
            self.last_retrieved_docs = list(result.retrieved_docs)
            self.last_system_prompt = getattr(agentic_pipeline, "last_system_prompt", "")
            self.last_user_message = getattr(agentic_pipeline, "last_user_message", "")
            self.last_response = getattr(agentic_pipeline, "last_response", "")
            self.api_issues = validate_api(
                result.code,
                self.retriever,
                strict_options=True,
                pipeline=pipeline,
            )
            return result

        return self._generate_manual_kb(
            request, inventory_block=inventory_block, manual_renderer=manual_renderer
        )

    def _generate_manual_kb(
        self,
        request: str,
        inventory_block: str = "",
        manual_renderer=None,
    ) -> "PipelineGenerationResult":
        from grass_agent.manual_context import manual_budget, render_manual_cards

        self.last_request = request
        query_embedding = self.provider.generate_embeddings(request)
        docs = self.retriever.retrieve(request, query_embedding, k=self.config.rag_top_k)
        self.last_retrieved_docs = docs

        budget = getattr(self.config, "manual_context_tokens", None)
        if budget is None:
            budget = int(0.45 * getattr(self.config, "num_ctx", 8192))
        renderer = manual_renderer or render_manual_cards
        rendered = renderer(docs, budget=budget, num_ctx=getattr(self.config, "num_ctx", 8192))
        context = rendered.text
        self.last_manual_cards = rendered.cards

        grounding = f"{inventory_block}\n\n" if inventory_block.strip() else ""
        user_message = (
            "Relevant GRASS tools manual cards (authoritative; use flags and "
            "parameter names exactly as documented):\n\n"
            f"{context}\n\n"
            f"{grounding}"
            f"Task: {request}\n\nGenerate the Python script:"
        )
        self.last_system_prompt = SYSTEM_PROMPT
        self.last_user_message = user_message

        response = self.provider.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )
        self.last_response = response
        code = normalize_dotted_calls(extract_python_code(response))
        self.last_code = code
        validate_syntax(code)
        self.api_issues = validate_api(
            code, self.retriever, strict_options=True, pipeline="manual-kb"
        )
        stats = getattr(self.provider, "last_stats", None) or {}
        result = PipelineGenerationResult(
            code=code,
            prompt_tokens=int(stats.get("prompt_tokens", 0) or 0),
            completion_tokens=int(stats.get("completion_tokens", 0) or 0),
            manual_cards=list(rendered.cards),
            manual_tokens=rendered.tokens,
            manual_omissions=list(rendered.omissions),
            retrieved_docs=list(docs),
        )
        self.last_generation_result = result
        return result

    def format_debug_header(self) -> str:
        """Commented record of the exchange with the model.

        The RAG context is already embedded in the user message, so it is not
        repeated separately. Emits the prompt and the raw response as
        comments; the caller appends the final script as real code.
        """
        def comment(text: str) -> str:
            return "\n".join(f"# {line}" for line in text.splitlines())

        return f"""# ==============================================================================
# DEBUG: LLM PROMPT & RESPONSE
# ==============================================================================
# Task: {self.last_request}
# ------------------------------------------------------------------------------
# System Prompt:
{comment(self.last_system_prompt)}
# ------------------------------------------------------------------------------
# User Message Sent to LLM (includes the RAG tool documentation):
{comment(self.last_user_message)}
# ------------------------------------------------------------------------------
# Raw Model Response:
{comment(self.last_response)}
# ==============================================================================
"""


def normalize_dotted_calls(code: str) -> str:
    def replace_match(match):
        expr = match.group(1)
        normalized = expr.replace(".", "_")
        return f"tools.{normalized}("

    return re.sub(r"\btools\.([a-zA-Z0-9_.]+)\s*\(", replace_match, code)


def extract_python_code(text: str) -> str:
    # 1. Check for markdown code fences
    fences = re.findall(r"```(?:python)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if fences:
        for f in fences:
            if "grass.tools" in f or "tools." in f:
                return f.strip()
        return fences[0].strip()
    
    # 2. If no markdown fence, search for start line 'from grass.tools import Tools'
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if "from grass.tools import Tools" in line:
            start_idx = i
            break
    if start_idx is not None:
        code_lines = lines[start_idx:]
        cleaned = []
        for line in code_lines:
            # Stop if we hit conversational markdown headers or sentences after code
            if line.startswith("# Note") or line.startswith("Here is") or line.startswith("This script"):
                break
            cleaned.append(line)
        return "\n".join(cleaned).strip()
        
    return text.strip()


def validate_syntax(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Generated code is not valid Python (line {e.lineno}): {e.msg}") from e


def _dotted_parts(node) -> tuple[str, ...] | None:
    """Resolve a call target like tools.v_patch(...) or tools.v.patch(...).

    Returns ('tools', 'v', 'patch') when the call is made on the tools object,
    else None.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name) and node.id == "tools":
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def _resolve_tool_name(parts: tuple[str, ...]) -> str:
    tail = parts[1:]
    if len(tail) == 1 and "_" in tail[0]:
        head, *rest = tail[0].split("_")
        return head + "." + ".".join(rest)
    return ".".join(tail)


def _dict_literal_keys(node) -> set[str]:
    """String keys of a dict literal, e.g. **{"from": "a"} -> {"from"}.

    Used to credit **-unpacked parameters during validation; returns an empty
    set for anything that is not a literal dict of string keys.
    """
    if not isinstance(node, ast.Dict):
        return set()
    keys = set()
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
    return keys


def _keyword_literal_values(node) -> list[str] | None:
    """String values of a constant/list literal keyword, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split(",")
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[str] = []
        for element in node.elts:
            if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
                return None
            values.extend(element.value.split(","))
        return values
    return None


def _module_flag_names(doc) -> set[str]:
    names = set()
    for flag in getattr(doc, "flags", []) or []:
        if isinstance(flag, dict):
            name, generic = flag.get("flag", ""), bool(flag.get("generic", False))
        else:
            name, generic = getattr(flag, "flag", ""), bool(getattr(flag, "generic", False))
        if name and not generic:
            names.add(str(name))
    return names


def validate_api(
    code: str,
    retriever: GrassToolsRetriever,
    strict_options: bool | None = None,
    pipeline: str | None = None,
) -> list[str]:
    """Check tools.<method>(...) calls against real knowledge-base signatures.

    Returns a list of human-readable issues; an empty list means every call
    names a real tool with only valid parameters and all required ones.

    Closed-enum and flag validation is gated: it runs when ``strict_options``
    is true or the pipeline is ``manual-kb``/``planned``. The default (legacy,
    strict_options=False) is byte-for-byte the previous behavior.
    """
    if strict_options is None:
        strict = pipeline in ("manual-kb", "planned")
    else:
        strict = bool(strict_options) or pipeline in ("manual-kb", "planned")

    tree = ast.parse(code)
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts = _dotted_parts(node.func)
        if parts is None:
            continue
        if len(parts) > 2:
            method = ".".join(parts[1:])
            underscore_name = "_".join(parts[1:])
            issues.append(f"tools.{method}: dotted method call violates Rule 3; use underscore syntax (tools.{underscore_name})")
            continue
        method = ".".join(parts[1:])
        tool_name = _resolve_tool_name(parts)
        doc = retriever.get_tool(tool_name)
        if doc is None:
            issues.append(f"tools.{method}: unknown tool (no '{tool_name}' in knowledge base)")
            continue

        if node.args:
            issues.append(f"tools.{method}: positional argument(s) used; pass parameters as keyword arguments")

        positional_names = list(doc.params)
        provided = set(positional_names[: len(node.args)])
        unknown = []
        for keyword in node.keywords:
            if keyword.arg is None:
                # **kwargs / **mapping: the keys are only knowable from the
                # literal. Needed because GRASS params like v.distance's
                # `from` are Python keywords and must be passed this way.
                provided |= _dict_literal_keys(keyword.value)
            else:
                provided.add(keyword.arg)
                if keyword.arg not in doc.params and not (
                    strict and keyword.arg in SYNTHETIC_FLAG_PARAMS
                ):
                    unknown.append(keyword.arg)
        if unknown:
            issues.append(f"tools.{method}: unknown parameter(s): {', '.join(unknown)} (valid: {', '.join(doc.params)})")
        required = [p for p, info in doc.params.items() if info.get("required")]
        missing = [p for p in required if p not in provided]
        if missing:
            issues.append(f"tools.{method}: missing required parameter(s): {', '.join(missing)}")

        if not strict:
            continue

        # ---- strict, new-mode-only checks
        known_flags = _module_flag_names(doc)
        options = getattr(doc, "options", {}) or {}
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            if keyword.arg == "flags" and known_flags:
                values = _keyword_literal_values(keyword.value)
                if values is not None:
                    invalid = [
                        char
                        for value in values
                        for char in value.strip()
                        if char and char not in known_flags
                    ]
                    if invalid:
                        issues.append(
                            f"tools.{method}: invalid flag(s) for 'flags': "
                            f"{', '.join(sorted(set(invalid)))} "
                            f"(allowed: {', '.join(sorted(known_flags))})"
                        )
            if keyword.arg in options:
                allowed = []
                for entry in options[keyword.arg]:
                    value = entry.get("value") if isinstance(entry, dict) else getattr(entry, "value", "")
                    if value:
                        allowed.append(str(value))
                if not allowed:
                    continue
                values = _keyword_literal_values(keyword.value)
                if values is None:
                    # Free-form value (expression, variable, file path): the
                    # manual does not constrain it statically.
                    continue
                invalid = [value.strip() for value in values if value.strip() and value.strip() not in allowed]
                if invalid:
                    issues.append(
                        f"tools.{method}: invalid value(s) for '{keyword.arg}': "
                        f"{', '.join(invalid)} (allowed: {', '.join(allowed)})"
                    )
    return issues

