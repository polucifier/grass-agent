#!/usr/bin/env python3
"""Build presentation.odp — a four-slide supervisor briefing on the Gate 1 state.

Usage:
    .venv/bin/python scripts/create_presentation.py

The deck content lives in the SLIDES list at the bottom of this file, so the
headline numbers can be updated after a benchmark re-run and the deck
regenerated rather than hand-edited in Impress.

odfpy constraints this file is written around
----------------------------------------------
odfpy wraps lxml with strict attribute grammars, and several names differ
from the ODF specification spelling. The conventions used here were
established by reading its grammar tables:

  * attribute kwargs are the dashed name with dashes stripped
    (``marginleft``, ``textindent``, ``pagewidth``, ``bulletchar``);
  * page size goes on ``PageLayoutProperties`` as ``pagewidth`` /
    ``pageheight``, and lands in ``styles.xml`` rather than ``content.xml``;
  * a slide is ``odf.draw.Page(masterpagename=...)`` — odfpy has no ``Slide``;
  * frame geometry is page-anchored through a ``family="graphic"`` style using
    ``verticalpos`` / ``horizontalpos`` / ``*rel``, not frame x/y;
  * ``Frame(stylename=...)`` wants the Style *element*, while
    ``List(stylename=...)`` wants a name string;
  * all text formatting must live in *named* styles, because
    ``style:text-properties`` is not accepted as a direct child of ``text:p``.

Bullets are literal glyphs in a styled ``text:span`` over a hanging-indent
paragraph rather than ODF list structures. odfpy silently drops
``text:list-style`` from ``office:automatic-styles`` — it parses and attaches
to the tree, then never serialises it — so a real ``text:list`` would render
with no bullet at all. The trade-off is that editing the text in Impress will
not renumber the Gate 2 steps automatically; for a static briefing deck the
deterministic output is worth more.

Layout is 16:9 (28cm x 15.75cm), the LibreOffice Impress default widescreen
ratio, with 28pt titles, 16pt subtitles and 17/15pt body copy.
"""

from pathlib import Path

from odf.draw import Frame, Page, TextBox
from odf.opendocument import OpenDocumentPresentation
from odf.style import (
    GraphicProperties,
    MasterPage,
    PageLayout,
    PageLayoutProperties,
    ParagraphProperties,
    Style,
    TextProperties,
)
from odf.text import H, P, Span

# --- geometry --------------------------------------------------------------

SLIDE_W = "28cm"
SLIDE_H = "15.75cm"
MARGIN_X = "1.35cm"

TITLE_X, TITLE_Y, TITLE_W, TITLE_H = MARGIN_X, "0.85cm", "25.3cm", "2.3cm"
SUB_X, SUB_Y, SUB_W, SUB_H = MARGIN_X, "3.15cm", "24.0cm", "1.1cm"
BODY_X, BODY_Y, BODY_W, BODY_H = MARGIN_X, "4.75cm", "25.3cm", "9.55cm"
FOOT_X, FOOT_Y, FOOT_W, FOOT_H = MARGIN_X, "14.45cm", "25.3cm", "0.7cm"

# --- palette ---------------------------------------------------------------

ACCENT = "#0b5d8a"
INK = "#1a1a1a"
SOFT_INK = "#3d3d3d"
MUTED = "#5f5f5f"
FAINT = "#8d8d8d"
RULE = "#b9c9d6"

# --- type scale ------------------------------------------------------------

PT_TITLE = "28pt"
PT_SUBTITLE = "16pt"
PT_BODY = "16pt"
PT_SUB = "15pt"
PT_FOOTER = "11pt"

# Hanging indents: the glyph sits in the negative-indent zone, so wrapped
# continuation lines align under the text rather than under the bullet.
INDENT_BULLET = "0.42in"
INDENT_SUB = "0.86in"
HANG = "-0.30in"


# --- style builders --------------------------------------------------------


