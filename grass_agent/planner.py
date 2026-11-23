"""Candidate-constrained JSON planner (Feature 004 Step B).

The planner is an internal workflow step: it sees only the retrieval
shortlist, returns JSON, and never appears in the final generated script.
Validation is strict and human-readable; an invalid plan or timeout gets one
pre-execution repair and then falls back to ``manual-kb`` with no tier charge.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
from dataclasses import dataclass, field

MAX_PLAN_STEPS = 5
DEFAULT_PLANNER_TIMEOUT = 60
MAX_PLANNER_INVOCATIONS = 3

# Tools whose output category is the opposite of their module prefix.
_OUTPUT_TYPE_OVERRIDES = {
    "r.to.vect": "vector",
    "r.contour": "vector",
    "r.stream.extract": "raster",  # raster streams, vector optional
    "v.to.rast": "raster",
    "r.drain": "raster",
    "v.surf.rst": "raster",
    "r.surf.rst": "raster",
    "r.what.rast": "raster",
    "v.out.ogr": "vector",
}

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


class PlannerTimeout(Exception):
    """The planner did not answer inside the configured timeout."""


class PlanParseError(ValueError):
    """The planner response is not a JSON object."""


@dataclass
class PlanStep:
    id: int
    intent: str
    tool: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intent": self.intent,
            "tool": self.tool,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "output_types": list(self.output_types),
            "constraints": list(self.constraints),
        }


@dataclass
class ExecutionPlan:
    steps: list[PlanStep] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    revision: int = 0
    plan_repair_count: int = 0
    replan_count: int = 0
    planner_invocations: int = 0
    raw_response_hash: str = ""
    fallback: bool = False

    @property
    def tools(self) -> list[str]:
        return [step.tool for step in self.steps]

    def to_dict(self) -> dict:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "assumptions": list(self.assumptions),
            "revision": self.revision,
            "plan_repair_count": self.plan_repair_count,
            "replan_count": self.replan_count,
            "planner_invocations": self.planner_invocations,
        }


@dataclass
class PlanValidation:
    ok: bool = True
    errors: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors)}


@dataclass
class PlannerOutcome:
    plan: ExecutionPlan | None = None
    validation: PlanValidation = field(default_factory=PlanValidation)
    invocations: int = 0
    plan_repair_count: int = 0
    replan_count: int = 0
    fallback: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: str = ""
    shortlist: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.plan is not None and self.validation.ok and not self.fallback

    def to_artifact(self) -> dict:
        return {
            "pipeline": "planned",
            "revision": (
                self.plan.revision if self.plan is not None else (1 if self.replan_count else 0)
            ),
            "plan_repair_count": self.plan_repair_count,
            "replan_count": self.replan_count,
            "planner_invocations": self.invocations,
            "fallback": self.fallback,
            "shortlist": list(self.shortlist),
            "shortlist_shortfall": len(self.shortlist) < 8,
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "validation": self.validation.to_dict(),
            "planner_prompt_tokens": self.prompt_tokens,
            "planner_completion_tokens": self.completion_tokens,
        }


def extract_json(text: str) -> dict:
    """Tolerantly extract the first JSON object from a model response."""
    if text is None:
        raise PlanParseError("planner returned no text")
    candidate = text.strip()
    fence = _JSON_FENCE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise PlanParseError(
                f"planner response is not JSON: {candidate[:160]!r}"
            ) from None
        try:
            payload = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PlanParseError(f"planner JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanParseError("planner JSON must be an object with 'steps'")
    return payload


def _plan_from_dict(payload: dict) -> ExecutionPlan:
    steps: list[PlanStep] = []
    for entry in payload.get("steps", []) or []:
        if not isinstance(entry, dict):
            raise PlanParseError("every plan step must be an object")
        steps.append(
            PlanStep(
                id=entry.get("id", 0),
                intent=str(entry.get("intent", "")),
                tool=str(entry.get("tool", "")),
                inputs=list(entry.get("inputs", []) or []),
                outputs=list(entry.get("outputs", []) or []),
                output_types=list(entry.get("output_types", []) or []),
                constraints=list(entry.get("constraints", []) or []),
            )
        )
    assumptions = [str(item) for item in payload.get("assumptions", []) or []]
    return ExecutionPlan(steps=steps, assumptions=assumptions)


def parse_plan(text: str) -> ExecutionPlan:
    """Parse a model response into an ExecutionPlan."""
    return _plan_from_dict(extract_json(text))


def expected_output_type(tool: str) -> str | None:
    if tool in _OUTPUT_TYPE_OVERRIDES:
        return _OUTPUT_TYPE_OVERRIDES[tool]
    if tool.startswith("r.") or tool.startswith("r3."):
        return "raster"
    if tool.startswith("v."):
        return "vector"
    return None


def validate_plan(
    plan,
    shortlist_names,
    inventory_maps=None,
    retriever=None,
) -> PlanValidation:
    """Validate an ExecutionPlan/dict against the shortlist and inventory."""
    validation = PlanValidation()
    if isinstance(plan, dict):
        try:
            plan = _plan_from_dict(plan)
        except PlanParseError as exc:
            validation.add(str(exc))
            return validation
    if plan is None:
        validation.add("no plan was produced")
        return validation

    steps = plan.steps
    if not steps:
        validation.add("plan has no steps")
        return validation
    if len(steps) > MAX_PLAN_STEPS:
        validation.add(f"plan has {len(steps)} steps; the maximum is {MAX_PLAN_STEPS}")

    shortlist = list(shortlist_names or [])
    inventory = set(inventory_maps or [])
    outputs_seen: set[str] = set()
    for index, step in enumerate(steps, start=1):
        label = f"step {step.id} ({step.tool or '?'})"
        if not isinstance(step.id, int) or isinstance(step.id, bool) or step.id != index:
            validation.add(
                f"{label}: ids must be 1-based and contiguous "
                f"(expected {index}, got {step.id!r})"
            )
        if not step.intent.strip():
            validation.add(f"{label}: intent is empty")
        if not step.tool:
            validation.add(f"{label}: tool is empty")
        elif shortlist and step.tool not in shortlist:
            validation.add(f"{label}: tool is not in the candidate shortlist")
        if retriever is not None and step.tool and retriever.get_tool(step.tool) is None:
            validation.add(f"{label}: tool does not exist in the knowledge base")

        if not step.inputs:
            validation.add(f"{label}: no inputs")
        if not step.outputs:
            validation.add(f"{label}: no outputs")
        if len(step.outputs) != len(step.output_types):
            validation.add(
                f"{label}: outputs ({len(step.outputs)}) and output_types "
                f"({len(step.output_types)}) differ in length"
            )
        for output in step.outputs:
            if not str(output).strip():
                validation.add(f"{label}: an output name is empty")
            elif output in outputs_seen:
                validation.add(f"{label}: duplicate output name {output!r}")
            else:
                outputs_seen.add(output)
        for value in step.output_types:
            if value not in ("raster", "vector"):
                validation.add(
                    f"{label}: output type {value!r} is not raster or vector"
                )
        expected = expected_output_type(step.tool)
        if expected is not None and step.output_types:
            incompatible = [value for value in step.output_types if value != expected]
            if incompatible:
                validation.add(
                    f"{label}: tool produces {expected} output but plan declares "
                    f"{', '.join(incompatible)}"
                )
        if inventory:
            for source in step.inputs:
                if source not in inventory and source not in outputs_seen:
                    validation.add(
                        f"{label}: input {source!r} has no lineage "
                        "(not an inventory map or earlier output)"
                    )
        outputs_seen.update(step.outputs)
    return validation


def _summarise_shortlist(shortlist) -> str:
    lines = []
    for candidate in shortlist:
        description = getattr(candidate, "description", "") or ""
        lines.append(f"- {candidate.name}: {description[:140]}")
    return "\n".join(lines)


PLANNER_SCHEMA = """{
  "steps": [
    {
      "id": 1,
      "intent": "atomic GIS action",
      "tool": "shortlisted.module",
      "inputs": ["map name"],
      "outputs": ["new map name"],
      "output_types": ["raster"],
      "constraints": []
    }
  ],
  "assumptions": []
}"""


def build_planner_prompt(
    task: str,
    inventory_block: str,
    shortlist,
    error: str = "",
    invalid_plan: str = "",
) -> str:
    repair = ""
    if error:
        repair = (
            "\nThe previous plan was rejected with this error:\n"
            f"{error}\n\n"
            f"Rejected plan:\n{invalid_plan}\n\n"
            "Return a corrected plan using only the shortlisted tools.\n"
        )
    return (
        "You are planning a GRASS GIS workflow. Return JSON only, with no "
        "Markdown fences and no prose.\n\n"
        f"Task: {task}\n\n"
        f"{inventory_block}\n\n"
        "Candidate tools (choose only from this list):\n"
        f"{_summarise_shortlist(shortlist)}\n\n"
        f"Schema:\n{PLANNER_SCHEMA}\n\n"
        f"Rules: 1-{MAX_PLAN_STEPS} steps, contiguous 1-based ids, one tool per "
        "step, distinct non-empty outputs, and every input must be an inventory "
        "map or an output of an earlier step."
        f"{repair}"
    )


class Planner:
    """Local JSON planner with timeout, validation, one repair, and fallback."""

    def __init__(
        self,
        provider,
        model: str | None = None,
        timeout: int = DEFAULT_PLANNER_TIMEOUT,
        retriever=None,
    ):
        self.provider = provider
        self.model = model or getattr(provider, "model", "")
        self.timeout = timeout
        self.retriever = retriever

    def _call(self, messages: list[dict]) -> tuple[str, dict]:
        options = {"num_predict": 1024}
        if self.timeout and self.timeout > 0:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.provider.chat_with_stats, messages, options)
            try:
                return future.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise PlannerTimeout(
                    f"planner did not answer within {self.timeout}s"
                ) from exc
            finally:
                pool.shutdown(wait=False)
        try:
            return self.provider.chat_with_stats(messages, options)
        except TypeError:
            return self.provider.chat(messages), {}

    def _invoke(
        self,
        task: str,
        inventory_block: str,
        shortlist,
        inventory_maps,
        error: str = "",
        invalid_plan: str = "",
    ) -> tuple[dict | None, PlanValidation, str, int, int]:
        prompt = build_planner_prompt(
            task, inventory_block, shortlist, error=error, invalid_plan=invalid_plan
        )
        messages = [{"role": "user", "content": prompt}]
        raw = ""
        prompt_tokens = completion_tokens = 0
        try:
            raw, stats = self._call(messages)
            prompt_tokens = int((stats or {}).get("prompt_tokens", 0) or 0)
            completion_tokens = int((stats or {}).get("completion_tokens", 0) or 0)
            payload = extract_json(raw)
            plan = _plan_from_dict(payload)
        except (PlanParseError, PlannerTimeout) as exc:
            return None, _failure(str(exc)), raw, prompt_tokens, completion_tokens
        except Exception as exc:  # noqa: BLE001 - provider fault is an invalid plan
            return None, _failure(f"planner provider error: {exc}"), raw, prompt_tokens, completion_tokens

        validation = validate_plan(
            plan,
            [candidate.name for candidate in shortlist],
            inventory_maps=inventory_maps,
            retriever=self.retriever,
        )
        return payload, validation, raw, prompt_tokens, completion_tokens

    def create_plan(
        self,
        task: str,
        inventory_block: str,
        shortlist,
        inventory_maps=None,
    ) -> PlannerOutcome:
        """Initial plan plus at most one pre-execution repair, then fallback."""
        payload, validation, raw, ptok, ctok = self._invoke(
            task, inventory_block, shortlist, inventory_maps
        )
        invocations = 1
        prompt_tokens, completion_tokens = ptok, ctok
        if validation.ok and payload is not None:
            plan = _plan_from_dict(payload)
            plan.planner_invocations = 1
            plan.raw_response_hash = hashlib.sha256((raw or "").encode()).hexdigest()
            return PlannerOutcome(
                plan=plan,
                validation=validation,
                invocations=1,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                raw=raw,
                shortlist=[candidate.name for candidate in shortlist],
            )

        # One pre-execution repair with the exact validation error.
        error_text = "; ".join(validation.errors) or "invalid plan"
        payload2, validation2, raw2, ptok2, ctok2 = self._invoke(
            task,
            inventory_block,
            shortlist,
            inventory_maps,
            error=error_text,
            invalid_plan=raw or json.dumps(payload or {}),
        )
        invocations = 2
        prompt_tokens += ptok2
        completion_tokens += ctok2
        if validation2.ok and payload2 is not None:
            plan = _plan_from_dict(payload2)
            plan.revision = 1
            plan.plan_repair_count = 1
            plan.planner_invocations = invocations
            plan.raw_response_hash = hashlib.sha256((raw2 or "").encode()).hexdigest()
            return PlannerOutcome(
                plan=plan,
                validation=validation2,
                invocations=invocations,
                plan_repair_count=1,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                raw=raw2,
                shortlist=[candidate.name for candidate in shortlist],
            )

        return PlannerOutcome(
            validation=validation2,
            invocations=invocations,
            plan_repair_count=1,
            fallback=True,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=raw2,
            shortlist=[candidate.name for candidate in shortlist],
        )

    def replan(
        self,
        task: str,
        inventory_block: str,
        shortlist,
        failed_plan,
        error: str,
        inventory_maps=None,
    ) -> PlannerOutcome:
        """One constrained post-failure re-plan (distinct from plan repair)."""
        invalid = (
            json.dumps(failed_plan.to_dict())
            if isinstance(failed_plan, ExecutionPlan)
            else json.dumps(failed_plan or {})
        )
        payload, validation, raw, ptok, ctok = self._invoke(
            task,
            inventory_block,
            shortlist,
            inventory_maps,
            error=error,
            invalid_plan=invalid,
        )
        if validation.ok and payload is not None:
            plan = _plan_from_dict(payload)
            plan.revision = 1
            plan.replan_count = 1
            plan.planner_invocations = 1
            plan.raw_response_hash = hashlib.sha256((raw or "").encode()).hexdigest()
            return PlannerOutcome(
                plan=plan,
                validation=validation,
                invocations=1,
                replan_count=1,
                prompt_tokens=ptok,
                completion_tokens=ctok,
                raw=raw,
                shortlist=[candidate.name for candidate in shortlist],
            )
        return PlannerOutcome(
            validation=validation,
            invocations=1,
            replan_count=1,
            fallback=True,
            prompt_tokens=ptok,
            completion_tokens=ctok,
            raw=raw,
            shortlist=[candidate.name for candidate in shortlist],
        )


def _failure(message: str) -> PlanValidation:
    validation = PlanValidation()
    validation.add(message)
    return validation
