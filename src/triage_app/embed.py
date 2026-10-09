"""The one embedder: a Hugging Face model run locally, or a model served by OpenRouter.

The model is EMBEDDING_MODEL in .env: a Hugging Face repo ID (sentence-transformers, the
default, `HFEmbedder`) or, with EMBEDDING_BACKEND=openrouter, an OpenRouter slug
(`RemoteEmbedder`, for hosts that cannot hold a local model). Used by the
redundancy check (stage 2), the duplicate and merge checks for new theses (stages 7 and 8)
and the verify agent's filing search. Each text's vector is cached on disk and every batch
is recorded by monitoring. Vectors are L2-normalized, so a dot product is cosine similarity.

Tests pass a fake with the same `embed` / `count_tokens` / `max_tokens` surface.
"""

import math
import os
import time
from typing import Any, Protocol

import httpx
import numpy as np
from numpy.typing import NDArray

from triage_app import thresholds
from triage_app import config
from triage_app.cache import DiskCache, cache_key
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
        return np.asarray([self._embed_one(text) for text in texts], dtype=np.float32)

    def _embed_one(self, text: str) -> list[float]:
        return cached_call(
            namespace="embed", model=self.model, payload={"model": self.model, "text": text},
            call=lambda: self._encode(text),
            dump=lambda v: v, load=lambda v: list(v),
            usage=lambda _v: (self.count_tokens(text), 0),
            input_text=text, cache=self.cache, recorder=self.recorder,
        )



class RemoteEmbedder:
    """Embeddings from a model served by OpenRouter, for hosts that cannot run a local model.

    Same interface and caching as `HFEmbedder`. There is no tokenizer here, so tokens are
    estimated from characters, conservatively, which keeps every chunk under the model's
    input limit. Uncached texts go out in batches; each text is then cached on its own.
    Selected with EMBEDDING_BACKEND=openrouter; EMBEDDING_MODEL is an OpenRouter slug.
    """

    def __init__(self, model: str | None = None, *, api_key: str | None = None, base_url: str | None = None,
                 cache: DiskCache | None = None, use_cache: bool = True, recorder: Recorder | None = None,
                 timeout: float = thresholds.EMBED_TIMEOUT_S) -> None:
        from triage_app.llm import DEFAULT_BASE_URL

        self.model = model or config.EMBEDDING_MODEL
        self.max_tokens = thresholds.REMOTE_EMBED_MAX_TOKENS
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.cache = (cache or DiskCache()) if use_cache else None
        self.recorder = recorder
        self.timeout = timeout

    def count_tokens(self, text: str) -> int:
        return math.ceil(len(text) / thresholds.REMOTE_CHARS_PER_TOKEN)

    def _post(self, texts: list[str]) -> list[list[float]]:
        from triage_app.llm import _retry_delay

        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        body = {"model": self.model, "input": texts}
        for attempt in range(thresholds.LLM_MAX_RETRIES + 1):
            try:
                resp = httpx.post(f"{self.base_url}/embeddings", json=body, timeout=self.timeout,
                                  headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
            except httpx.TransportError:
                if attempt == thresholds.LLM_MAX_RETRIES:
                    raise
                time.sleep(min(thresholds.LLM_RETRY_BASE_S * 2 ** attempt, thresholds.LLM_RETRY_MAX_S))
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < thresholds.LLM_MAX_RETRIES:
                time.sleep(_retry_delay(resp, attempt))
                continue
            break
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenRouter embeddings {resp.status_code}: {resp.text[:300]}")
        rows = sorted(resp.json()["data"], key=lambda r: r.get("index", 0))
        if len(rows) != len(texts):
            raise RuntimeError(f"OpenRouter embeddings returned {len(rows)} vectors for {len(texts)} texts")
        out: list[list[float]] = []
        for row in rows:
            vec = np.asarray(row["embedding"], dtype=np.float64)
            norm = float(np.linalg.norm(vec))
            out.append([float(x) for x in (vec / norm if norm else vec)])
        return out

    def _post_trimmed(self, text: str) -> list[float]:
        while True:
            try:
                return self._post([text])[0]
            except RuntimeError as e:
                if "context length" not in str(e) or len(text) < 32:
                    raise
                text = text[: int(len(text) * 0.85)]

    def _payload(self, text: str) -> dict[str, Any]:
        return {"model": self.model, "text": text}

    def embed(self, texts: list[str]) -> Vector:
        fetched: dict[str, list[float]] = {}
        if self.cache is not None:
            pending = [t for t in dict.fromkeys(texts)
                       if self.cache.get("embed", cache_key("embed", self._payload(t))) is None]
        else:
            pending = list(dict.fromkeys(texts))
        for i in range(0, len(pending), thresholds.REMOTE_EMBED_BATCH):
            batch = pending[i:i + thresholds.REMOTE_EMBED_BATCH]
            try:
                fetched.update(zip(batch, self._post(batch), strict=True))
            except RuntimeError as e:
                if "context length" not in str(e):
                    raise
                for text in batch:   # a chunk the estimate let through is cut until the model accepts it
                    fetched[text] = self._post_trimmed(text)
        return np.asarray([self._embed_one(t, fetched) for t in texts], dtype=np.float32)

    def _embed_one(self, text: str, fetched: dict[str, list[float]]) -> list[float]:
        return cached_call(
            namespace="embed", model=self.model, payload=self._payload(text),
            call=lambda: fetched[text] if text in fetched else self._post([text])[0],
            dump=lambda v: v, load=lambda v: list(v),
            usage=lambda _v: (None, None), input_text=text, cache=self.cache, recorder=self.recorder,
        )
