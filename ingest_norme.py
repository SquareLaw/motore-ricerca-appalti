"""
ingest_norme.py - Loads the Codice dei Contratti Pubblici (D.Lgs. 36/2023)
into the database, one row per article, using normattiva2md to get clean
per-article text from the official Akoma Ntoso XML on normattiva.it.

Install first:
    pip install normattiva2md

IMPORTANT - verify before trusting this at scale:
normattiva2md outputs Markdown with a heading hierarchy (H1-H4). This script
assumes article headings look like "## Art. 35" or "### Articolo 35" and
splits on that pattern. Run it once, open the generated codice.md, and check
that the split actually lines up with real article boundaries before relying
on the output - heading conventions can vary depending on how nested a given
law's structure is (parts / titles / chapters / articles).
"""

import os
import re
import subprocess

from db import get_conn, create_schema
import voyageai

NORMATTIVA_URL = "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2023-03-31;36"
OUTPUT_FILE = "codice_contratti_pubblici.md"

voyage_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

ARTICLE_HEADING = re.compile(r"^#{1,4}\s*(Art(?:icolo)?\.?\s*\d+[\w\-]*)", re.MULTILINE)


def download_markdown():
    """Calls the normattiva2md CLI tool to fetch and convert the law."""
    subprocess.run(["normattiva2md", NORMATTIVA_URL, OUTPUT_FILE], check=True)
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        return f.read()


def split_by_article(markdown_text: str) -> list[dict]:
    """Splits the Markdown on article headings. Each chunk = one article."""
    matches = list(ARTICLE_HEADING.finditer(markdown_text))
    articoli = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        testo = markdown_text[start:end].strip()
        riferimento = match.group(1).strip()
        articoli.append({"riferimento": riferimento, "testo": testo})
    return articoli


def index_article(articolo: dict):
    doc_id = f"norma-{articolo['riferimento']}"
    embedding = voyage_client.embed(
        [articolo["testo"]], model="voyage-3", input_type="document"
    ).embeddings[0]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO documenti (id, tipo, riferimento, testo, fonte_url, embedding)
            VALUES (%s, 'norma', %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                testo = EXCLUDED.testo, embedding = EXCLUDED.embedding;
        """, (doc_id, articolo["riferimento"], articolo["testo"], NORMATTIVA_URL, embedding))
        conn.commit()


if __name__ == "__main__":
    create_schema()
    print("Scaricando il Codice dei Contratti Pubblici da Normattiva...")
    markdown_text = download_markdown()

    articoli = split_by_article(markdown_text)
    print(f"Trovati {len(articoli)} articoli (verificare a campione la correttezza dello split)")

    for art in articoli:
        print(f"  - {art['riferimento']}")
        index_article(art)
