import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import ollama
import requests
import sqlite_vec
from bs4 import BeautifulSoup

INDEX_HTML = Path(__file__).resolve().parent.parent / "Tools - GRASS 8.6 Documentation.html"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grass_knowledge.db"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
MANUALS_BASE = "https://grass.osgeo.org/grass-stable/manuals"
EMBED_MODEL = "nomic-embed-text"
DIM = 768
RATE_LIMIT = 0.4

CATEGORY_HEADER = re.compile(r"-tools-([a-z0-9.]+)$")
PARAM_PATTERN = re.compile(r"<strong>([a-z_]+)</strong>\s*:\s*([^,]+),\s*<em>(required|optional)</em>")


def parse_signature_params(signature: str) -> dict:
    """Derive the authoritative parameter set from the grass.tools signature.

    The signature lists the real API parameter names; the params tab below can
    carry legacy/CLI names (e.g. v.overlay documents 'and' but the API uses
    'output'). Required == no default value in the signature.

    The docs format the signature one parameter per line, so a line is a single
    param: the name runs to the first '=' and the default is everything after
    it (defaults may contain commas, e.g. threshold=-1,0,0).
    """
    if not signature or "(" not in signature or ")" not in signature:
        return {}
    body = signature.split("(")[1].rsplit(")", 1)[0]
    params: dict = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",").strip()
        if not line or line in {")", ")", "*", "**"}:
            continue
        if "=" in line:
            name, default = line.split("=", 1)
            name = name.strip()
            if name and name != "self":
                params[name] = {"type": "", "required": False, "default": default.strip()}
        else:
            name = line.strip()
            if name and name != "self":
                params[name] = {"type": "", "required": True}
    return params


def parse_index(html: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    tools: list[tuple[str, str, str]] = []
    current_cat = ""
    for el in soup.find_all(["h3", "tr"]):
        if el.name == "h3":
            m = CATEGORY_HEADER.search(el.get("id", ""))
            if m:
                current_cat = m.group(1)
            continue
        a = el.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not href.endswith(".html") or "?" in href:
            continue
        tds = el.find_all("td")
        if len(tds) < 2:
            continue
        if not tds[0].find("a"):
            continue
        name = a.get_text(strip=True)
        desc = tds[1].get_text(strip=True)
        tools.append((name, current_cat, desc))
    return tools


def fetch_tool_page(name: str) -> str:
    cached = CACHE_DIR / f"{name}.html"
    if cached.exists():
        return cached.read_text()
    url = f"{MANUALS_BASE}/{name}.html"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text
    cached.write_text(html)
    time.sleep(RATE_LIMIT)
    return html


def parse_tool_page(html: str, fallback_desc: str) -> tuple[str, str, dict, str, str]:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    desc = fallback_desc
    if h1:
        first_p = h1.find_next("p")
        if first_p:
            desc = first_p.get_text(strip=True) or desc

    signature = ""
    example = ""
    for tabbed in soup.find_all("div", class_="tabbed-set"):
        em = tabbed.find("em", string=re.compile(r"^grass\.tools\.Tools\."))
        if em:
            signature = em.parent.get_text() if em.parent else ""
            block = em.parent.parent if em.parent else None
            if block is not None:
                highlight = block.find("div", class_="highlight")
                if highlight:
                    example = "\n".join(
                        line.strip() for line in highlight.get_text().splitlines() if line.strip()
                    )
            break

    params: dict = parse_signature_params(signature)
    h2 = soup.find("h2", id="parameters")
    if h2 and params:
        pset = h2.find_next_sibling("div", class_="tabbed-set")
        if pset:
            blocks = pset.find_all("div", class_="tabbed-block")
            if len(blocks) >= 2:
                for m in PARAM_PATTERN.finditer(str(blocks[1])):
                    if m.group(1) in params and not params[m.group(1)]["type"]:
                        params[m.group(1)]["type"] = m.group(2)

    return title, desc, params, signature, example


def build():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    tools = parse_index(INDEX_HTML.read_text())
    print(f"Index: {len(tools)} tools")

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tools ("
        "rowid INTEGER PRIMARY KEY,"
        "name TEXT UNIQUE NOT NULL,"
        "category TEXT NOT NULL DEFAULT '',"
        "description TEXT NOT NULL DEFAULT '',"
        "signature TEXT NOT NULL DEFAULT '',"
        "example TEXT NOT NULL DEFAULT '',"
        "params_json TEXT NOT NULL DEFAULT '{}'"
        ")"
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS tools_vec USING vec0("
        f"rowid INTEGER PRIMARY KEY, embedding FLOAT[{DIM}] distance_metric=cosine)"
    )

    names = sys.argv[1:] if len(sys.argv) > 1 else [t[0] for t in tools]
    existing = {row[0] for row in conn.execute("SELECT name FROM tools")}
    names = [n for n in names if n not in existing]
    print(f"Processing {len(names)} tools ({len(existing)} already in DB)...")

    done = 0
    skipped = 0
    failed = []
    for name in names:
        meta = next((t for t in tools if t[0] == name), None)
        category = meta[1] if meta else ""
        fallback_desc = meta[2] if meta else ""
        try:
            html = fetch_tool_page(name)
            title, desc, params, signature, example = parse_tool_page(html, fallback_desc)
        except Exception as e:
            print(f"  !! {name}: {e}")
            failed.append(name)
            continue

        if not signature:
            print(f"  -- {name}: no grass.tools signature")
            skipped += 1

        embed_text = " ".join([
            name,
            title,
            desc,
            signature,
            example,
            " ".join(f"{p}:{info.get('type', '')}" for p, info in params.items()),
        ])[:3000]
        embedding = ollama.embeddings(
            model=EMBED_MODEL,
            prompt=embed_text,
            options={"num_ctx": 8192},
        )["embedding"]

        cur = conn.execute(
            "INSERT INTO tools (name, category, description, signature, example, params_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, category, desc, signature, example, json.dumps(params)),
        )
        rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO tools_vec (rowid, embedding) VALUES (?, ?)",
            (rowid, sqlite_vec.serialize_float32(embedding)),
        )
        conn.commit()
        done += 1
        if done % 25 == 0:
            print(f"  ... {done} stored")

    conn.close()

    print(f"\nDone: {done} stored, {skipped} without signature, {len(failed)} failed")
    if failed:
        print("Failed:", ", ".join(failed))


if __name__ == "__main__":
    build()
