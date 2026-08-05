import ast
import re

from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever

SYSTEM_PROMPT = """You are a GRASS GIS expert. Generate a Python script that uses the
grass.tools API (GRASS 8.5+).

Rules:
- Start the script exactly like this:
  from grass.tools import Tools
  tools = Tools(overwrite=True)
- Do NOT assign attributes on the tools object (e.g. never write "tools.overwrite = ...").
- Tool names become methods with underscores instead of dots: r.slope.aspect -> tools.r_slope_aspect.
  Always use underscore methods (tools.v_buffer). NEVER write dotted method chains
  such as tools.v.buffer(...) or tools.r.stats.mean(...) - that is invalid.
- Pass all parameters as keyword arguments. Use the signatures from the context below.
- Include every numeric value from the task (distances, resolutions, thresholds) as an
  actual parameter value, not a placeholder.
- Choose raster tools (r.*) for tasks about raster/DEM data, and vector tools (v.*) for
  tasks about vector data (roads, rivers, buildings, polygons, lines, points).
- Use ONE tool call for the task. Do not add setup, cleanup, or intermediate steps
  (no creating grids, no rule files, no g.remove of helpers).
- Output ONLY the Python code. No explanations, no markdown fences.
"""


def format_context(docs) -> str:
    sections = []
    for doc in docs:
        parts = [f"### {doc.name}"]
        if doc.category:
            parts.append(f"Category: {doc.category}")
        parts.append(f"Description: {doc.description}")
        if doc.signature:
            parts.append(f"grass.tools signature: {doc.signature}")
        if doc.example:
            parts.append(f"Example:\n{doc.example}")
        if doc.params:
            required = [p for p, info in doc.params.items() if info.get("required")]
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

    def generate(self, request: str) -> str:
        query_embedding = self.provider.generate_embeddings(request)
        docs = self.retriever.retrieve(request, query_embedding, k=self.config.rag_top_k)

        context = format_context(docs)
        user_message = (
            f"Relevant GRASS tools documentation:\n\n{context}\n\n"
            f"Task: {request}\n\nGenerate the Python script:"
        )

        response = self.provider.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ])

        code = extract_python_code(response)
        validate_syntax(code)
        self.api_issues = validate_api(code, self.retriever)
        return code


def extract_python_code(text: str) -> str:
    fence = re.search(r"```(?:python)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
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
        method = ".".join(parts[1:])
        tool_name = _resolve_tool_name(parts)
        doc = retriever.get_tool(tool_name)
        if doc is None:
            issues.append(f"tools.{method}: unknown tool (no '{tool_name}' in knowledge base)")
            continue
        if len(parts) > 2:
            issues.append(
                f"tools.{method}: dotted method chain is invalid - use tools.{tool_name.replace('.', '_')}(...) "
                f"instead of tools.{method}(...)"
            )

        if node.args:
            issues.append(f"tools.{method}: positional argument(s) used; pass parameters as keyword arguments")

        positional_names = list(doc.params)
        provided = set(positional_names[: len(node.args)]) | {a.arg for a in node.keywords if a.arg is not None}
        unknown = [a.arg for a in node.keywords if a.arg is not None and a.arg not in doc.params]
        if unknown:
            issues.append(f"tools.{method}: unknown parameter(s): {', '.join(unknown)} (valid: {', '.join(doc.params)})")
        if any(a.arg is None for a in node.keywords):
            issues.append(f"tools.{method}: **kwargs expansion used; pass parameters as explicit keyword arguments")
        required = [p for p, info in doc.params.items() if info.get("required")]
        missing = [p for p in required if p not in provided]
        if missing:
            issues.append(f"tools.{method}: missing required parameter(s): {', '.join(missing)}")
    return issues
