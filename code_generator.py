import ast
import re

from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever

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
5. Include every numeric value from the task (distances, resolutions, thresholds) as an
   actual parameter value, not a placeholder.
6. Coordinate pairs (x,y) and bounding box extents (n,s,e,w) MUST be passed as comma-separated string literals (e.g. "635000,216500" or "0,10,0,10").
7. For multi-step tasks, chain multiple tool calls sequentially, assigning intermediate raster or vector outputs to variables and passing them as input parameters to subsequent tools.
8. Output ONLY executable Python code. No conversational text, no explanations, and no markdown fences.
"""


CANONICAL_EXAMPLES = {
    "r.mapcalc": 'tools.r_mapcalc(expression="elevation_double = elevation * 2")',
    "r.mapcalc.simple": 'tools.r_mapcalc_simple(expression="A * 2", a="elevation", output="elevation_double")',
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


class GrassCodeGenerator:

    def __init__(self, config: GenerationConfig, provider: OllamaProvider, retriever: GrassToolsRetriever):
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.api_issues: list[str] = []
        self.last_retrieved_docs: list = []
        self.last_system_prompt: str = ""
        self.last_user_message: str = ""
        self.last_request: str = ""

    def generate(self, request: str) -> str:
        self.last_request = request
        query_embedding = self.provider.generate_embeddings(request)
        docs = self.retriever.retrieve(request, query_embedding, k=self.config.rag_top_k)
        self.last_retrieved_docs = docs

        context = format_context(docs)
        user_message = (
            f"Relevant GRASS tools documentation:\n\n{context}\n\n"
            f"Task: {request}\n\nGenerate the Python script:"
        )
        self.last_system_prompt = SYSTEM_PROMPT
        self.last_user_message = user_message

        response = self.provider.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ])

        code = extract_python_code(response)
        code = normalize_dotted_calls(code)
        validate_syntax(code)
        self.api_issues = validate_api(code, self.retriever)
        return code

    def format_debug_header(self) -> str:
        doc_lines = []
        for doc in self.last_retrieved_docs:
            doc_lines.append(f"#   - {doc.name}: {doc.description}")
            if doc.signature:
                doc_lines.append(f"#     Signature: {doc.signature}")
        docs_str = "\n".join(doc_lines) if doc_lines else "#   (None)"

        sys_lines = "\n".join(f"# {line}" for line in self.last_system_prompt.splitlines())
        user_lines = "\n".join(f"# {line}" for line in self.last_user_message.splitlines())

        return f"""# ==============================================================================
# DEBUG: RAG RETRIEVAL & LLM PROMPT
# ==============================================================================
# Task: {self.last_request}
# Retrieved RAG Tools:
{docs_str}
# ------------------------------------------------------------------------------
# System Prompt:
{sys_lines}
# ------------------------------------------------------------------------------
# User Message Sent to LLM:
{user_lines}
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


def validate_api(code: str, retriever: GrassToolsRetriever) -> list[str]:
    """Check tools.<method>(...) calls against real knowledge-base signatures.

    Returns a list of human-readable issues; an empty list means every call
    names a real tool with only valid parameters and all required ones.
    """
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
        provided = set(positional_names[: len(node.args)]) | {a.arg for a in node.keywords}
        unknown = [a.arg for a in node.keywords if a.arg and a.arg not in doc.params]
        if unknown:
            issues.append(f"tools.{method}: unknown parameter(s): {', '.join(unknown)} (valid: {', '.join(doc.params)})")
        required = [p for p, info in doc.params.items() if info.get("required")]
        missing = [p for p in required if p not in provided]
        if missing:
            issues.append(f"tools.{method}: missing required parameter(s): {', '.join(missing)}")
    return issues
