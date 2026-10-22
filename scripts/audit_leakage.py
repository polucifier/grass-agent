#!/usr/bin/env python3
"""Audit benchmark prompts for contamination against the GRASS knowledge base.

The retrieval corpus and the benchmark prompts were written by the same hand,
so the obvious failure mode is that a prompt accidentally reproduces a tool's
documentation, and the retrieval score then measures memorisation rather than
retrieval. This tool quantifies that risk for every test case.

Three signals are computed per case:

  1. Token Jaccard similarity on content words (stop words removed) of the
     prompt against (a) the descriptions of its own expected tools and
     (b) the single best-matching description out of all 543 in the corpus.
  2. Exact 3-gram and 4-gram phrase matches between the prompt and every
     tool's description and example.
  3. A verdict that separates legitimate shared *domain vocabulary* ("buffer",
     "elevation", "slope") from actual *task recipe* leakage, since a prompt
     that asks for a buffer is supposed to share the word "buffer" with
     v.buffer. That distinction is the whole point of the audit, so a high
     Jaccard score alone is deliberately not enough to raise a leak.

Run standalone:

    python scripts/audit_leakage.py
    python scripts/audit_leakage.py --threshold 0.5 --output /tmp/leak.md
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "grass_knowledge.db"
DEFAULT_SUITES = [
    REPO_ROOT / "benchmarks" / "benchmark_prompts_tier1.json",
    REPO_ROOT / "benchmarks" / "benchmark_prompts_tier2.json",
]
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks" / "leakage_report.md"
DEFAULT_THRESHOLD = 0.35

NGRAM_SIZES = (3, 4)
MAX_PHRASE_N = 6

WORD_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at
be because been before being below between both but by
can cannot could
did do does doing down during
each few for from further
had has have having he her here hers herself him himself his how
i if in into is it its itself
just
me more most my myself
no nor not now
of off on once only or other otherwise ought our ours ourselves out over own
same she should so some such
than that the their theirs them themselves then there these they this those
through to too
under until up upon us using
very
was we were what when where whether which while who whom why will with within
without toward towards among per via
you your yours yourself yourselves
""".split())


def phrase_tokens(text: str) -> tuple[str, ...]:
    """Lowercase alphanumeric tokens with stop words intact.

    Used for n-gram matching, where the unit of evidence is a contiguous run
    of words and dropping stop words would fabricate phrases that never
    appeared in the text.
    """
    return tuple(WORD_RE.findall(text.lower()))


