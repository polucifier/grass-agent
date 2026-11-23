"""Planned-mode orchestration: shortlist → plan → cards → synthesis.

The manual is authoritative over the plan. Planner JSON never reaches the
final script: the synthesizer sees a compact advisory plan plus the per-step
manual cards and emits executable ``grass.tools`` Python through the existing
zero-chat extractor.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from code_generator import (
    AGENTIC_SYSTEM_PROMPT,
    PipelineGenerationResult,
    extract_python_code,
    normalize_dotted_calls,
    validate_api,
    validate_syntax,
)
from grass_agent.manual_context import ManualBudgetExceeded, render_manual_cards
from grass_agent.planner import Planner, PlannerOutcome
from rag_retriever import family_alternatives, family_note


class AgenticPipeline:
    """Orchestrates the candidate-constrained planned pipeline."""

    def __init__(
        self,
        config,
        provider,
        retriever,
        generator=None,
        planner: Planner | None = None,
        manual_renderer=None,
    ):
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.generator = generator
        self.planner = planner or Planner(
            provider,
            model=getattr(config, "planner_model", None) or getattr(config, "model", None),
            timeout=getattr(config, "planner_timeout", 60),
            retriever=retriever,
        )
        self.manual_renderer = manual_renderer or render_manual_cards
        self.last_system_prompt = ""
        self.last_user_message = ""
        self.last_response = ""
        self.last_shortlist = []
        self.last_plan_outcome: PlannerOutcome | None = None

    # ------------------------------------------------------------------ API
    def generate(
        self,
        request: str,
        inventory_block: str = "",
        inventory_maps=None,
    ) -> PipelineGenerationResult:
        embedding = self.provider.generate_embeddings(request)
        shortlist = self.retriever.retrieve_shortlist(
            request,
            embedding,
            shortlist_k=getattr(self.config, "shortlist_k", 12),
            embedding_model=getattr(self.config, "embedding_model", ""),
        )
        self.last_shortlist = shortlist.candidates

        if not shortlist.candidates:
            # Zero candidates force the manual-kb fallback.
            return self._fallback(
                request,
                inventory_block,
                shortlist.names,
                reason="empty shortlist",
            )

        outcome = self.planner.create_plan(
            request,
            inventory_block,
            shortlist.candidates,
            inventory_maps=inventory_maps,
        )
        self.last_plan_outcome = outcome
        if outcome.fallback or not outcome.valid:
            return self._fallback(
                request,
                inventory_block,
                shortlist.names,
                reason="plan invalid after one repair",
                outcome=outcome,
            )

        return self._synthesize_plan(
            request,
            inventory_block,
            shortlist.candidates,
            outcome,
            inventory_maps=inventory_maps,
        )

    def synthesize_plan(
        self,
        request: str,
        inventory_block: str,
        shortlist,
        outcome: PlannerOutcome,
        inventory_maps=None,
    ) -> PipelineGenerationResult:
        """Public entry for a constrained re-plan repair candidate."""
        return self._synthesize_plan(
            request,
            inventory_block,
            shortlist,
            outcome,
            inventory_maps=inventory_maps,
        )

    # ------------------------------------------------------------- internals
    def _fallback(
        self,
        request: str,
        inventory_block: str,
        shortlist_names: list[str],
        reason: str = "",
        outcome: PlannerOutcome | None = None,
    ) -> PipelineGenerationResult:
        if self.generator is not None:
            result = self.generator._generate_manual_kb(
                request,
                inventory_block=inventory_block,
                manual_renderer=self.manual_renderer,
            )
        else:  # pragma: no cover - defensive; the harness always supplies one
            result = PipelineGenerationResult(code="")
        result.plan_fallback = True
        result.shortlist = list(shortlist_names)
        result.shortlist_shortfall = len(shortlist_names) < 8
        if outcome is not None:
            result.plan_repair_count = outcome.plan_repair_count
            result.planner_invocations = outcome.invocations
            result.planner_prompt_tokens = outcome.prompt_tokens
            result.planner_completion_tokens = outcome.completion_tokens
        return result

    def _records_for_plan(self, outcome: PlannerOutcome):
        records = []
        alternatives: dict[str, list] = {}
        for step in outcome.plan.steps:
            record = self.retriever.get_manual(step.tool)
            if record is None:
                record = self.retriever.get_tool(step.tool)
            if record is None:
                continue
            if all(existing.name != record.name for existing in records):
                records.append(record)
                alternatives[record.name] = [
                    {
                        "name": alternative.name,
                        "note": family_note(alternative.name),
                    }
                    for alternative in family_alternatives(
                        record.name, self.retriever, limit=2
                    )
                ]
        return records, alternatives

    def _synthesize_plan(
        self,
        request: str,
        inventory_block: str,
        shortlist,
        outcome: PlannerOutcome,
        inventory_maps=None,
    ) -> PipelineGenerationResult:
        records, alternatives = self._records_for_plan(outcome)
        budget = getattr(self.config, "manual_context_tokens", None)
        if budget is None:
            budget = int(0.45 * getattr(self.config, "num_ctx", 8192))
        rendered = self.manual_renderer(
            records,
            budget=budget,
            num_ctx=getattr(self.config, "num_ctx", 8192),
            alternatives=alternatives,
        )
        plan_text = _render_plan(outcome.plan)
        grounding = f"{inventory_block}\n\n" if (inventory_block or "").strip() else ""
        user_message = (
            f"Task: {request}\n\n"
            f"### Plan (advisory; the manual cards are authoritative)\n\n"
            f"{plan_text}\n\n"
            f"### Manual cards (authoritative)\n\n{rendered.text}\n\n"
            f"{grounding}"
            "Generate the complete Python script:"
        )
        self.last_system_prompt = AGENTIC_SYSTEM_PROMPT
        self.last_user_message = user_message

        response = self.provider.chat(
            [
                {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )
        self.last_response = response
        code = normalize_dotted_calls(extract_python_code(response))
        validate_syntax(code)
        issues = validate_api(
            code, self.retriever, strict_options=True, pipeline="planned"
        )
        stats = getattr(self.provider, "last_stats", None) or {}
        return PipelineGenerationResult(
            code=code,
            prompt_tokens=int(stats.get("prompt_tokens", 0) or 0),
            completion_tokens=int(stats.get("completion_tokens", 0) or 0),
            plan=outcome.plan,
            plan_fallback=False,
            plan_repair_count=outcome.plan_repair_count,
            replan_count=outcome.replan_count,
            planner_invocations=outcome.invocations,
            shortlist_shortfall=len(shortlist) < 8,
            manual_cards=list(rendered.cards),
            manual_tokens=rendered.tokens,
            manual_omissions=list(rendered.omissions),
            tool_swaps=_detect_tool_swaps(code, outcome.plan.tools),
            planner_prompt_tokens=outcome.prompt_tokens,
            planner_completion_tokens=outcome.completion_tokens,
            retrieved_docs=list(records),
            shortlist=[candidate.name for candidate in shortlist],
            plan_validation=outcome.validation.to_dict(),
            planned_tools=list(outcome.plan.tools),
        )


def _render_plan(plan) -> str:
    lines = []
    revision = getattr(plan, "revision", 0)
    lines.append(f"revision: {revision}")
    for step in getattr(plan, "steps", []):
        lines.append(
            f"{step.id}. {step.tool} — {step.intent} "
            f"(inputs: {', '.join(step.inputs) or '—'}; "
            f"outputs: {', '.join(step.outputs) or '—'})"
        )
    return "\n".join(lines)


def _tool_calls(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name) and target.id == "tools" and parts:
            tail = list(reversed(parts))
            if len(tail) == 1 and "_" in tail[0]:
                names.append(tail[0].replace("_", ".", 1))
            else:
                names.append(".".join(tail))
    return names


def _detect_tool_swaps(code: str, planned_tools: list[str]) -> list[str]:
    """Record documented substitutions visible in the generated code."""
    actual = set(_tool_calls(code))
    swaps: list[str] = []
    for planned in planned_tools:
        if planned in actual:
            continue
        alternatives = [
            member
            for member in _family_members(planned)
            if member in actual and member != planned
        ]
        if alternatives:
            swaps.append(f"{planned} -> {alternatives[0]}")
    return swaps


def _family_members(tool: str) -> list[str]:
    from rag_retriever import TOOL_FAMILIES, tool_family

    family = tool_family(tool)
    if family is None:
        return []
    return list(TOOL_FAMILIES[family])
