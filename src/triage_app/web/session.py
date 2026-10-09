"""Per-visitor session state, held in server memory and keyed by a signed session cookie.

Holds the change log, dismissed suggestions and reviews, live-run times, verify results,
and whatever live runs and "this mattered" added to the visitor's brief. A restart clears
every session. Reset clears the visitor's state but keeps the live-run times, so it cannot
be used to lift the rate limit.
"""

import secrets
import threading
import time
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


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(18)

    def get(self, sid: str) -> SessionState:
        with self._lock:
            return self._sessions.setdefault(sid, SessionState())
