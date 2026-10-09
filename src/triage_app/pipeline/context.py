"""What every stage's `run` receives besides its directories: clients, settings, monitoring.

Clients are built lazily on first use, so a stage that needs no model never loads one,
and tests pass fakes in their place:

    ctx = RunContext(corpus_set="day_1", chat=FakeChat(...), embedder=FakeEmbedder(), jev=FakeJev(...))
"""

from typing import Any

from triage_app import config
from triage_app.cache import DiskCache
from triage_app.config import CorpusSet
from triage_app.embed import Embedder
from triage_app.llm import ChatClient
from triage_app.monitoring import Recorder
from triage_app.schema import CriteriaSet, Thresholds


class RunContext:
    def __init__(self, corpus_set: CorpusSet | None = None, *, recorder: Recorder | None = None,
                 cache: DiskCache | None = None, use_cache: bool = True, chat: ChatClient | None = None,
                 embedder: Embedder | None = None, jev: Any | None = None,
                 criteria: CriteriaSet | None = None, thresholds: Thresholds | None = None) -> None:
        self.corpus_set = corpus_set
        self.recorder = recorder or Recorder()
        self.cache = (cache or DiskCache()) if use_cache else None
        self._chat, self._embedder, self._jev = chat, embedder, jev
        self._criteria, self._thresholds = criteria, thresholds

    @property
    def chat(self) -> ChatClient:
        """OpenRouter chat client for every generative call."""
        if self._chat is None:
            from triage_app.llm import OpenRouterClient
            self._chat = OpenRouterClient(cache=self.cache, use_cache=self.cache is not None,
                                          recorder=self.recorder)
        return self._chat

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            from triage_app.embed import HFEmbedder
            self._embedder = HFEmbedder(cache=self.cache, use_cache=self.cache is not None,
                                        recorder=self.recorder)
        return self._embedder

    @property
    def jev(self) -> Any:
        """TypeSafe client for stage 3 (Jev). The classify module wraps calls in cached_call."""
        if self._jev is None:
            from dotenv import load_dotenv
            from typesafe_sdk import TypeSafeClient
            load_dotenv(config.ROOT / ".env")
            self._jev = TypeSafeClient(model=config.JEV_MODEL)
        return self._jev

    @property
    def criteria(self) -> CriteriaSet:
        if self._criteria is None:
            from triage_app.criteria import load
            self._criteria = load()
        return self._criteria

    @property
    def thresholds(self) -> Thresholds:
        if self._thresholds is None:
            self._thresholds = config.load_thresholds()
        return self._thresholds
