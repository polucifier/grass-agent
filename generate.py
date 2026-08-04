import argparse
import re
import sys
from pathlib import Path

from code_generator import GrassCodeGenerator
from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever


def default_output_path(config: GenerationConfig, request: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", request.lower()).strip("_") or "script"
    return Path(config.output_dir) / f"{slug}.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate grass.tools Python code from a natural language request.")
    parser.add_argument("request", help="Natural language description of the GRASS task")
    parser.add_argument("-o", "--output", default=None, help="Output file path (default: generated/<slug>.py)")
    parser.add_argument("--model", default=None, help="Override the Ollama model")
    parser.add_argument("--print", dest="print_only", action="store_true", help="Print code to stdout instead of writing a file")
    args = parser.parse_args()

    config = GenerationConfig.from_env()
    if args.model:
        config.model = args.model

    provider = OllamaProvider(config)
    retriever = GrassToolsRetriever(config.rag_db_path)
    generator = GrassCodeGenerator(config, provider, retriever)

    print(f"Generating grass.tools code for: {args.request}")
    try:
        code = generator.generate(args.request)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if generator.api_issues:
        print("API validation warnings:")
        for issue in generator.api_issues:
            print(f"  ! {issue}")

    if args.print_only:
        print(code)
        return 0

    output = Path(args.output) if args.output else default_output_path(config, args.request)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(code)
    print(f"Generated: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
