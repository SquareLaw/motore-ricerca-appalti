"""
embeddings.py - Shared embedding helper with rate-limit handling.

Voyage AI's free tier (no payment method on file) allows only 3 requests
per minute. This wraps every embedding call with automatic wait-and-retry
so ingestion scripts pause and continue instead of crashing when that
limit is hit - useful even after adding a payment method, since traffic
spikes can still occasionally get rate-limited.
"""

import time
import voyageai

_MAX_RETRIES = 8
_WAIT_SECONDS = 25  # a little over 60/3=20s to be safe


def _embed_with_retry(client: voyageai.Client, texts: list[str], input_type: str) -> list[float]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return client.embed(texts, model="voyage-3", input_type=input_type).embeddings[0]
        except voyageai.error.RateLimitError:
            if attempt == _MAX_RETRIES:
                raise
            print(f"    (rate limit hit, waiting {_WAIT_SECONDS}s before retry {attempt}/{_MAX_RETRIES}...)")
            time.sleep(_WAIT_SECONDS)


def embed_document(client: voyageai.Client, testo: str) -> list[float]:
    return _embed_with_retry(client, [testo], "document")


def embed_query(client: voyageai.Client, testo: str) -> list[float]:
    return _embed_with_retry(client, [testo], "query")
