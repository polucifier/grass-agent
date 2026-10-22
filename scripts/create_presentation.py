#!/usr/bin/env python3
"""Build presentation.odp — an eleven-slide Czech-language briefing on the Gate 1 state.

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

import struct
from pathlib import Path

from odf.draw import Frame, Image, Page, TextBox
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

ROOT = Path(__file__).resolve().parent.parent
FIGURES = ROOT / "figures"

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


def png_size(path):
    """Width/height in pixels, read straight from the PNG IHDR chunk.

    Avoids pulling in an image library just to preserve aspect ratio.
    """
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _cm(value):
    """Parse an ODF length ('12.5cm', '1in', '40pt') into centimetres."""
    text = str(value).strip()
    for unit, factor in (("cm", 1.0), ("mm", 0.1), ("in", 2.54), ("pt", 2.54 / 72)):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * factor
    return float(text)


def fit_box(path, x, y, max_w, max_h):
    """Fit an image inside a box, preserving aspect ratio, centred."""
    pw, ph = png_size(path)
    box_w, box_h = _cm(max_w), _cm(max_h)
    scale = min(box_w / pw, box_h / ph)
    w, h = pw * scale, ph * scale
    return _cm(x) + (box_w - w) / 2, _cm(y) + (box_h - h) / 2, w, h


def image_frame(doc, img_path, x, y, max_w, max_h):
    """Embed an image, scaled to fit its box without distortion.

    doc.addPicture() registers the file and returns the draw:image href; the
    frame carries geometry inline, as text frames do. Sizing to the box
    without preserving aspect visibly squashes the figures, so the fitted
    rectangle is computed from the PNG's own dimensions.
    """
    fx, fy, fw, fh = fit_box(img_path, x, y, max_w, max_h)
    href = doc.addPicture(str(img_path))
    frame = Frame(x=f"{fx:.3f}cm", y=f"{fy:.3f}cm",
                  width=f"{fw:.3f}cm", height=f"{fh:.3f}cm")
    frame.addElement(Image(href=href))
    return frame


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
        # Standalone figure slides. The image is fitted into the large box
        # below the subtitle, and the caption is drawn *on top of* the figure
        # where the PNG has a genuinely empty horizontal band — measured by
        # blank_band(), not assumed. Slides whose figure has no such band fall
        # back to the caption sitting just underneath it.
        "fig_over": (MARGIN_X, "4.30cm", "25.3cm", "9.90cm"),
        "fig_under": (MARGIN_X, "4.30cm", "25.3cm", "9.30cm"),
        "caption": (MARGIN_X, "13.55cm", "25.3cm", "0.65cm"),
    }
    return n


def blank_band(path, min_frac=0.10):
    """Locate the widest empty horizontal band of a PNG.

    Returns ``(top, bottom)`` as fractions of image height, or ``None`` when
    no band is at least ``min_frac`` tall. Matplotlib's ``bbox_inches="tight"``
    leaves uneven margins, so a caption can be drawn on the figure itself
    instead of stealing a band below it -- but only where the pixels really
    are white, otherwise it would collide with the diagram's own labels.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    a = np.asarray(Image.open(path).convert("L"))
    empty = (a < 245).sum(axis=1) < 3
    best = cur = start = best_start = 0
    for i, is_empty in enumerate(empty):
        if is_empty:
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, best_start = cur, start
        else:
            cur = 0
    if best / len(empty) < min_frac:
        return None
    return best_start / len(empty), (best_start + best) / len(empty)


def overlay_y(img_path, box, cap_h=0.65):
    """Y for a caption drawn on a figure's blank band, in cm.

    Centres one caption line inside the band and keeps it from escaping the
    image rectangle, so it never spills onto the surrounding slide.
    """
    x, y, max_w, max_h = box
    _, fy, _, fh = fit_box(img_path, x, y, max_w, max_h)
    band = blank_band(img_path)
    if band is None:
        return None
    top, bottom = band
    centre = fy + fh * (top + bottom) / 2
    return max(fy, min(fy + fh - cap_h, centre - cap_h / 2))


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


