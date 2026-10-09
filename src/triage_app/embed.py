"""The one embedder: a Hugging Face model, pulled from the Hub and run locally.

The model is the repo ID in .env as EMBEDDING_MODEL (sentence-transformers). Used by the
redundancy check (stage 2), the duplicate and merge checks for new theses (stages 7 and 8)
and the verify agent's filing search. Each text's vector is cached on disk and every batch
is recorded by monitoring. Vectors are L2-normalized, so a dot product is cosine similarity.

Tests pass a fake with the same `embed` / `count_tokens` / `max_tokens` surface.
"""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from triage_app import thresholds
from triage_app import config
from triage_app.cache import DiskCache
from triage_app.monitoring import Recorder, cached_call

Vector = NDArray[np.float32]


class Embedder(Protocol):
    model: str
    max_tokens: int

    def count_tokens(self, text: str) -> int: ...

    def embed(self, texts: list[str]) -> Vector: ...  # shape (len(texts), dim), normalized


class HFEmbedder:
    def __init__(self, model: str | None = None, *, cache: DiskCache | None = None,
                 use_cache: bool = True, recorder: Recorder | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = model or config.EMBEDDING_MODEL
        self._st = SentenceTransformer(self.model)
        self.max_tokens = int(self._st.max_seq_length or thresholds.EMBEDDING_MAX_TOKENS)
        self.cache = (cache or DiskCache()) if use_cache else None
        self.recorder = recorder

    def count_tokens(self, text: str) -> int:
        return len(self._st.tokenizer(text, add_special_tokens=True)["input_ids"])

    def _encode(self, text: str) -> list[float]:
        vec = self._st.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
        return [float(x) for x in vec]

    def embed(self, texts: list[str]) -> Vector:
        rows = []
        for text in texts:
            rows.append(cached_call(
                namespace="embed", model=self.model, payload={"model": self.model, "text": text},
                call=lambda t=text: self._encode(t),  # type: ignore[misc]
                dump=lambda v: v, load=lambda v: list(v),
                usage=lambda _v, t=text: (self.count_tokens(t), 0),  # type: ignore[misc]
                input_text=text, cache=self.cache, recorder=self.recorder,
            ))
        return np.asarray(rows, dtype=np.float32)
