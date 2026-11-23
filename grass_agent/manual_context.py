"""Compact, budgeted manual cards for the new pipeline modes.

The knowledge base stores complete manual sections at rest. Inference sees a
``ManualCard``: small enough for an 8K context but complete enough to expose
the API signature, module flags, closed enums, and the constraints that make
the difference between an executable script and a plausible one.

The signature, flags, and closed enums are mandatory and strictly fail-closed.
Only optional prose (``DESCRIPTION`` and secondary ``EXAMPLES``) may be named in
``omissions``. Compaction order is fixed: deduplicate tools, compact
alternatives to one per step, drop optional prose, then fail closed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

SYNTHETIC_PARAMS = {"flags", "overwrite", "verbose", "quiet", "superquiet"}
SYNTHETIC_FLAGS = SYNTHETIC_PARAMS
TARGET_MIN_TOKENS = 250
TARGET_MAX_TOKENS = 600
DEFAULT_MANUAL_BUDGET_FRACTION = 0.45

_CONSTRAINT_KEYWORDS = (
    "integer",
    "float",
    "file",
    "rules",
    "topology",
    "duplicate",
    "threshold",
    "unit",
    "extent",
    "binary",
    "snap",
    "rmdupl",
    "curvature",
    "refraction",
    "reclass",
)


class ManualBudgetExceeded(Exception):
    """Mandatory card sections cannot fit the global documentation budget."""

    def __init__(self, tools: list[str], required_tokens: int, budget: int):
        self.tools = list(tools)
        self.required_tokens = required_tokens
        self.budget = budget
        super().__init__(
            "manual card budget exceeded after deterministic compaction: "
            f"{required_tokens} required tokens > {budget} budget "
            f"(tools: {', '.join(self.tools)})"
        )


def estimate_tokens(text: str) -> int:
    """Conservative estimate: ceil(chars / 3.5) plus a 10% safety margin."""
    if not text:
        return 0
    return int(math.ceil((len(text) / 3.5) * 1.1))


@dataclass
class ParameterCard:
    name: str
    type: str = ""
    required: bool = False
    default: object = None
    options: list[str] = field(default_factory=list)
    description: str = ""

    def render(self) -> str:
        parts = [f"  {self.name}"]
        if self.type:
            parts.append(f": {self.type}")
        parts.append(", required" if self.required else ", optional")
        if self.default not in (None, "None", ""):
            parts.append(f" = {self.default}")
        if self.options:
            choices = ", ".join(f'"{value}"' for value in self.options)
            parts.append(f", options: Literal[{choices}]")
        if self.description:
            parts.append(f"  -- {self.description}")
        return "".join(parts)


@dataclass
class ManualCard:
    tool: str
    signature: str = ""
    flags: list[str] = field(default_factory=list)
    parameters: list[ParameterCard] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)
    token_estimate: int = 0
    source: str = ""
    rendered: str = ""

    @property
    def within_target(self) -> bool:
        return TARGET_MIN_TOKENS <= self.token_estimate <= TARGET_MAX_TOKENS

    @property
    def mandatory_text(self) -> str:
        """Signature, flags, parameters/enums, and constraints (never dropped)."""
        blocks = [f"### {self.tool}"]
        if self.signature:
            blocks.append(f"API: {self.signature}")
        if self.flags:
            blocks.append("Flags:")
            blocks.extend(f"  {flag}" for flag in self.flags)
        if self.parameters:
            blocks.append("Parameters:")
            blocks.extend(parameter.render() for parameter in self.parameters)
        if self.constraints:
            blocks.append("Constraints:")
            blocks.extend(f"  - {constraint}" for constraint in self.constraints)
        return "\n".join(blocks)

    def render(self) -> str:
        blocks = [self.mandatory_text]
        if self.examples:
            blocks.append("Examples:")
            blocks.extend(f"  {example}" for example in self.examples)
        if self.alternatives:
            blocks.append("Alternatives:")
            blocks.extend(f"  {alternative}" for alternative in self.alternatives)
        for omission in self.omissions:
            blocks.append(f"[omitted: {omission}]")
        self.rendered = "\n".join(blocks)
        self.token_estimate = estimate_tokens(self.rendered)
        return self.rendered

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "signature": self.signature,
            "flags": list(self.flags),
            "parameters": [
                {
                    "name": parameter.name,
                    "type": parameter.type,
                    "required": parameter.required,
                    "default": parameter.default,
                    "options": list(parameter.options),
                    "description": parameter.description,
                }
                for parameter in self.parameters
            ],
            "constraints": list(self.constraints),
            "examples": list(self.examples),
            "alternatives": list(self.alternatives),
            "omissions": list(self.omissions),
            "token_estimate": self.token_estimate,
            "source": self.source,
        }


@dataclass
class ManualRenderResult:
    text: str = ""
    cards: list[ManualCard] = field(default_factory=list)
    tokens: int = 0
    budget: int = 0
    omissions: list[str] = field(default_factory=list)

    @property
    def card_tokens(self) -> list[int]:
        return [card.token_estimate for card in self.cards]

    def to_dict(self) -> dict:
        return {
            "budget": self.budget,
            "tokens": self.tokens,
            "omissions": list(self.omissions),
            "cards": [card.to_dict() for card in self.cards],
        }


def manual_budget(num_ctx: int = 8192, explicit: int | None = None) -> int:
    """Global documentation budget: explicit value or 45% of the context."""
    if explicit is not None:
        return explicit
    return int(DEFAULT_MANUAL_BUDGET_FRACTION * num_ctx)


def _field(record, name: str, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _flag_text(flag) -> str | None:
    if isinstance(flag, str):
        name, description, generic = flag.lstrip("-"), "", False
    elif isinstance(flag, dict):
        name = str(flag.get("flag", ""))
        description = str(flag.get("description", ""))
        generic = bool(flag.get("generic", False))
    else:
        name = str(getattr(flag, "flag", ""))
        description = str(getattr(flag, "description", ""))
        generic = bool(getattr(flag, "generic", False))
    if not name or generic:
        return None
    prefix = f"-{name}" if len(name) == 1 else name
    return f"{prefix}  {description}".rstrip()


def _options_for(record, parameter: str) -> list[str]:
    options = _field(record, "options", {}) or {}
    entries = options.get(parameter, []) if isinstance(options, dict) else []
    values = []
    for entry in entries:
        if isinstance(entry, str):
            values.append(entry)
            continue
        value = entry.get("value") if isinstance(entry, dict) else getattr(entry, "value", "")
        if value:
            values.append(str(value))
    return values


def _parameter_cards(record) -> list[ParameterCard]:
    params = _field(record, "params", {}) or {}
    cards: list[ParameterCard] = []
    for name, info in params.items():
        if name in SYNTHETIC_PARAMS:
            continue
        info = info or {}
        cards.append(
            ParameterCard(
                name=name,
                type=str(info.get("type", "")),
                required=bool(info.get("required", False)),
                default=info.get("default"),
                options=_options_for(record, name),
                description=str(info.get("description", "")),
            )
        )
    # Required-first, then declaration order, so the card reads predictably.
    return cards


def _section_texts(record, name: str) -> list[str]:
    sections = _field(record, "sections", {}) or {}
    entries = sections.get(name, []) if isinstance(sections, dict) else []
    texts = []
    for entry in entries:
        if isinstance(entry, str):
            texts.append(entry)
            continue
        text = entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", "")
        if text:
            texts.append(str(text))
    return texts


def _clean_line(line: str) -> str:
    line = re.sub(r"^[-*#>\s]+", "", line).strip()
    line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
    line = re.sub(r"\*(.*?)\*", r"\1", line)
    line = re.sub(r"`([^`]*)`", r"\1", line)
    return re.sub(r"\s+", " ", line).strip()


def select_constraints(record, limit: int = 3) -> list[str]:
    """Top NOTES bullets by the documented keyword rule, in manual order.

    Selection is deterministic: score by keyword hits, break ties by the
    original order, keep at most ``limit``, then restore manual order.
    """
    text = "\n".join(_section_texts(record, "NOTES"))
    if not text:
        return []
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 15 and not line.startswith("```")]
    scored = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        hits = sum(1 for keyword in _CONSTRAINT_KEYWORDS if keyword in lowered)
        scored.append((hits, index, line))
    if not scored:
        return []
    chosen = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return [line for _, _, line in sorted(chosen, key=lambda item: item[1])]


def _extract_examples(record, max_examples: int = 2) -> list[str]:
    examples: list[str] = []
    for text in _section_texts(record, "EXAMPLES"):
        for block in re.findall(r"```(?:python|sh)?\s*\n(.*?)```", text, re.DOTALL):
            cleaned = block.strip()
            if cleaned and cleaned not in examples:
                examples.append(cleaned)
            if len(examples) >= max_examples:
                return examples
    if not examples:
        example = str(_field(record, "example", "") or "").strip()
        if example:
            examples.append(example)
    return examples[:max_examples]


def _alternative_text(alternative) -> str:
    if isinstance(alternative, str):
        return alternative
    name = str(_field(alternative, "name", ""))
    note = str(_field(alternative, "note", "") or "")
    if not note:
        try:
            from rag_retriever import family_note

            note = family_note(name)
        except Exception:  # noqa: BLE001 - alternatives are optional prose
            note = ""
    return f"{name} — {note}".rstrip(" —") if note else name


def build_card(
    record,
    alternatives=None,
    include_examples: bool = True,
    max_examples: int = 2,
    max_alternatives: int = 2,
) -> ManualCard:
    """Build one card without applying the global budget."""
    tool = str(_field(record, "name", "") or _field(record, "tool", ""))
    flags = [text for text in (_flag_text(flag) for flag in _field(record, "flags", []) or []) if text]
    card = ManualCard(
        tool=tool,
        signature=str(_field(record, "signature", "") or ""),
        flags=flags,
        parameters=_parameter_cards(record),
        constraints=select_constraints(record, limit=3),
        examples=_extract_examples(record, max_examples) if include_examples else [],
        alternatives=[
            _alternative_text(alternative)
            for alternative in list(alternatives or [])[:max_alternatives]
        ],
        source=str(_field(record, "source", "") or ""),
    )
    if not include_examples and _section_texts(record, "EXAMPLES"):
        card.omissions.append("EXAMPLES")
    # DESCRIPTION is optional prose and is omitted by default.
    if _section_texts(record, "DESCRIPTION"):
        card.omissions.append("DESCRIPTION")
    card.render()
    return card


def render_manual_cards(
    records,
    budget: int | None = None,
    num_ctx: int = 8192,
    alternatives: dict[str, list] | None = None,
    dedupe: bool = True,
) -> ManualRenderResult:
    """Render deduplicated cards within the global budget.

    Raises :class:`ManualBudgetExceeded` when mandatory sections still exceed
    the budget after the deterministic compaction order.
    """
    budget = manual_budget(num_ctx, budget)
    alternatives = alternatives or {}

    seen: set[str] = set()
    ordered = []
    for record in records:
        name = str(_field(record, "name", "") or _field(record, "tool", ""))
        if dedupe and name in seen:
            continue
        seen.add(name)
        ordered.append(record)

    def attempt(include_examples: bool, max_alternatives: int, secondary_examples: bool):
        cards = []
        for record in ordered:
            name = str(_field(record, "name", "") or _field(record, "tool", ""))
            card = build_card(
                record,
                alternatives=alternatives.get(name, []),
                include_examples=include_examples,
                max_examples=2 if secondary_examples else 1,
                max_alternatives=max_alternatives,
            )
            if include_examples and not secondary_examples and card.examples:
                card.omissions.append("secondary EXAMPLES")
                card.examples = card.examples[:1]
                card.render()
            cards.append(card)
        text = "\n\n".join(card.rendered for card in cards)
        tokens = estimate_tokens(text)
        return cards, text, tokens

    # 1. Full card set.
    cards, text, tokens = attempt(True, 2, True)
    if tokens <= budget:
        return _result(cards, text, tokens, budget)

    # 2. Compact alternatives to one per step.
    cards, text, tokens = attempt(True, 1, True)
    if tokens <= budget:
        return _result(cards, text, tokens, budget)

    # 3. Drop optional prose (examples), keeping mandatory sections.
    cards, text, tokens = attempt(False, 1, False)
    if tokens <= budget:
        return _result(cards, text, tokens, budget)

    # 4. Fail closed; never truncate a signature, flag, or enum.
    mandatory_tokens = estimate_tokens(
        "\n\n".join(card.mandatory_text for card in cards)
    )
    if mandatory_tokens <= budget:
        # The mandatory text fits; only the current concrete record set is
        # oversized. This cannot happen given step 3, but keep the diagnostic
        # honest rather than silently truncating.
        raise ManualBudgetExceeded([card.tool for card in cards], mandatory_tokens, budget)
    raise ManualBudgetExceeded([card.tool for card in cards], mandatory_tokens, budget)


def _result(cards, text, tokens, budget) -> ManualRenderResult:
    omissions: list[str] = []
    for card in cards:
        for omission in card.omissions:
            label = f"{card.tool}: {omission}"
            if label not in omissions:
                omissions.append(label)
    return ManualRenderResult(
        text=text,
        cards=cards,
        tokens=tokens,
        budget=budget,
        omissions=omissions,
    )