def make_page(doc, master, spec, names):
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

    if spec.get("image"):
        role = spec["image_role"]
        ix, iy, iw, ih = names["geom"][role]
        page.addElement(image_frame(doc, FIGURES / spec["image"],
                                   ix, iy, iw, ih))

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
        bx, by, bw, bh = names["geom"][spec.get("body_role", "body")]
        if spec.get("image") and spec["image_role"] == "fig_over":
            # Prefer drawing the caption on the figure's own empty band; fall
            # back to the reserved caption line if the PNG has no room.
            placed = overlay_y(FIGURES / spec["image"],
                               names["geom"]["fig_over"])
            if placed is not None:
                by = f"{placed:.3f}cm"
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
        doc.presentation.addElement(make_page(doc, master, spec, names))
    return doc


def ensure_figures():
    """Generate any missing figure PNGs by delegating to create_figures.py."""
    wanted = ["pipeline_architecture.png", "query_dataflow.png",
              "benchmark_performance.png", "residual_failures.png"]
    if all((FIGURES / name).exists() for name in wanted):
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "create_figures", Path(__file__).resolve().parent / "create_figures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.generate_pipeline_diagram()
    mod.generate_dataflow_figure()
    mod.generate_benchmark_figures()
    mod.generate_residual_breakdown()


def main():
    ensure_figures()
    doc = build_document()
    out = ROOT / "presentation.odp"
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
          "autonomní generování kódu pro grass.tools")