def content_tokens(text: str) -> frozenset[str]:
    """Stop-word-free token set, used for Jaccard similarity."""
    return frozenset(t for t in WORD_RE.findall(text.lower()) if t not in STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity |A n B| / |A u B| of two token sets."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def ngram_set(tokens: tuple[str, ...], n: int) -> frozenset[tuple[str, ...]]:
    return frozenset(tokens[i:i + n] for i in range(len(tokens) - n + 1))


def longest_shared_phrase(
    prompt_ngrams: dict[int, frozenset[tuple[str, ...]]],
    tool_ngrams: dict[int, frozenset[tuple[str, ...]]],
) -> tuple[int, tuple[str, ...]]:
    """Longest verbatim run of words shared by the prompt and one tool text."""
    for n in range(MAX_PHRASE_N, 2, -1):
        shared = prompt_ngrams[n] & tool_ngrams[n]
        if shared:
            return n, max(shared, key=lambda g: (-len(g), g))
    return 0, ()


def flatten_expected(expected_tools) -> list[str]:
    """Flatten expected_tools, whose items are names or lists of alternatives."""
    names: list[str] = []
    for item in expected_tools or []:
        if isinstance(item, (list, tuple)):
            names.extend(str(x) for x in item)
        else:
            names.append(str(item))
    return names


@dataclass
class ToolIndex:
    """Pre-tokenised knowledge base, so the audit stays O(cases x tools)."""

    names: list[str]
    descriptions: list[str]
    content: list[frozenset[str]]
    ngrams: list[dict[int, frozenset[tuple[str, ...]]]]
    doc_freq: dict[str, int]
    by_name: dict[str, int]

    @classmethod
    def load(cls, db_path: Path) -> "ToolIndex":
        names: list[str] = []
        descriptions: list[str] = []
        content: list[frozenset[str]] = []
        ngrams: list[dict[int, frozenset[tuple[str, ...]]]] = []
        doc_freq: dict[str, int] = {}

        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT name, description, example FROM tools ORDER BY name"
            ).fetchall()
        finally:
            con.close()

        for name, description, example in rows:
            description = description or ""
            toks = content_tokens(description)
            if example:
                toks = toks | content_tokens(example)
            text_tokens = phrase_tokens(f"{description} {example or ''}")

            names.append(name)
            descriptions.append(description)
            content.append(toks)
            ngrams.append({n: ngram_set(text_tokens, n) for n in range(2, MAX_PHRASE_N + 1)})
            for token in toks:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        return cls(
            names=names,
            descriptions=descriptions,
            content=content,
            ngrams=ngrams,
            doc_freq=doc_freq,
            by_name={n: i for i, n in enumerate(names)},
        )

    def __len__(self) -> int:
        return len(self.names)

    MIN_PHRASE_TOKENS = 3
    MIN_PHRASE_CONTENT = 3
    GENERIC_DF_FRACTION = 0.10

    def is_specific(self, phrase) -> bool:
        """True when a shared phrase is too rare to be ordinary domain wording.

        Two tests, because neither alone is sufficient.

        *Content weight.* At least three content words. The corpus document
        frequency cannot carry this test on its own: its 543 descriptions are
        terse one-liners, so everyday GIS wording looks rare inside it. `cost`
        occurs in five descriptions and `table` in thirty-four, yet "least
        cost" and "attribute table" are standard parlance, not copied text.
        Requiring three content words separates them from a lifted fragment
        like "regularized spline with tension".

        *Corpus rarity.* Every content word must still be infrequent. This
        rejects "elevation raster map", which has three content words but
        means nothing beyond the vocabulary that `raster` (40% of the corpus)
        and `map` (45%) already give it.

        Both tests are deliberately conservative: under-reporting a leak is
        recoverable, crying wolf on a benchmark audit is not.
        """
        content = [t for t in phrase if t not in STOPWORDS]
        if len(content) < self.MIN_PHRASE_CONTENT:
            return False
        cutoff = self.GENERIC_DF_FRACTION * len(self)
        return all(self.doc_freq.get(t, 0) <= cutoff for t in content)

    def rare(self, tokens) -> list[str]:
        """Tokens specific enough to carry signal rather than domain vocabulary."""
        cutoff = max(2, round(0.005 * len(self)))
        return sorted(t for t in tokens if self.doc_freq.get(t, 0) <= cutoff)


def classify(jaccard_expected, jaccard_max, evidence_phrase, rare_shared, threshold):
    """CLEAN unless the overlap looks like a copied task recipe rather than vocabulary.

    A prompt naming a domain concept it legitimately needs ("buffer" for
    v.buffer) will always share vocabulary with that tool, so similarity alone
    cannot convict. Two independent signals can:

      * a verbatim phrase of three or more words whose content words are all
        infrequent in the corpus, i.e. text lifted from a description rather
        than shared terminology;
      * a similarity above threshold corroborated by two or more
        corpus-rare shared terms.

    The phrase signal deliberately is not gated on the similarity threshold.
    Jaccard is length-sensitive and dilutes exactly the case that matters: a
    short prompt quoting one fragment of a long description scores low because
    the union is dominated by the description's other words.
    """
    score = max(jaccard_expected, jaccard_max)
    if evidence_phrase:
        words = " ".join(evidence_phrase)
        return ("POTENTIAL_LEAK",
                f"{len(evidence_phrase)}-word verbatim phrase shared with corpus: "
                f"“{words}”")
    if score > threshold and len(rare_shared) >= 2:
        return "POTENTIAL_LEAK", (
            f"similarity {score:.3f} > {threshold:.2f} with "
            f"{len(rare_shared)} corpus-rare shared terms: "
            f"{', '.join(rare_shared)}"
        )
    if score > threshold:
        return "CLEAN", (
            f"similarity {score:.3f} > {threshold:.2f}, but the overlap is "
            f"domain vocabulary only"
        )
    return "CLEAN", f"best Jaccard {score:.3f} <= {threshold:.2f}"


