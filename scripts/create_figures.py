#!/usr/bin/env python3
"""Generate the briefing figures, styled to the presentation.odp palette.

Meeting artifact: writes to ./figures/ and is not part of the project.
Requires matplotlib, which is intentionally not listed in requirements.txt.

    .venv/bin/python scripts/create_figures.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display required

import matplotlib.patches as patches
import matplotlib.pyplot as plt

# --- palette: matches scripts/create_presentation.py exactly ---------------

ACCENT = "#0b5d8a"
ACCENT_LIGHT = "#e6f0f5"
INK = "#1a1a1a"
SOFT_INK = "#3d3d3d"
MUTED = "#5f5f5f"
RULE = "#b9c9d6"
SUCCESS = "#2a8a42"
BG = "#ffffff"

OUT_DIR = Path(__file__).resolve().parent.parent / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _save(fig, name):
    path = OUT_DIR / name
    plt.savefig(path, dpi=300, facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    print(f"Saved: {path}")
    return path


def generate_pipeline_diagram():
    """Four-stage pipeline: Stage 1 Knowledge Base -> Stage 4 Verification."""
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    stages = [
        ("Stage 1\nKnowledge Base",
         "543 Tools\nScraped Docs\n768-d Embeddings",
         "SQLite +\nsqlite-vec"),
        ("Stage 2\nHybrid RAG",
         "Dense Cosine\nLexical SYNONYMS\nAnti-Crowding",
         "k=5 Filtered\nTool Signatures"),
        ("Stage 3\nLLM Synthesis",
         "Kwarg Pruning\nCanonical Overrides\nZero-Chat Rules",
         "qwen2.5-coder:7b\n(Local / Ollama)"),
        ("Stage 4\nStatic Verification",
         "ast.parse (Syntax)\nSchema Tree-Walk\nRule 3 Normalizer",
         "100% Deterministic\n(No Model)"),
    ]

    box_w, box_h, gap, start_x, y = 1.9, 2.4, 0.65, 0.5, 0.9

    for i, (title, details, tech) in enumerate(stages):
        x = start_x + i * (box_w + gap)

        ax.add_patch(patches.FancyBboxPatch(
            (x, y), box_w, box_h,
            boxstyle="round,pad=0.08,rounding_size=0.15",
            facecolor=ACCENT_LIGHT, edgecolor=ACCENT, linewidth=1.8))

        ax.add_patch(patches.FancyBboxPatch(
            (x, y + box_h - 0.65), box_w, 0.65,
            boxstyle="round,pad=0.08,rounding_size=0.15",
            facecolor=ACCENT, edgecolor=ACCENT, linewidth=1.8))

        ax.text(x + box_w / 2, y + box_h - 0.32, title, ha="center",
                va="center", color="#ffffff", fontsize=9.5,
                fontweight="bold", linespacing=1.1)

        ax.text(x + box_w / 2, y + 1.05, details, ha="center", va="center",
                color=INK, fontsize=8, linespacing=1.3)

        ax.add_patch(patches.FancyBboxPatch(
            (x + 0.15, y + 0.15), box_w - 0.3, 0.45,
            boxstyle="round,pad=0.04,rounding_size=0.08",
            facecolor="#ffffff", edgecolor=RULE, linewidth=1.0))
        ax.text(x + box_w / 2, y + 0.37, tech, ha="center", va="center",
                color=SOFT_INK, fontsize=7, fontweight="bold", linespacing=1.1)

        if i < len(stages) - 1:
            ax.annotate(
                "", xy=(x + box_w + gap - 0.16, y + box_h / 2),
                xytext=(x + box_w + 0.08, y + box_h / 2),
                arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=2.2,
                                mutation_scale=14))

    ax.set_xlim(0, start_x + len(stages) * (box_w + gap) - 0.2)
    ax.set_ylim(0, 4.0)
    ax.axis("off")
    plt.tight_layout()
    return _save(fig, "pipeline_architecture.png")


def generate_benchmark_figures():
    """Verification pass rates by suite, and warm synthesis latency by host."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8), dpi=300)
    fig.patch.set_facecolor(BG)

    # --- panel 1: static verification rates
    suites = ["Tier 1\n(Smoke)", "Tier 2\n(Advanced)", "Overall\n(Gate 1)"]
    scores = [100.0, 86.7, 90.0]
    fractions = ["10/10", "26/30", "36/40"]

    bars1 = ax1.bar(suites, scores, color=[SUCCESS, ACCENT, ACCENT],
                    width=0.52, edgecolor=INK, linewidth=0.8)
    ax1.set_ylim(0, 118)
    ax1.set_ylabel("Verification Pass Rate (%)", fontsize=9,
                   fontweight="bold", color=INK)
    ax1.set_title("Static Verification Rates", fontsize=11,
                  fontweight="bold", color=ACCENT, pad=12)
    ax1.axhline(90.0, color=RULE, linestyle="--", linewidth=1.2, zorder=0)
    ax1.text(2.42, 90.0, " 90% combined", fontsize=7.5, color=MUTED,
             va="center", ha="left")

    for bar, frac, score in zip(bars1, fractions, scores):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2.5,
                 f"{score:.1f}%\n({frac})", ha="center", va="bottom",
                 fontsize=8.5, fontweight="bold", color=INK)

    # --- panel 2: warm latency per prompt
    targets = ["Local Laptop\niGPU (Vulkan)", "Remote Cloud\nT4 GPU (15 GB)"]
    latencies = [10.5, 1.35]

    bars2 = ax2.bar(targets, latencies, color=[MUTED, ACCENT], width=0.48,
                    edgecolor=INK, linewidth=0.8)
    ax2.set_ylim(0, 14)
    ax2.set_ylabel("Warm Latency / Prompt (seconds)", fontsize=9,
                   fontweight="bold", color=INK)
    ax2.set_title("Synthesis Latency Profile", fontsize=11,
                  fontweight="bold", color=ACCENT, pad=12)

    for bar, val in zip(bars2, latencies):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.35,
                 f"{val:.1f} s", ha="center", va="bottom", fontsize=9,
                 fontweight="bold", color=INK)

    ax2.text(1, 6.6, "≈8× faster\nwith a discrete GPU", ha="center",
             va="center", fontsize=8, fontweight="bold", color=ACCENT,
             bbox=dict(boxstyle="round,pad=0.35", facecolor=ACCENT_LIGHT,
                       edgecolor=ACCENT, lw=1.2))

    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(RULE)
        ax.spines["bottom"].set_color(RULE)
        ax.tick_params(colors=SOFT_INK, labelsize=8.5)

    plt.tight_layout()
    return _save(fig, "benchmark_performance.png")


