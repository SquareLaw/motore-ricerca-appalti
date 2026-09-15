"""
app.py - Merged search: retrieves top statute articles AND top case law
separately (so the statute isn't crowded out by more numerous case law
chunks), then asks Claude to write one short synthesized summary citing both.
"""

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import voyageai
import anthropic

from db import get_conn, embedding_to_sql
from embeddings import embed_query

app = FastAPI()

voyage_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def embed(testo: str) -> list[float]:
    return embed_query(voyage_client, testo)


def retrieve(query: str, tipo: str, top_k: int = 4) -> list[dict]:
    """Hybrid search restricted to one content type ('norma', 'giurisprudenza', 'commento')."""
    query_vector_sql = embedding_to_sql(embed(query))
    conn = get_conn()
    try:
        rows = conn.run("""
            SELECT tipo, riferimento, testo, fonte_url
            FROM documenti
            WHERE tipo = :tipo
            ORDER BY (
                0.4 * ts_rank(search_vector, plainto_tsquery('italian', :query))
                + 0.6 * (1 - (embedding <=> :query_vector::vector))
            ) DESC
            LIMIT :top_k;
        """, tipo=tipo, query=query, query_vector=query_vector_sql, top_k=top_k)
        columns = [c["name"] for c in conn.columns]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


class SearchRequest(BaseModel):
    query: str


@app.post("/search")
def search(req: SearchRequest):
    norme = retrieve(req.query, "norma", top_k=4)
    giurisprudenza = retrieve(req.query, "giurisprudenza", top_k=4)
    commenti = retrieve(req.query, "commento", top_k=3)

    if not norme and not giurisprudenza and not commenti:
        return {"summary": "Nessun risultato trovato nel corpus indicizzato.", "norme": [], "giurisprudenza": [], "commenti": []}

    contesto_norme = "\n\n".join(f"[Norma: {n['riferimento']}]\n{n['testo']}" for n in norme)
    contesto_giurisprudenza = "\n\n".join(
        f"[Giurisprudenza: {g['riferimento']}]\n{g['testo']}" for g in giurisprudenza
    )
    contesto_commenti = "\n\n".join(
        f"[Commento editoriale (secondario): {c['riferimento']}]\n{c['testo']}" for c in commenti
    )

    system_prompt = (
        "Sei un assistente di ricerca giuridica per uno studio legale italiano, "
        "specializzato in appalti pubblici. Ti vengono fornite tre categorie di "
        "fonti, con affidabilita' diversa: (1) NORME - testo ufficiale di legge, "
        "massima autorevolezza; (2) GIURISPRUDENZA - massime di sentenze, "
        "seconda per autorevolezza; (3) COMMENTI - spiegazioni editoriali di "
        "terzi, utili per il contesto ma MAI da citare come fonte di diritto "
        "autonoma - usale solo per chiarire, non come base di un'affermazione "
        "giuridica che non trova riscontro nelle norme o nella giurisprudenza. "
        "Scrivi una SINTESI BREVE (150-250 parole) che integri norme e "
        "giurisprudenza, usando i commenti solo come sfondo esplicativo. "
        "Rispondi ESCLUSIVAMENTE sulla base delle fonti fornite - se sono "
        "insufficienti, dillo esplicitamente. Non inventare articoli o sentenze "
        "non presenti nelle fonti. Cita tra parentesi quadre la fonte per ogni "
        "affermazione, es. [Art. 35] o [TAR Torino n. 1455/2026]."
    )

    user_message = (
        f"NORME:\n{contesto_norme or '(nessuna norma pertinente trovata)'}\n\n"
        f"GIURISPRUDENZA:\n{contesto_giurisprudenza or '(nessuna sentenza pertinente trovata)'}\n\n"
        f"COMMENTI (secondari):\n{contesto_commenti or '(nessun commento pertinente trovato)'}\n\n"
        f"Domanda: {req.query}"
    )

    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    summary = "".join(block.text for block in response.content if block.type == "text")

    return {
        "summary": summary,
        "norme": [{"riferimento": n["riferimento"], "url": n["fonte_url"]} for n in norme],
        "giurisprudenza": [{"riferimento": g["riferimento"], "url": g["fonte_url"]} for g in giurisprudenza],
        "commenti": [{"riferimento": c["riferimento"], "url": c["fonte_url"]} for c in commenti],
    }


@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()
