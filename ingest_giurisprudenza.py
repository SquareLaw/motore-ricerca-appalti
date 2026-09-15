"""
ingest_giurisprudenza.py - Same scraping logic as before (sentenzeappalti.it),
now writing into the unified 'documenti' table with tipo='giurisprudenza',
so it can be searched together with the statute articles from ingest_norme.py.
"""

import os
import re
import time

import requests
from bs4 import BeautifulSoup
import voyageai

from db import get_conn, create_schema, embedding_to_sql
from embeddings import embed_document

BASE_URL = "https://www.sentenzeappalti.it"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StudioLegaleBot/0.1; ricerca interna)"}
SLEEP_BETWEEN_REQUESTS = 1.5

voyage_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


def get_article_urls_from_tag(tag_slug: str, max_pages: int = 2) -> list[str]:
    urls = []
    for page in range(1, max_pages + 1):
        page_url = f"{BASE_URL}/tag/{tag_slug}/" if page == 1 else f"{BASE_URL}/tag/{tag_slug}/?paged={page}"
        resp = requests.get(page_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        pattern = re.compile(r"^https://www\.sentenzeappalti\.it/\d{4}/\d{2}/\d{2}/[^/]+/$")
        found = {a["href"] for a in soup.find_all("a", href=True) if pattern.match(a["href"])}
        if not found:
            break
        urls.extend(found)
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    return sorted(set(urls))


def parse_article(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    citazione_link, citazione_testo = None, None
    for strong in soup.find_all("strong"):
        link = strong.find("a", href=True)
        if link and "giustizia-amministrativa.it" in link["href"]:
            citazione_link = link["href"]
            citazione_testo = strong.get_text(strip=True)
            break

    corpo = []
    h1 = soup.find("h1")
    if h1:
        for sibling in h1.find_all_next(["p", "h3"]):
            if sibling.name == "h3":
                break
            testo_p = sibling.get_text(strip=True)
            if testo_p and testo_p != citazione_testo:
                corpo.append(testo_p)

    return {
        "url": url,
        "riferimento": citazione_testo or (h1.get_text(strip=True) if h1 else url),
        "testo": "\n".join(corpo),
        "fonte_url": citazione_link or url,
    }


def index_article(dati: dict):
    if not dati["testo"]:
        return
    embedding = embed_document(voyage_client, dati["testo"])

    conn = get_conn()
    try:
        conn.run("""
            INSERT INTO documenti (id, tipo, riferimento, testo, fonte_url, embedding)
            VALUES (:id, 'giurisprudenza', :riferimento, :testo, :fonte_url, :embedding::vector)
            ON CONFLICT (id) DO UPDATE SET
                testo = EXCLUDED.testo, embedding = EXCLUDED.embedding;
        """, id=dati["url"], riferimento=dati["riferimento"], testo=dati["testo"],
             fonte_url=dati["fonte_url"], embedding=embedding_to_sql(embedding))
    finally:
        conn.close()


if __name__ == "__main__":
    create_schema()
    tag = "accesso-agli-atti"
    urls = get_article_urls_from_tag(tag, max_pages=2)
    print(f"Trovati {len(urls)} articoli")
    for url in urls:
        try:
            dati = parse_article(url)
            print(f"  - {dati['riferimento']}")
            index_article(dati)
            time.sleep(0.3)  # light pacing, kept as a courtesy to the API
        except Exception as e:
            print(f"  ERRORE su {url}: {e}")
        time.sleep(SLEEP_BETWEEN_REQUESTS)