SLIDES = [
    # --- 1. Titul a motivace ----------------------------------------------
    {
        "title": "Autonomní agent pro generování kódu pro GRASS 8.6 (grass.tools)",
        "subtitle": "Architektura Gate 1 a experimentální evaluační základ",
        "items": [
            (0, "author", "Autor: Mykhailo Radchenko"),
            (0, "body",
             "Problém — obecné LLM modely trpí driftem ke staršímu CLI "
             "rozhraní (grass.script.run_command), halucinací signatur metod "
             "a záměnou konvence volání při cílení na moderní API grass.tools."),
            (0, "body",
             "Cíl — deterministický, 100% offline agent, který překládá "
             "přirozené jazykové GIS dotazy do syntakticky platných a schématu "
             "vyhovujících Python skriptů."),
            (0, "body",
             "Nulová závislost na cloudu — lokální a soukromá inference přes "
             "Ollama s open-weight modely: qwen2.5-coder:7b pro syntézu kódu a "
             "nomic-embed-text pro embeddings."),
        ],
        "footer": FOOTER,
    },
    # --- 2. Přehled pipeline (obrázek) -------------------------------------
    {
        "title": "Přehled systémové pipeline",
        "subtitle": "Čtyři fáze mezi jazykovým dotazem a ověřeným kódem",
        "image": "pipeline_architecture.png",
        "image_role": "fig_over",
        "body_role": "caption",
        "items": [
            (0, "body",
             "Pouze fáze 3 zahrnuje jazykový model; ostatní jsou deterministické."),
        ],
        "footer": FOOTER,
    },
    # --- 3. Data flow of a single query (obrázek) --------------------------
    {
        "title": "Zpracování jednoho dotazu",
        "subtitle": "Cesta od přirozeného jazyka k ověřenému souboru na disku",
        "image": "query_dataflow.png",
        "image_role": "fig_under",
        "body_role": "caption",
        "items": [
            (0, "body",
             "Knowledge base se čte na dvou místech a nikdy nedosáhne modelu."),
        ],
        "footer": FOOTER,
    },
    # --- 4. Fáze 1 ---------------------------------------------------------
    {
        "title": "Fáze 1 — Offline knowledge base a vector store",
        "subtitle": "Autoritativní ukotvení v oficiální dokumentaci GRASS 8.6",
        "items": [
            (0, "body",
             "Automated manual ingestion — 543 nástrojů z dokumentace GRASS 8.6 "
             "uloženo do samostatné 3,8 MB SQLite databáze "
             "(data/grass_knowledge.db) bez jediného síťového volání za běhu."),
            (0, "body",
             "768-dimensional embeddings — textové reprezentace názvů nástrojů, "
             "popisů a schémat parametrů mapovány do 768-d sémantických vektorů "
             "lokálním modelem nomic-embed-text."),
            (0, "body",
             "sqlite-vec virtual tables — C rozšíření umožňující nativní "
             "vektorové cosine similarity vyhledávání přímo v databázi, bez "
             "externí vektorové databáze."),
            (0, "body",
             "Authoritative schema extraction — zachycuje signatury metod, "
             "povinné vs. volitelné argumenty, typy parametrů a ukázková použití."),
        ],
        "footer": FOOTER,
    },
    # --- 5. Fáze 2 ---------------------------------------------------------
    {
        "title": "Fáze 2 — Hybrid multi-signal RAG retrieval",
        "subtitle": "Překonání omezení sémantického vektorového vyhledávání na GIS dotazy",
        "items": [
            (0, "body",
             "Dense cosine similarity — výpočet sémantické blízkosti vektorů pro "
             "zachycení konceptuálního záměru (např. ‚vodní tok‘ → nástroje pro "
             "streamy a hydrologii)."),
            (0, "body",
             "Lexical synonyms (SYNONYMS) — rozšiřuje 60+ oborových termínů "
             "(např. ‚statistiky‘ → ‚stats‘, ‚zonální‘ → ‚v.rast.stats‘) přes SQL "
             "LIKE, pro překlad hovorových výrazů do historického pojmenování GRASS."),
            (0, "body",
             "Modern wrapper preference — ohodnocuje moderní wrappery "
             "(v.import/r.import) +0,6 oproti nízkoúrovňovým driverům "
             "(v.in.ogr/r.in.gdal), pokud OGR/GDAL drivery nejsou výslovně "
             "požadovány."),
            (0, "body",
             "Anti-crowding (MAX_PER_STEP = 1) — slučuje rodiny nástrojů "
             "(d.* → display, r.li.* → landscape), aby zobrazovací nebo pomocné "
             "moduly neobsadily všech pět nejlepších pozic."),
        ],
        "footer": FOOTER,
    },
    # --- 6. Fáze 3 ---------------------------------------------------------
    {
        "title": "Fáze 3 — Context optimization a LLM synthesis",
        "subtitle": "Ukotvení malých lokálních modelů agresivní tvorbou promptů",
        "items": [
            (0, "body",
             "Kwarg pruning — odstraněny nadbytečné execution argumenty "
             "(flags, overwrite, verbose, quiet), což zkrátilo text signatur o "
             "36,3 % a eliminuje propis parametrů do výstupu."),
            (0, "body",
             "Canonical overrides — poskytují platné šablony volání pro odlehlé "
             "nástroje (algebraická syntaxe r.mapcalc) a případy s rezervovanými "
             "klíčovými slovy (v.distance(**{\'from\': ...}))."),
            (0, "body",
             "Zero-chat contract — vynucuje striktní systémový prompt vyžadující "
             "čistý, spustitelný Python kód bez jakéhokoli konverzačního textu, "
             "vysvětlení nebo markdown fence."),
            (0, "body",
             "Local inference — zero-shot syntéza Python kódu lokálně přes "
             "Ollama s modelem qwen2.5-coder:7b."),
        ],
        "footer": FOOTER,
    },
    # --- 7. Fáze 4 ---------------------------------------------------------
    {
        "title": "Fáze 4 — Deterministic static verification",
        "subtitle": "Validace na úrovni kompilátoru bez zapojení modelu",
        "items": [
            (0, "body",
             "Deterministic pass — působí jako automatická statická "
             "kompilační bariéra před uložením kódu na disk; zcela nezávislá na "
             "samplování LLM."),
            (0, "body",
             "Python AST parsing (ast.parse) — kompiluje generovaný kód do "
             "abstraktního syntaxového stromu a odmítá syntaktické chyby, chybné "
             "odsazení nebo konverzační zbytky."),
            (0, "body",
             "Schema tree-walk (validate_api) — prochází uzly volání v AST proti "
             "schématům v SQLite a kontroluje:"),
            (0, "sub", "ověřit existenci nástroje"),
            (0, "sub", "vynutit použití keyword argumentů"),
            (0, "sub", "zkontrolovat povinné parametry"),
            (0, "sub", "odmítnout halucinované kwargs"),
            (0, "body",
             "Rule 3 normalizer — automaticky opravuje tečkované metody "
             "(tools.v.buffer → tools.v_buffer), aby syntakticky správné skripty "
             "nebyly odmítnuty kvůli formátové chybě."),
        ],
        "footer": FOOTER,
    },
    # --- 8. Evaluace -------------------------------------------------------
    {
        "title": "Empirická evaluace a výkon",
        "subtitle": "Vysoká věrnost syntézy napříč 40 případovou dvouúrovňovou sadou",
        "items": [
            (0, "body",
             "Tier 1 (smoke suite): 10 / 10 (100 %) — základní rastrové a vektorové "
             "workflow, multi-step řetězení a soulad s zero-chat kontraktem."),
            (0, "body",
             "Tier 2 (advanced suite): 26 / 30 (86,7 %) — komplexní hydrologie, "
             "dálkové snímkování a NDVI, vektorová topologie, síťové routování a "
             "víceprstencové koncentrické buffery."),
            (0, "body",
             "Overall benchmark pass rate: 36 / 40 (90,0 %) zero-shot ověřeno ve "
             "všech testovacích případech."),
            (0, "body",
             "Hardware latency profile — teplá latence 0,9–1,8 s na prompt na T4 "
             "GPU (~49 s celá sada) versus 10–11 s na lokálním mobilním iGPU přes "
             "Vulkan (465 s celá sada)."),
            (0, "sub",
             "Zjištění z měření: 7B na lokálním iGPU nedrží čistých 10/10 — "
             "v opakovaných bězích 9–10/10 (selhává tc_07). Model 3B kolísá "
             "mezi 8 a 10/10 a na teplém běhu vždy selhává na tc_10."),
        ],
        "footer": FOOTER,
    },
    # --- 9. Výsledky benchmarku (obrázek) ----------------------------------
    {
        "title": "Výsledky benchmarku na první pohled",
        "subtitle": "Míra verifikace podle sady a teplá latence syntézy podle hostitele",
        "image": "benchmark_performance.png",
        "image_role": "fig_under",
        "body_role": "caption",
        "items": [
            (0, "body",
             "Verifikace podle sady (vlevo); teplá latence na prompt podle "
             "hostitele (vpravo)."),
        ],
        "footer": FOOTER,
    },
    # --- 10. Diagnostika selhání (obrázek) ----------------------------------
    {
        "title": "Diagnostika zbývajících selhání",
        "subtitle": "Všechna čtyři selhání v Tier 2 klasifikovaná podle kořenové příčiny",
        "image": "residual_failures.png",
        "image_role": "fig_over",
        "body_role": "caption",
        "items": [
            (0, "body",
             "Jedna mezera v retrievalu; tři chyby modelu, které by runtime "
             "harness odhalil okamžitě."),
        ],
        "footer": FOOTER,
    },
    # --- 11. Analýza a plán na Gate 2 --------------------------------------
    {
        "title": "Analýza zbytků a plán na Gate 2",
        "subtitle": "Přechod od statické správnosti ke skutečnému spuštění",
        "items": [
            (0, "body",
             "Hranice Gate 1 — dokazuje platnost AST a soulad se schématem, nikoli "
             "běh proti skutečným GIS vrstvám, souřadnicovým systémům nebo "
             "geometrii dat."),
            (0, "body",
             "Diagnostika čtyř zbývajících selhání — identifikována jako chyby "
             "zjistitelné za běhu (chybějící parametry, halucinované pomocné "
             "nástroje), nikoli jako architektonické nedostatky."),
            (0, "body",
             "Kontrolované zastavení — ladění promptů bylo záměrně zastaveno na "
             "90 %, aby se předešlo přeučení na šum z nedeterministického "
             "samplování LLM."),
            (0, "body", "Plán Gate 2 (runtime a self-healing):"),
            (0, "step",
             "Headless spuštění GRASS runtime přes grass.script.setup.init() s "
             "použitím vzorkové datové sady North Carolina."),
            (0, "step",
             "Zachycení runtime stderr (chybějící mapsety, nekompatibilní typy "
             "vrstev, výjimky schématu)."),
            (0, "step",
             "Automatizovaná self-healing smyčka: přesměrování LLM s tracebackem "
             "a cíleným RAG kontextem podle omezeného rozpočtu pokusů."),
        ],
        "footer": FOOTER,
    },
]


if __name__ == "__main__":
    main()