def para_style(doc, name, indent=None, hang=None, space="0.15cm",
               rule=False, **text):
    """Named paragraph style. Indent/hang stay out of the text properties."""
    style = Style(name=name, family="paragraph", displayname=name)
    style.addElement(TextProperties(**text))
    if indent or rule:
        props = {"marginbottom": space}
        if indent:
            props.update(marginleft=indent, textindent=hang)
        if rule:
            # The accent underline below the subtitle replaces a drawn
            # shape: draw:frame does not accept draw:custom-shape in odfpy's
            # grammar, and a paragraph border renders identically.
            props.update(border=f"0.06pt solid {RULE}",
                         paddingbottom="0.32cm",
                         marginbottom="0cm")
        style.addElement(ParagraphProperties(**props))
    doc.automaticstyles.addElement(style)
    return name


def char_style(doc, name, **text):
    """Named character style, used to colour the bullet glyph."""
    style = Style(name=name, family="text", displayname=name)
    style.addElement(TextProperties(**text))
    doc.automaticstyles.addElement(style)
    return name


def frame_fill(doc, name):
    """Transparent, unstroked fill for text frames.

    Frames get their geometry from svg:x/y/width/height on the draw:frame
    itself. Positioning them through style:graphic-properties compiles and
    serialises correctly but renders nothing in Impress, because those
    properties are honoured for shapes, not for text frames. A default
    opaque fill also has to be suppressed explicitly.
    """
    style = Style(name=name, family="graphic")
    style.addElement(GraphicProperties(fill="none", stroke="none"))
    doc.automaticstyles.addElement(style)
    return style


def build_styles(doc):
    """Create every automatic style the deck uses; returns a name lookup."""
    n = {}
    n["title"] = para_style(doc, "dpTitle", fontweight="bold",
                            fontsize=PT_TITLE, color=ACCENT)
    n["subtitle"] = para_style(doc, "dpSubtitle", fontstyle="italic",
                               fontsize=PT_SUBTITLE, color=MUTED,
                               space="0cm", rule=True)
    n["author"] = para_style(doc, "dpAuthor", fontweight="bold",
                             fontsize=PT_BODY, color=ACCENT,
                             indent=INDENT_BULLET, hang=HANG)
    n["body"] = para_style(doc, "dpBody", fontsize=PT_BODY, color=INK,
                           indent=INDENT_BULLET, hang=HANG)
    n["sub"] = para_style(doc, "dpBodySub", fontsize=PT_SUB, color=SOFT_INK,
                          indent=INDENT_SUB, hang=HANG, space="0.13cm")
    n["step"] = para_style(doc, "dpStep", fontsize=PT_SUB, color=SOFT_INK,
                           indent=INDENT_BULLET, hang=HANG, space="0.13cm")
    n["footer"] = para_style(doc, "dpFooter", fontsize=PT_FOOTER, color=FAINT,
                             space="0cm")
    n["glyph"] = char_style(doc, "dpGlyph", fontweight="bold", color=ACCENT)

    n["fill"] = frame_fill(doc, "dpFrameFill")
    n["geom"] = {
        "title": (TITLE_X, TITLE_Y, TITLE_W, TITLE_H),
        "subtitle": (SUB_X, SUB_Y, SUB_W, SUB_H),
        "body": (BODY_X, BODY_Y, BODY_W, BODY_H),
        "footer": (FOOT_X, FOOT_Y, FOOT_W, FOOT_H),
    }
    return n


# --- slide assembly --------------------------------------------------------


def text_frame(names, role, paragraphs):
    box = TextBox()
    for para in paragraphs:
        box.addElement(para)
    x, y, w, h = names["geom"][role]
    frame = Frame(stylename=names["fill"], x=x, y=y, width=w, height=h)
    frame.addElement(box)
    return frame


GLYPH = {
    "author": "•  ",
    "body": "•  ",
    "sub": "–  ",
    "step": "",          # filled in by the step counter
}