def audit_case(case: dict, tier: str, index: ToolIndex, threshold: float) -> dict:
    """Compute the full contamination profile for one test case."""
    prompt = case.get("prompt", "")
    p_content = content_tokens(prompt)
    p_ngrams = {n: ngram_set(phrase_tokens(prompt), n)
                for n in range(2, MAX_PHRASE_N + 1)}

    best_j, best_i = 0.0, -1
    for i, tool_content in enumerate(index.content):
        score = jaccard(p_content, tool_content)
        if score > best_j:
            best_j, best_i = score, i

    expected = flatten_expected(case.get("expected_tools"))
    exp_j, exp_i = 0.0, -1
    unresolved: list[str] = []
    for name in expected:
        i = index.by_name.get(name)
        if i is None:
            unresolved.append(name)
            continue
        score = jaccard(p_content, index.content[i])
        if exp_i < 0 or score > exp_j:
            exp_j, exp_i = score, i

    n3 = n4 = 0
    longest_len, longest_phrase, longest_tool = 0, (), None
    evidence_len, evidence_phrase, evidence_tool = 0, (), None
    for i, tool_ngrams in enumerate(index.ngrams):
        if p_ngrams[3] & tool_ngrams[3]:
            n3 += 1
        if p_ngrams[4] & tool_ngrams[4]:
            n4 += 1
        length, match = longest_shared_phrase(p_ngrams, tool_ngrams)
        if length > longest_len:
            longest_len, longest_phrase, longest_tool = length, match, index.names[i]
        if (length >= index.MIN_PHRASE_TOKENS and length > evidence_len
                and index.is_specific(match)):
            evidence_len, evidence_phrase, evidence_tool = length, match, index.names[i]

    shared = p_content & index.content[best_i] if best_i >= 0 else frozenset()
    rare_shared = index.rare(shared)
    verdict, reason = classify(exp_j, best_j, evidence_phrase, rare_shared, threshold)

    return {
        "id": case.get("id", "?"),
        "tier": tier,
        "category": case.get("category", ""),
        "prompt": prompt,
        "expected_tools": expected,
        "jaccard_expected": round(exp_j, 4),
        "jaccard_max": round(best_j, 4),
        "best_tool": index.names[best_i] if best_i >= 0 else "",
        "expected_tool": index.names[exp_i] if exp_i >= 0 else "",
        "expected_tool_known": exp_i >= 0,
        "unresolved_expected": unresolved,
        "shared_tokens": sorted(shared),
        "rare_shared": rare_shared,
        "ngram3_tools": n3,
        "ngram4_tools": n4,
        "longest_phrase_len": longest_len,
        "longest_phrase": " ".join(longest_phrase),
        "longest_phrase_tool": longest_tool or "",
        "evidence_phrase": " ".join(evidence_phrase),
        "evidence_tool": evidence_tool or "",
        "verdict": verdict,
        "reason": reason,
    }


def audit_all(suites, db_path, threshold=DEFAULT_THRESHOLD) -> tuple[list[dict], int]:
    """Audit every case in every suite. Returns (records, tool_count)."""
    index = ToolIndex.load(Path(db_path))
    records: list[dict] = []
    for suite in suites:
        suite = Path(suite)
        data = json.loads(suite.read_text(encoding="utf-8"))
        tier = Path(suite).stem.replace("benchmark_prompts_", "")
        for case in data.get("test_cases", []):
            records.append(audit_case(case, tier, index, threshold))
    return records, len(index)


