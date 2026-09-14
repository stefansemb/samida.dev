import httpx

from samida.config import Settings

_DEFAULT_MODEL = "nomic-embed-text"


async def embed_text(text: str, settings: Settings) -> list[float] | None:
    """Embed a string via a local Ollama model. Returns None (never raises)
    if Ollama is unreachable, the model isn't pulled, or the response is
    malformed - callers must degrade to keyword-only behavior, not break."""
    model = settings.embedding_model or _DEFAULT_MODEL
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        return None
    return embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