def bullet_paragraph(kind, text, names, step_number=None):
    glyph = f"{step_number}.  " if kind == "step" else GLYPH[kind]
    para = P(stylename=names[kind])
    if glyph:
        para.addElement(Span(text=glyph, stylename=names["glyph"]))
    para.addElement(Span(text=text))
    return para


def make_page(master, spec, names):
    page = Page(masterpagename=master)

    if spec.get("title"):
        page.addElement(text_frame(
            names, "title",
            [H(text=spec["title"], outlinelevel="1", stylename=names["title"])],
        ))
    if spec.get("subtitle"):
        page.addElement(text_frame(
            names, "subtitle",
            [P(text=spec["subtitle"], stylename=names["subtitle"])],
        ))

    if spec.get("items"):
        body = TextBox()
        step = 0
        for level, kind, text in spec["items"]:
            if kind == "step":
                step += 1
                body.addElement(
                    bullet_paragraph(kind, text, names, step_number=step)
                )
            else:
                body.addElement(bullet_paragraph(kind, text, names))
        bx, by, bw, bh = names["geom"]["body"]
        frame = Frame(stylename=names["fill"], x=bx, y=by, width=bw, height=bh)
        frame.addElement(body)
        page.addElement(frame)

    if spec.get("footer"):
        page.addElement(text_frame(
            names, "footer",
            [P(text=spec["footer"], stylename=names["footer"])],
        ))
    return page


def build_document():
    doc = OpenDocumentPresentation()

    layout = PageLayout(name="dpLayout16x9")
    layout.addElement(PageLayoutProperties(
        printorientation="landscape", pagewidth=SLIDE_W, pageheight=SLIDE_H,
    ))
    doc.automaticstyles.addElement(layout)

    master = MasterPage(name="dpMaster16x9",
                        pagelayoutname=layout.getAttribute("name"))
    doc.masterstyles.addElement(master)

    names = build_styles(doc)
    for spec in SLIDES:
        doc.presentation.addElement(make_page(master, spec, names))
    return doc


def main():
    doc = build_document()
    out = Path(__file__).resolve().parent.parent / "presentation.odp"
    doc.write(str(out))
    print(f"Wrote {out}  ({out.stat().st_size:,} bytes, "
          f"{len(SLIDES)} slides, {SLIDE_W} x {SLIDE_H})")


# --- deck content ----------------------------------------------------------
#
# Figures are the measured Gate 1 baseline documented in README.md. Update
# them here and re-run this script after any benchmark change.
#
# Item tuple: (indent level, style role, text)
#   "author" -> accent bullet, bold      (title slide only)
#   "body"   -> filled bullet, 17pt
#   "sub"    -> en-dash sub-bullet, 15pt
#   "step"   -> decimal 1. 2. 3., 15pt

FOOTER = ("Grass Agent · Gate 1 · Mykhailo Radchenko · "
          "autonomous grass.tools code generation")