def audit_suite(
    suite_path: str | Path,
    db_path: str | Path,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[dict]:
    """Return the test cases in one suite that warrant review.

    This is the entry point used by the pre-flight check in run_eval.py. It
    returns a case when its similarity exceeds `threshold` *or* when it is
    judged `POTENTIAL_LEAK`, which is a superset of the threshold crossing
    rather than a synonym for it. Filtering on the score alone would report a
    clean run while `tc_35` — the strongest verbatim phrase match in the
    suite, and the one case worth reviewing — was silently dropped, because
    its diluted Jaccard sits below the threshold.

    Each record's `flags` field says which test it failed, so a caller can
    distinguish a near miss from a confirmed verbatim match.
    """
    records, _ = audit_all([suite_path], db_path, threshold)
    flagged = []
    for r in records:
        score = max(r["jaccard_expected"], r["jaccard_max"])
        reasons = []
        if score > threshold:
            reasons.append("above_threshold")
        if r["verdict"] == "POTENTIAL_LEAK":
            reasons.append("verbatim_phrase" if r["evidence_phrase"] else "rare_terms")
        if reasons:
            r["flags"] = reasons
            r["score"] = score
            flagged.append(r)
    return flagged


def _excerpt(text: str, limit: int = 58) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt_ngram(rec: dict) -> str:
    if not rec["longest_phrase_len"]:
        return "—"
    return f"{rec['longest_phrase_len']}-gram “{rec['longest_phrase']}”"


def build_report(records, tool_count, threshold, suites) -> str:
    total = len(records)
    leaks = [r for r in records if r["verdict"] == "POTENTIAL_LEAK"]
    over = [r for r in records
            if max(r["jaccard_expected"], r["jaccard_max"]) > threshold]
    scores = [max(r["jaccard_expected"], r["jaccard_max"]) for r in records]
    mean = sum(scores) / total if total else 0.0
    top = max(records, key=lambda r: r["jaccard_max"], default=None)
    max_row = (f"| Maximum Jaccard similarity | {top['jaccard_max']:.3f} "
               f"(`{top['id']}` vs `{top['best_tool']}`) |"
               if top else "| Maximum Jaccard similarity | — |")
    cases3 = sum(1 for r in records if r["ngram3_tools"])
    cases4 = sum(1 for r in records if r["ngram4_tools"])
    hits3 = sum(r["ngram3_tools"] for r in records)
    hits4 = sum(r["ngram4_tools"] for r in records)
    unknown = [r for r in records if r["unresolved_expected"]]

    verdict = (
        "POTENTIAL CONTAMINATION — investigate the flagged cases before "
        "quoting retrieval numbers."
        if leaks else
        "NO CONTAMINATION DETECTED — every case is explained by shared domain "
        "vocabulary rather than copied task recipes."
    )

    lines = [
        "# Benchmark Contamination Audit",
        "",
        f"Corpus: `data/grass_knowledge.db` ({tool_count} tool descriptions)  ",
        f"Suites: {', '.join(f'`{Path(s).name}`' for s in suites)}  ",
        f"Similarity threshold: **{threshold:.2f}**",
        "",
        "## Executive summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Test cases audited | {total} |",
        f"| Mean Jaccard similarity | {mean:.3f} |",
        max_row,
        f"| Cases above threshold | {len(over)} of {total} |",
        f"| Cases with a 3-gram match | {cases3} (total hits {hits3}) |",
        f"| Cases with a 4-gram match | {cases4} (total hits {hits4}) |",
        f"| Cases flagged POTENTIAL_LEAK | {len(leaks)} of {total} |",
        "",
        f"**Overall verdict: {verdict}**",
        "",
        "## Top overlaps",
        "",
        "Ranked by Jaccard similarity against the single most similar tool "
        "description in the corpus.",
        "",
        "| Test ID | Prompt excerpt | Most similar tool | Jaccard | Max n-gram match | Verdict |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for r in sorted(records, key=lambda r: r["jaccard_max"], reverse=True)[:10]:
        lines.append(
            f"| `{r['id']}` | {_excerpt(r['prompt'])} | `{r['best_tool']}` | "
            f"{r['jaccard_max']:.3f} | {_fmt_ngram(r)} | {r['verdict']} |"
        )

    if leaks:
        lines += [
            "",
            "### Flagged cases",
            "",
            "Each of these needs a human decision. A shared phrase may still "
            "be unavoidable if the prompt legitimately describes the very "
            "algorithm its expected tool implements, but the case should be "
            "confirmed as non-trivial before its score is quoted.",
            "",
            "| Test ID | Jaccard | Evidence | Expected tool | Verdict |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in sorted(leaks, key=lambda r: -r["jaccard_max"]):
            ev = f"“{r['evidence_phrase']}” (`{r['evidence_tool']}`)" \
                if r["evidence_phrase"] else \
                ", ".join(f"`{t}`" for t in r["rare_shared"]) or "—"
            exp = ", ".join(f"`{t}`" for t in r["expected_tools"]) or "—"
            lines.append(
                f"| `{r['id']}` | {r['jaccard_max']:.3f} | {ev} | {exp} | "
                f"{r['verdict']} |"
            )

    near = [r for r in records
            if r["verdict"] == "CLEAN" and r in over]
    if near:
        lines += [
            "",
            "### Above threshold, judged clean",
            "",
            "These score above the threshold yet are explained by domain "
            "vocabulary rather than a copied recipe. They are listed "
            "explicitly so that the judgement can be checked.",
            "",
            "| Test ID | Jaccard | Most similar tool | Shared tokens | Why it is clean |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in sorted(near, key=lambda r: -r["jaccard_max"]):
            shared = ", ".join(f"`{t}`" for t in r["shared_tokens"]) or "—"
            lines.append(
                f"| `{r['id']}` | {r['jaccard_max']:.3f} | `{r['best_tool']}` | "
                f"{shared} | {r['reason']} |"
            )

    if unknown:
        lines += [
            "",
            "### Unresolved expected tools",
            "",
            "These name a tool that is absent from the knowledge base, so the "
            "expected-tool comparison could not be made: "
            + ", ".join(f"`{r['id']}` ({', '.join(r['unresolved_expected'])})"
                        for r in unknown),
        ]

    lines += [
        "",
        "## Methodological note",
        "",
        "Two different kinds of overlap are being measured here, and only one "
        "of them is a problem.",
        "",
        "**Expected domain vocabulary.** A prompt asking for a 200-metre buffer "
        "*must* share the token `buffer` with `v.buffer`, and a slope prompt "
        "*must* share `slope` with `r.slope`. This is the retrieval task working "
        "as intended: the query is supposed to use the same domain language as "
        "the documentation. Single shared domain words are therefore expected "
        "and are not evidence of contamination.",
        "",
        "**Task recipe leakage.** The failure mode this audit exists to detect "
        "is different: a prompt that reproduces the *recipe* — a multi-word "
        "sequence of operations copied out of a tool description or example — "
        "so that a lexical or embedding retriever can match it almost perfectly "
        "without understanding anything. That inflates measured retrieval "
        "quality and would misstate the benchmark's difficulty.",
        "",
        "A case is flagged `POTENTIAL_LEAK` on one of two independent grounds, "
        "and neither of them is the similarity score on its own.",
        "",
        "1. **A verbatim, corpus-specific phrase.** Three or more consecutive "
        "words shared with a tool description or example, of which at least "
        "three are content words and all of those are infrequent in the "
        "corpus. Both conditions are needed. The content-word floor removes "
        "matches like \"maps from the\" and \"in the attribute table\", and "
        "the rarity test removes matches like \"elevation raster map\", whose "
        "words are ordinary even though they are three of them.",
        "2. **High similarity plus rare corroboration.** A Jaccard score above "
        "the threshold together with at least two corpus-rare shared terms.",
        "",
        "The phrase test is deliberately *not* gated on the similarity "
        "threshold. Jaccard is length-sensitive: a short prompt quoting one "
        "fragment of a long description scores low because the union is "
        "dominated by the description's other words. `tc_35` is the concrete "
        "case — it carries the strongest verbatim match in the suite yet "
        "scores only 0.174, and a threshold-first rule would have missed it.",
        "",
        "Two known limits are worth stating. Document frequency is measured "
        "over 543 terse one-liners, so it understates how ordinary a term is "
        "outside the corpus; that is why the content-word floor carries part "
        "of the load. And a flag is a prompt for review, not a finding: where "
        "a prompt legitimately describes the algorithm its expected tool "
        "implements, some phrase overlap is unavoidable and the case is not "
        "invalid. Both biases push towards under-reporting, which is the "
        "safer direction for a benchmark audit.",
        "",
        "Notes on the measures: Jaccard is computed on stop-word-free tokens, "
        "so function words do not inflate it, while n-gram matching keeps stop "
        "words so that a phrase match corresponds to words that were genuinely "
        "adjacent. A high Jaccard value is weak evidence on its own and should "
        "be read together with the n-gram column.",
        "",
        f"Generated by `scripts/audit_leakage.py`. Threshold {threshold:.2f}.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit benchmark prompts for leakage against the GRASS "
                    "knowledge base.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"Knowledge base SQLite file (default: {DEFAULT_DB})")
    parser.add_argument("--suites", nargs="+", default=[str(s) for s in DEFAULT_SUITES],
                        help="Benchmark suite JSON files to audit")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Markdown report path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Similarity threshold (default: {DEFAULT_THRESHOLD})")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: knowledge base not found at {db_path}", file=sys.stderr)
        return 1

    suites = [Path(s) for s in args.suites]
    missing = [s for s in suites if not s.exists()]
    if missing:
        for s in missing:
            print(f"Error: suite not found at {s}", file=sys.stderr)
        return 1

    records, tool_count = audit_all(suites, db_path, args.threshold)
    if not records:
        print("Error: no test cases found in the given suites", file=sys.stderr)
        return 1

    report = build_report(records, tool_count, args.threshold, suites)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    leaks = [r for r in records if r["verdict"] == "POTENTIAL_LEAK"]
    scores = [max(r["jaccard_expected"], r["jaccard_max"]) for r in records]
    print(f"Audited {len(records)} test cases against {tool_count} tool descriptions.")
    print(f"  mean Jaccard   : {sum(scores) / len(scores):.3f}")
    print(f"  max Jaccard    : {max(scores):.3f}")
    print(f"  above threshold: {sum(1 for r in records if max(r['jaccard_expected'], r['jaccard_max']) > args.threshold)}")
    print(f"  POTENTIAL_LEAK : {len(leaks)}")
    for r in leaks:
        print(f"      {r['id']}: {r['reason']}")
    print(f"  report         : {out_path}")
    print("Exit status reflects whether the report was produced, not the "
          "verdict; use run_eval.py --audit --audit-strict to gate a run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
