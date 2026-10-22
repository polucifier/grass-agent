"""Initial-prompt map inventory grounding (FR-012b, SC-006b).

Attempt 1 previously received tool documentation but no map names, so the
zero-shot baseline was free to invent layers. These tests pin the contract:
the same `### Available Dataset Maps` block used by repairs reaches the very
first generation prompt, and its absence never breaks prompt construction.
"""

from pathlib import Path

from benchmarks.run_gate2 import generate_attempt, read_inventory_safely
from code_generator import GrassCodeGenerator
from config import GenerationConfig
from grass_agent.inventory import MapInventory, read_inventory
from rag_retriever import ToolDoc


class FakeProvider:
    """Records the messages sent to the model and returns valid code."""

    def __init__(self):
        self.messages: list[dict] | None = None
        self.last_stats = {"prompt_tokens": 3, "completion_tokens": 4}

    def generate_embeddings(self, text: str) -> list[float]:
        return [0.0, 0.0]

    def chat(self, messages: list[dict], options: dict | None = None) -> str:
        self.messages = messages
        return "from grass.tools import Tools\ntools = Tools()\n"


class FakeRetriever:
    def retrieve(self, query: str, query_embedding, k: int = 5) -> list[ToolDoc]:
        return [
            ToolDoc(
                name="r.info",
                category="r",
                description="Prints basic information about a raster map.",
                signature="r_info(map)",
                example='tools.r_info(map="elevation")',
                params={"map": {"required": True}},
                similarity=1.0,
            )
        ]

    def get_tool(self, name: str) -> ToolDoc | None:
        return None


def _generator(provider: FakeProvider) -> GrassCodeGenerator:
    return GrassCodeGenerator(GenerationConfig(), provider, FakeRetriever())


def _user_message(provider: FakeProvider) -> str:
    assert provider.messages is not None
    return provider.messages[1]["content"]


def test_initial_prompt_contains_inventory_block_when_provided():
    provider = FakeProvider()
    block = MapInventory(
        rasters=("basins", "elevation", "lakes"),
        vectors=("roadsmajor", "streams"),
    ).format_block()

    _generator(provider).generate(
        "Compute slope from the elevation raster.", inventory_block=block
    )
    user = _user_message(provider)

    assert "### Available Dataset Maps" in user
    assert "Available Rasters: [basins, elevation, lakes]" in user
    assert "Available Vectors: [roadsmajor, streams]" in user
    assert "ONLY maps that exist" in user
    # Grounding sits between the docs and the task, as in repair prompts.
    assert user.index("Relevant GRASS tools documentation") < user.index(
        "### Available Dataset Maps"
    )
    assert user.index("### Available Dataset Maps") < user.index("Task:")


def test_initial_prompt_omits_block_when_empty():
    provider = FakeProvider()
    _generator(provider).generate("Compute slope from elevation.", inventory_block="")
    user = _user_message(provider)

    assert "### Available Dataset Maps" not in user
    assert "Task: Compute slope from elevation." in user


def test_inventory_from_project_reaches_the_initial_prompt(tmp_path: Path):
    """End-to-end: on-disk maps -> read_inventory -> attempt-1 prompt."""
    permanent = tmp_path / "PERMANENT"
    (permanent / "cellhd").mkdir(parents=True)
    for name in ("elevation", "lakes", "soils"):
        (permanent / "cellhd" / name).write_text("", encoding="utf-8")
    (permanent / "vector" / "streams").mkdir(parents=True)

    inventory = read_inventory(tmp_path)
    provider = FakeProvider()
    _generator(provider).generate(
        "Buffer the streams.", inventory_block=inventory.format_block()
    )
    user = _user_message(provider)

    assert "### Available Dataset Maps" in user
    assert "elevation" in user and "lakes" in user and "soils" in user
    assert "streams" in user


def test_generate_attempt_forwards_the_inventory_block():
    class RecordingGenerator:
        def __init__(self):
            self.inventory_block = None
            self.provider = self
            self.last_stats = {"prompt_tokens": 0, "completion_tokens": 0}

        def generate(self, prompt: str, inventory_block: str = "") -> str:
            self.inventory_block = inventory_block
            return "from grass.tools import Tools\ntools = Tools()\n"

    block = MapInventory(rasters=("elevation",)).format_block()
    generator = RecordingGenerator()
    generate_attempt(generator, "task", None, block)

    assert generator.inventory_block == block


def test_unreadable_inventory_degrades_to_empty_without_raising(monkeypatch, tmp_path):
    import benchmarks.run_gate2 as run_gate2

    def boom(_dataset_project):
        raise OSError("dataset is unreadable")

    monkeypatch.setattr(run_gate2, "read_inventory", boom)

    inventory = read_inventory_safely(tmp_path)

    assert inventory.is_empty()
    assert inventory.format_block() == ""