SLIDES = [
    {
        "title": "Autonomous Code Generation Agent for GRASS GIS 8.6 (grass.tools)",
        "subtitle": "Gate 1 Architecture & Empirical Evaluation Baseline",
        "items": [
            (0, "author", "Author: Mykhailo Radchenko"),
            (0, "body",
             "Problem — general LLMs drift to the legacy CLI "
             "(grass.script.run_command), hallucinate method signatures, and "
             "confuse the CLI habit of writing output= with the grass.tools "
             "convention, where modules return their result instead."),
            (0, "body",
             "Objective — a deterministic, 100% offline agent translating "
             "natural-language GIS prompts into syntactically valid, "
             "schema-compliant Python code grounded in the GRASS 8.6 manual."),
            (0, "body",
             "Zero cloud dependence — full privacy and local reproducibility "
             "via open-weight models served by Ollama: qwen2.5-coder:7b for "
             "synthesis, nomic-embed-text for embeddings."),
        ],
        "footer": FOOTER,
    },
    {
        "title": "System Architecture & Generation Pipeline",
        "subtitle": "Deterministic grounding and verification beyond the LLM",
        "items": [
            (0, "body",
             "Stage 1 — Knowledge extraction. 543 tools ingested from the "
             "GRASS 8.6 manuals into SQLite, with parsed signature schemas "
             "and 768-d embeddings indexed by sqlite-vec."),
            (0, "body",
             "Stage 2 — Hybrid RAG retrieval. Dense cosine blended with "
             "lexical SQL matching, abbreviation expansion (SYNONYMS, ~68 "
             "terms), wrapper preference (v.import over v.in.ogr), and "
             "anti-crowding (MAX_PER_STEP = 1) so one tool family cannot "
             "monopolise the context."),
            (0, "body",
             "Stage 3 — Context optimisation and synthesis. Boilerplate "
             "kwargs stripped (36.3% less signature text), canonical examples "
             "for outliers (r.mapcalc syntax; ** unpacking for v.distance), "
             "then zero-shot generation with qwen2.5-coder:7b."),
            (0, "body",
             "Stage 4 — Deterministic verification, no model involved: "
             "ast.parse for syntax, then a recursive AST walk against the "
             "database confirming module existence, required parameters, and "
             "no hallucinated arguments. Zero-chat contract enforced."),
        ],
        "footer": FOOTER,
    },
    {
        "title": "Empirical Evaluation & Performance",
        "subtitle": "High-fidelity synthesis across a 40-case two-tier benchmark",
        "items": [
            (0, "body",
             "Tier 1 (smoke suite): 10 / 10 passed (100%) — core raster and "
             "vector workflows, multi-step chaining, zero-chat compliance."),
            (0, "body",
             "Tier 2 (advanced suite): 26 / 30 passed (86.7%) — hydrology, "
             "remote sensing and NDVI, vector topology, network routing, "
             "multi-ring concentric buffering."),
            (0, "body",
             "Overall: 36 / 40 (90.0%) zero-shot static verification, every "
             "case passing all four assertions — syntax, zero-chat, schema, "
             "expected tool."),
            (0, "body",
             "Hardware: warm latency 0.9–1.8 s per prompt on a remote T4 GPU "
             "(~49 s suite) versus 10–11 s on a local mobile iGPU via Vulkan "
             "(465 s suite)."),
            (0, "sub",
             "Counter-intuitive: the 3B model is slower per prompt on "
             "integrated graphics — faster decode, but roughly twice the "
             "tokens; latency follows output length."),
        ],
        "footer": FOOTER,
    },
    {
        "title": "Residual Analysis & Roadmap to Gate 2",
        "subtitle": "From static well-formedness to runtime execution",
        "items": [
            (0, "body",
             "Boundary of Gate 1: static verification proves AST validity and "
             "schema compliance, not execution against real layers, argument "
             "values, or CRS consistency."),
            (0, "body",
             "The 4 residual failures are runtime-detectable exceptions, not "
             "architectural flaws: one retrieval gap, one required-parameter "
             "omission, one wrong operator, one hallucinated helper appended "
             "to a correct answer."),
            (0, "body",
             "Avoiding overfitting: tuning stopped at 90% — with "
             "non-deterministic sampling, further edits fit noise and risk "
             "silent regressions."),
            (0, "body", "Gate 2 — next steps:"),
            (0, "step",
             "Headless GRASS execution via grass.script.setup.init() against "
             "the North Carolina sample dataset."),
            (0, "step",
             "Runtime stderr interception classifying missing mapsets, layer "
             "type mismatches, and schema exceptions."),
            (0, "step",
             "Self-healing loop: re-prompt with the traceback and RAG context, "
             "then re-execute under a bounded retry budget."),
        ],
        "footer": FOOTER,
    },
]


if __name__ == "__main__":
    main()
