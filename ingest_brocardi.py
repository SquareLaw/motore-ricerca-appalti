"""
ingest_brocardi.py - Loads Brocardi.it's article-by-article commentary on the
Codice dei Contratti Pubblici. Stored as tipo='commento' - explicitly SECONDARY
material (editorial explanation), never treated as the authoritative statute
text (that's what ingest_norme.py, from Normattiva, is for).

Brocardi has one static page per article with a "successivo" (next) link, so
this crawls forward sequentially instead of guessing URLs (article pages live
under different chapter/section slugs, e.g.:
  .../dei-principi-.../dei-principi/i-principi-generali/art1.html
  .../dei-principi-.../della-digitalizzazione-del-ciclo-di-vita-dei-contratti/art35.html
following "successivo" avoids having to know these slugs in advance).

VERIFY BEFORE TRUSTING AT SCALE:
This script's link-following logic (looking for an <a> whose text contains
"successivo") is based on the page structure as read via a text-rendering
fetch, not the raw HTML. If it stops early or loops, inspect the real HTML
of an article page in the browser and adjust the SUCCESSIVO_PATTERN / link
selection below.
"""

import os
import re
import time

import requests
from bs4 import BeautifulSoup
import voyageai

from db import get_conn, create_schema

START_URL = "https://www.brocardi.it/nuovo-codice-appalti/dei-principi-della-digitalizzazione-della-programmazione-della-progettazione/dei-principi/i-principi-generali/art1.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StudioLegaleBot/0.1; ricerca interna)"}
SLEEP_BETWEEN_REQUESTS = 1.5
MAX_ARTICLES = 260  # safety cap - the code has ~229 articles + allegati

voyage_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
SUCCESSIVO_PATTERN = re.compile(r"successiv", re.IGNORECASE)


def find_next_url(soup: BeautifulSoup, current_url: str) -> str | None:
    for a in soup.find_all("a", href=True):
        if SUCCESSIVO_PATTERN.search(a.get_text()):
            href = a["href"]
            if href.startswith("http"):
                return href
            # relative link - resolve against the article's own directory
            base = current_url.rsplit("/", 1)[0]
            return f"{base}/{href.lstrip('/')}"
    return None


def parse_article(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    h1 = soup.find("h1")
    titolo = h1.get_text(strip=True) if h1 else url

    match = re.search(r"art(\d+[\w\-]*)\.html", url)
    numero_articolo = match.group(1) if match else "?"

    # Prendiamo tutto il testo dei paragrafi principali della pagina come
    # blocco unico (norma + commento insieme) - e' materiale secondario,
    # non serve separarlo dal testo ufficiale che abbiamo gia' da Normattiva.
    paragrafi = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
    testo = "\n".join(paragrafi)

    return {
        "url": url,
        "riferimento": f"Art. {numero_articolo} (commento Brocardi) - {titolo}",
        "testo": testo,
    }


def index_article(dati: dict):
    if not dati["testo"]:
        return
    embedding = voyage_client.embed(
        [dati["testo"]], model="voyage-3", input_type="document"
    ).embeddings[0]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO documenti (id, tipo, riferimento, testo, fonte_url, embedding)
            VALUES (%s, 'commento', %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                testo = EXCLUDED.testo, embedding = EXCLUDED.embedding;
        """, (dati["url"], dati["riferimento"], dati["testo"], dati["url"], embedding))
        conn.commit()


if __name__ == "__main__":
    create_schema()
    url = START_URL
    count = 0

    while url and count < MAX_ARTICLES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            dati = parse_article(url)
            print(f"  - {dati['riferimento']}")
            index_article(dati)

            url = find_next_url(soup, url)
            count += 1
        except Exception as e:
            print(f"  ERRORE su {url}: {e}")
            break
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"Totale articoli commentati indicizzati: {count}")
