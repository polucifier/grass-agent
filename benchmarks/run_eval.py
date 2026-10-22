import argparse
import json
import sys
import ast
from pathlib import Path

# Add parent directory to sys.path to import modules
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import GenerationConfig
from llm_provider import OllamaProvider
from rag_retriever import GrassToolsRetriever
from code_generator import GrassCodeGenerator, validate_syntax, _dotted_parts


def run_contamination_audit(suite_path: Path, threshold: float, strict: bool) -> bool:
    """Pre-flight contamination check on a suite's prompts.

    Returns True when the run may proceed. A flagged prompt is reported but
    does not stop the evaluation unless --audit-strict was passed, because the
    audit is advisory: its job is to make sure a reported score is not quietly
    inflated by memorised text.
    """
    from scripts.audit_leakage import audit_suite

    print(f"\n--- Contamination audit (threshold {threshold:.2f}) ---", flush=True)
    try:
        flagged = audit_suite(suite_path, REPO_ROOT / "data" / "grass_knowledge.db",
                              threshold)
    except Exception as e:
        print(f"  ! audit could not run ({e}); continuing without it",
              file=sys.stderr, flush=True)
        return True

    if not flagged:
        print(f"  ✓ Benchmark contamination audit passed "
              f"(all prompts < {threshold:.2f})", flush=True)
        return True

    leaks = [r for r in flagged if r["verdict"] == "POTENTIAL_LEAK"]
    print(f"  ! {len(flagged)} prompt(s) warrant review "
          f"({len(leaks)} potential leak(s), "
          f"{len(flagged) - len(leaks)} above threshold only):", flush=True)
    for rec in sorted(flagged, key=lambda r: -r["score"]):
        print(f"      {rec['id']}: Jaccard {rec['score']:.3f} "
              f"(best tool {rec['best_tool']}) — {rec['verdict']} "
              f"[{', '.join(rec['flags'])}]", flush=True)
        print(f"          {rec['reason']}", flush=True)
    if leaks:
        print("    A verbatim or corroborated overlap may inflate the reported "
              "score; confirm the flagged cases are non-trivial before "
              "quoting them.", flush=True)
    else:
        print("    None were flagged as leaks; these exceed the similarity "
              "threshold on shared domain vocabulary alone.", flush=True)

    if strict:
        print("    Aborting: --audit-strict was requested.", flush=True)
        return False
    print("    Continuing evaluation (advisory only; pass --audit-strict to "
          "make this fatal).", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run curated benchmark evaluation suite for GRASS script generation.")
    parser.add_argument("--model", default="qwen2.5-coder:3b", help="Ollama model to evaluate (e.g. qwen2.5-coder:3b or qwen2.5-coder:7b)")
    parser.add_argument("-s", "--suite", default="benchmarks/benchmark_prompts_tier1.json",
                        help="Path to the benchmark JSON test suite file (default: benchmarks/benchmark_prompts_tier1.json)")
    parser.add_argument("--audit", action="store_true",
                        help="Audit the suite's prompts for contamination against the "
                             "knowledge base before running (advisory; does not abort)")
    parser.add_argument("--audit-threshold", type=float, default=0.35,
                        help="Similarity threshold for --audit (default: 0.35)")
    parser.add_argument("--audit-strict", action="store_true",
                        help="With --audit, abort the run if any prompt exceeds the "
                             "threshold")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    if not suite_path.exists():
        print(f"Error: Benchmark suite not found at {suite_path}", file=sys.stderr)
        return 1

    data = json.loads(suite_path.read_text())
    test_cases = data.get("test_cases", [])

    if args.audit and not run_contamination_audit(
            suite_path, args.audit_threshold, args.audit_strict):
        return 1

    print(f"Loaded {len(test_cases)} benchmark test cases from {suite_path}. Evaluating model: {args.model}")

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

            # Fall back to the code the generator extracted before it raised,
            # so a validation failure still saves the offending script.
            saved = code if code is not None else generator.last_code
            if saved:
                output_path.write_text(f"{header}\n{saved.rstrip()}\n" if header else f"{saved.rstrip()}\n")
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
