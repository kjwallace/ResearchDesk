"""Per-visitor session state, held in server memory and keyed by a signed session cookie.

Holds the change log, dismissed suggestions and reviews, live-run times, verify results,
and whatever live runs and "this mattered" added to the visitor's brief. A restart clears
every session. Reset clears the visitor's state but keeps the live-run times, so it cannot
be used to lift the rate limit.

Live runs are limited only across the whole process (`thresholds.LIVE_RUNS_PER_HOUR_GLOBAL`);
there is no per-visitor limit (DECISIONS #122), so `runs_left` / `take_run` are no longer used
by the app. Idle sessions are evicted after `thresholds.SESSION_IDLE_TTL_S`, and the store holds at
most `thresholds.MAX_SESSIONS`, evicting the least recently used.
"""

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from triage_app import thresholds
from triage_app.schema import AttentionNote, Claim, Email, EmailResult, LogEntry, Suggestion, VerifyResult

SESSION_KEY = "sid"


@dataclass
class SessionState:
    log: list[LogEntry] = field(default_factory=list)
    dismissed: set[str] = field(default_factory=set)
    live_runs: list[float] = field(default_factory=list)
    verify: dict[str, VerifyResult] = field(default_factory=dict)
    # Added to this session's brief by the live route and "this mattered".
    emails: dict[str, Email] = field(default_factory=dict)
    results: dict[str, EmailResult] = field(default_factory=dict)
    notes: dict[str, AttentionNote] = field(default_factory=dict)
    suggestions: dict[str, Suggestion] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    mattered: dict[str, str] = field(default_factory=dict)  # email ID to outcome line
    handled: dict[str, str] = field(default_factory=dict)   # attention email ID to "responded" or "rejected"

    def reset(self) -> None:
        self.__dict__.update(SessionState(live_runs=self.live_runs).__dict__)

    def runs_left(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        self.live_runs = [t for t in self.live_runs if now - t < thresholds.LIVE_RATE_WINDOW_S]
        return max(0, thresholds.LIVE_RUNS_PER_HOUR - len(self.live_runs))

    def take_run(self, now: float | None = None) -> bool:
        """Spend one live run from the hourly allowance; False when none is left."""
        now = time.time() if now is None else now
        if self.runs_left(now) <= 0:
            return False
        self.live_runs.append(now)
        return True


def _prune(times: list[float], now: float) -> list[float]:
    return [t for t in times if now - t < thresholds.LIVE_RATE_WINDOW_S]


class GlobalRuns:
    """Live runs across every session in this process, within the rate window."""

    def __init__(self) -> None:
        self.times: list[float] = []
        self._lock = threading.Lock()

    def left(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            self.times = _prune(self.times, now)
            return max(0, thresholds.LIVE_RUNS_PER_HOUR_GLOBAL - len(self.times))

    def take(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            self.times = _prune(self.times, now)
            if len(self.times) >= thresholds.LIVE_RUNS_PER_HOUR_GLOBAL:
                return False
            self.times.append(now)
            return True

    def refund(self) -> None:
        with self._lock:
            if self.times:
                self.times.pop()


class SessionStore:
    """Sessions by ID, least recently used first; idle ones are evicted on access."""

    def __init__(self) -> None:
        self._sessions: OrderedDict[str, tuple[float, SessionState]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(18)

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, sid: object) -> bool:
        return sid in self._sessions

    def get(self, sid: str, now: float | None = None) -> SessionState:
        now = time.time() if now is None else now
        with self._lock:
            while self._sessions:
                oldest, (seen, _) = next(iter(self._sessions.items()))
                if now - seen < thresholds.SESSION_IDLE_TTL_S:
                    break
                del self._sessions[oldest]
            state = self._sessions.pop(sid, (now, SessionState()))[1]
            self._sessions[sid] = (now, state)
            while len(self._sessions) > thresholds.MAX_SESSIONS:
                self._sessions.popitem(last=False)
            return state
