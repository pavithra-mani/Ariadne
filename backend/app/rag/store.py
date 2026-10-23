"""ChromaDB access (embedded persistent client; in Docker the path is a mounted volume)."""
import hashlib
import math
import re
from functools import lru_cache

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from app.config import settings


class HashEmbedding(EmbeddingFunction):
    """Offline fallback: hashed bag-of-words. Only used if the MiniLM model cannot load."""

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        out = []
        for text in input:
            v = [0.0] * 256
            for w in re.findall(r"[a-z]+", text.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    @staticmethod
    def name() -> str:
        return "ariadne_hash"


@lru_cache
def client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_path)


@lru_cache
def embedder():
    try:
        from chromadb.utils import embedding_functions as ef
        fn = ef.DefaultEmbeddingFunction()
        fn(["warm up"])
        return fn
    except Exception:  # offline / model unavailable
        return HashEmbedding()


def collection(name: str):
    return client().get_or_create_collection(
        name, embedding_function=embedder(), metadata={"hnsw:space": "cosine"})


def reset_collection(name: str):
    try:
        client().delete_collection(name)
    except Exception:
        pass
    return collection(name)
