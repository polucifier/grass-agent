import argparse
import json
import sys
import ast
from pathlib import Path

# Add parent directory to sys.path to import modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever
from code_generator import GrassCodeGenerator, validate_syntax, _dotted_parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run curated benchmark evaluation suite for GRASS script generation.")
    parser.add_argument("--model", default="qwen2.5-coder:3b", help="Ollama model to evaluate (e.g. qwen2.5-coder:3b or qwen2.5-coder:7b)")
    parser.add_argument("--benchmarks", default="benchmarks/benchmark_prompts.json", help="Path to benchmark JSON file")
    args = parser.parse_args()

    benchmarks_path = Path(args.benchmarks)
    if not benchmarks_path.exists():
        print(f"Error: Benchmark file not found at {benchmarks_path}", file=sys.stderr)
        return 1

    data = json.loads(benchmarks_path.read_text())
    test_cases = data.get("test_cases", [])
    print(f"Loaded {len(test_cases)} benchmark test cases. Evaluating model: {args.model}")

    config = GenerationConfig.from_env()
    config.model = args.model

    provider = OllamaProvider(config)
    retriever = GrassToolsRetriever(config.rag_db_path)
    generator = GrassCodeGenerator(config, provider, retriever)

    passed = 0
    failed = 0

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    model_slug = args.model.replace(":", "_")

    for tc in test_cases:
        tc_id = tc["id"]
        category = tc["category"]
        prompt = tc["prompt"]
        print(f"\n--- Running [{tc_id}] ({category}): \"{prompt}\" ---", flush=True)
        output_path = output_dir / f"{tc_id}_{model_slug}.py"
        code = None
        try:
            code = generator.generate(prompt)

            # 1. Syntax validation via ast.parse
            validate_syntax(code)
            
            # 2. Zero-chat compliance check (must start with import, ignoring leading comment lines)
            lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
            if not lines or not lines[0].startswith("from grass.tools import Tools"):
                raise ValueError("Zero-chat violation: Generated code does not start with 'from grass.tools import Tools'")
            
            # 3. Check for markdown fences or stray prose
            if "```" in code:
                raise ValueError("Zero-chat violation: Markdown fences found in generated code")

            # 4. Check API issues from generator
            if generator.api_issues:
                raise ValueError(f"API validation issues: {'; '.join(generator.api_issues)}")

            # 5. Check expected tools
            expected_tools = tc.get("expected_tools", [])
            if expected_tools:
                called_tools = []
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        parts = _dotted_parts(node.func)
                        if parts and len(parts) == 2 and parts[0] == "tools":
                            called_tools.append(parts[1])
                
                for expected_item in expected_tools:
                    if isinstance(expected_item, list):
                        matched = any(alt.replace(".", "_") in called_tools for alt in expected_item)
                        if not matched:
                            raise ValueError(f"Tool mismatch: expected one of {expected_item} to be called, but none were in {called_tools}")
                    else:
                        expected_method = expected_item.replace(".", "_")
                        if expected_method not in called_tools:
                            raise ValueError(f"Tool mismatch: expected tool '{expected_item}' (method tools.{expected_method}) was not called in generated script (called tools: {called_tools})")

            print(f"✓ [{tc_id}] PASSED (Syntax valid, zero-chat compliant)", flush=True)
            passed += 1
        except Exception as e:
            print(f"✗ [{tc_id}] FAILED: {e}", flush=True)
            failed += 1
        finally:
            header = ""
            try:
                header = generator.format_debug_header()
            except Exception:
                pass

            if code is not None:
                output_path.write_text(f"{header}\n{code.rstrip()}\n" if header else f"{code.rstrip()}\n")
            else:
                fail_msg = f"# Generation failed for {tc_id}: no code produced\n"
                output_path.write_text(f"{header}\n{fail_msg}" if header else fail_msg)
            print(f"  -> saved: {output_path}", flush=True)

    retriever.close()

    print(f"\n==============================")
    print(f"Benchmark Results for {args.model}:")
    print(f"Total: {len(test_cases)} | Passed: {passed} | Failed: {failed}")
    print(f"==============================")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