def generate_residual_breakdown():
    """Slide 4: the four residual Tier 2 failures by cause."""
    fig, ax = plt.subplots(figsize=(9, 2.9), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    items = [
        ("tc_33", "Retrieval gap",
         "v.to.rast never\nreaches the top-5", ACCENT),
        ("tc_34", "Missing argument",
         "v.to.rast called\nwithout use=", MUTED),
        ("tc_28", "Wrong operator",
         "v.report used instead\nof v.to.db", MUTED),
        ("tc_38", "Hallucinated tool",
         "v.update.column invented,\nappended after a correct answer", MUTED),
    ]

    w, h, gap, y0 = 2.15, 1.50, 0.30, 0.55
    for i, (case, kind, detail, colour) in enumerate(items):
        x = 0.35 + i * (w + gap)
        ax.add_patch(patches.FancyBboxPatch(
            (x, y0), w, h, boxstyle="round,pad=0.08,rounding_size=0.12",
            facecolor="#ffffff", edgecolor=colour, linewidth=1.6))
        # Two-line header: Czech labels run wider than the English originals
        # and overflow a single line inside the card.
        head_h = 0.58
        ax.add_patch(patches.Rectangle((x, y0 + h - head_h), w, head_h,
                                       facecolor=colour, edgecolor="none"))
        ax.text(x + w / 2, y0 + h - 0.16, case, ha="center", va="center",
                color="#ffffff", fontsize=8.5, fontweight="bold")
        ax.text(x + w / 2, y0 + h - 0.38, kind, ha="center", va="center",
                color="#ffffff", fontsize=7.6, fontweight="bold")
        ax.text(x + w / 2, y0 + (h - head_h) / 2, detail, ha="center",
                va="center", color=SOFT_INK, fontsize=7.8, linespacing=1.4)

    ax.set_xlim(0, 0.35 + 4 * (w + gap) - gap + 0.35)
    ax.set_ylim(0, 2.25)
    ax.axis("off")
    plt.tight_layout()
    return _save(fig, "residual_failures.png")



def generate_dataflow_figure():
    """How a single user query actually travels through the pipeline.

    Complements the stage diagram: the knowledge base is read at two separate
    points (retrieval and schema validation) and never reaches the model
    itself, and four deterministic steps sit between the raw completion and
    the file on disk. Row 1 runs left-to-right, the completion drops at the
    right edge, and row 2 runs right-to-left so the drop stays a short
    vertical hop instead of a line across the figure.
    """
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    H = 0.92
    Y1, Y2 = 3.15, 0.75
    W1, S1 = 1.72, 2.02          # row 1: 5 boxes
    W2, S2 = 1.38, 1.68          # row 2: 6 boxes
    X0 = 0.15

    row1 = [
        ("User query", "natural language"),
        ("Embedding", "nomic-embed-text\n768-d vector"),
        ("Hybrid retrieval", "SYNONYMS + wrapper\npreference + anti-crowding"),
        ("Prompt assembly", "system prompt + top-5\ndocs + query"),
        ("LLM synthesis", "qwen2.5-coder:7b\n(Ollama, local)"),
    ]
    row2 = [
        ("Raw response", "as returned"),
        ("extract_python_code", "strips fences\nand prose"),
        ("normalize_dotted_calls", "tools.v.buffer\u2192\ntools.v_buffer"),
        ("ast.parse", "syntax gate"),
        ("validate_api", "schema tree-walk"),
        ("Saved script", "generated/<slug>.py\n+ debug header"),
    ]

    def box(x, y, w, title, sub, face="#ffffff", edge=ACCENT):
        ax.add_patch(patches.FancyBboxPatch(
            (x, y), w, H, boxstyle="round,pad=0.04,rounding_size=0.10",
            facecolor=face, edgecolor=edge, linewidth=1.4))
        ax.text(x + w / 2, y + H * 0.68, title, ha="center", va="center",
                color=INK, fontsize=7.6, fontweight="bold", linespacing=1.15)
        ax.text(x + w / 2, y + H * 0.28, sub, ha="center", va="center",
                color=SOFT_INK, fontsize=6.3, linespacing=1.2)

    def seg(p0, p1):
        ax.annotate("", xy=p1, xytext=p0, arrowprops=dict(
            arrowstyle="-|>", color=ACCENT, lw=1.5, mutation_scale=10,
            shrinkA=0, shrinkB=0))

    # --- row 1, left to right
    xs1 = [X0 + i * S1 for i in range(len(row1))]
    for i, (t, sub) in enumerate(row1):
        box(xs1[i], Y1, W1, t, sub, face=ACCENT_LIGHT if i in (0, 4) else "#ffffff")
        if i:
            seg((xs1[i - 1] + W1 + 0.03, Y1 + H / 2), (xs1[i] - 0.03, Y1 + H / 2))

    # --- row 2, right to left (mirrored placement)
    xs2 = [X0 + (len(row2) - 1 - i) * S2 for i in range(len(row2))]
    for i, (t, sub) in enumerate(row2):
        box(xs2[i], Y2, W2, t, sub,
            face=ACCENT_LIGHT if i == len(row2) - 1 else "#ffffff",
            edge=MUTED if i == len(row2) - 1 else ACCENT)
        if i:
            seg((xs2[i - 1] - 0.03, Y2 + H / 2), (xs2[i] + W2 + 0.03, Y2 + H / 2))

    # --- the drop: last box of row 1 -> rightmost box of row 2
    drop_x = xs1[-1] + W1 / 2
    ax.plot([drop_x, drop_x], [Y1, Y2 + H + 0.10], color=ACCENT, lw=1.5)
    seg((drop_x, Y2 + H + 0.10), (xs2[0] + W2 / 2, Y2 + H + 0.04))

    # --- knowledge base, feeding both rows
    db_w, db_x, db_y, db_h = 3.60, 1.95, 1.95, 0.72
    ax.add_patch(patches.FancyBboxPatch(
        (db_x, db_y), db_w, db_h, boxstyle="round,pad=0.04,rounding_size=0.10",
        facecolor="#ffffff", edgecolor=MUTED, linewidth=1.6,
        linestyle=(0, (4, 2))))
    ax.text(db_x + db_w / 2, db_y + db_h / 2,
            "data/grass_knowledge.db\n543 tools · SQLite + sqlite-vec",
            ha="center", va="center", color=MUTED, fontsize=7.2,
            fontweight="bold", linespacing=1.25)

    retr_c = xs1[2] + W1 / 2
    valid_c = xs2[4] + W2 / 2
    seg((retr_c, db_y + db_h + 0.03), (retr_c, Y1 - 0.03))          # up to retrieval
    seg((valid_c, db_y - 0.03), (valid_c, Y2 + H + 0.03))           # down to validate_api

    # --- failure path note
    ax.text((xs2[3] + xs2[4]) / 2, Y2 - 0.28,
            "fail \u2192 raise, nothing written to disk", ha="center",
            va="center", fontsize=6.8, fontweight="bold", color="#b03a2e")

    ax.set_xlim(-0.12, 10.12)
    ax.set_ylim(0.28, 4.34)
    ax.axis("off")
    plt.tight_layout()
    return _save(fig, "query_dataflow.png")


if __name__ == "__main__":
    generate_pipeline_diagram()
    generate_dataflow_figure()
    generate_benchmark_figures()
    generate_residual_breakdown()
