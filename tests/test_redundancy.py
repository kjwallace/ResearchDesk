from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fakes import FIXTURE_EMAILS, FakeEmbedder, fixture_emails

from triage_app import thresholds
from triage_app import config
from triage_app.pipeline import redundancy
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list
from triage_app.pipeline.redundancy import DayCache, email_vector, normalize_subject, subject_similarity
from triage_app.schema import Email, RedundancyRecord

FIXTURES = Path(__file__).parent / "fixtures" / "out"
T0 = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def _ctx(embedder: object | None = None) -> RunContext:
    return RunContext("day_1", embedder=embedder or FakeEmbedder(), use_cache=False, emails_path=FIXTURE_EMAILS)  # type: ignore[arg-type]


def _email(n: int, subject: str, body: str) -> Email:
    return Email(email_id=f"e{n}", received_at=T0 + timedelta(minutes=n), sender="A. Sender",
                 sender_email="a@example.com", subject=subject, body=body)


@pytest.fixture
def fixture_run(tmp_path: Path) -> tuple[list[RedundancyRecord], RunContext]:
    ctx = _ctx()
    redundancy.run(tmp_path, tmp_path, ctx)
    return read_list(tmp_path / "redundancy.json", RedundancyRecord), ctx


def every_comparison() -> list[RedundancyRecord]:
    """What `process` returns for each fixture email in arrival order, flagged or not."""
    ctx, day = _ctx(), DayCache()
    return [redundancy.process(e, day, ctx) for e in fixture_emails()]


def test_file_holds_only_the_flagged_repeat(fixture_run) -> None:  # type: ignore[no-untyped-def]
    records, _ = fixture_run
    assert [r.email_id for r in records] == ["fixture_006"]
    repeat = records[0]
    assert repeat.flagged and repeat.nearest == "fixture_005"
    assert repeat.content_similarity is not None and repeat.content_similarity >= 0.75
    assert [r.email_id for r in every_comparison() if r.flagged] == ["fixture_006"]


def test_no_vectors_are_saved(fixture_run, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["redundancy.json"]


def test_first_email_has_no_nearest() -> None:
    records = every_comparison()
    first = records[0]
    assert first.email_id == "fixture_001"
    assert (first.nearest, first.content_similarity, first.subject_score, first.flagged) == (None, None, None, False)
    assert all(r.nearest is not None for r in records[1:])


def test_output_matches_contract_and_order(fixture_run) -> None:  # type: ignore[no-untyped-def]
    _, ctx = fixture_run
    emails = fixture_emails()
    ids = [e.email_id for e in emails]
    for r in every_comparison():
        RedundancyRecord.model_validate(r.model_dump())
        if r.nearest is not None:
            assert ids.index(r.nearest) < ids.index(r.email_id)  # earlier emails only
            assert r.subject_score is not None and 0.0 <= r.subject_score <= 1.0
    timed = [t.email_id for t in ctx.recorder.timings if t.stage == "redundancy"]
    assert sorted(timed) == sorted(ids)


def test_build_day_cache_matches_the_run() -> None:
    ctx = _ctx()
    day = redundancy.build_day_cache(fixture_emails(), ctx)
    assert day.ids == [e.email_id for e in fixture_emails()]
    copy = day.copy()
    copy.add("x", "x", day.vectors[0])
    assert len(day.ids) == 10 and len(copy.ids) == 11


def test_subject_only_path_flags_between_thresholds() -> None:
    ctx = _ctx()
    t = ctx.thresholds
    shared = " ".join(f"w{i}" for i in range(16))
    first = _email(1, "Alphabet power deal", f"{shared} aa1 aa2 aa3 aa4")
    day = DayCache()
    redundancy.process(first, day, ctx)

    # Same subject; bodies chosen so content lands between the two content thresholds.
    for extra in range(1, 12):
        second = _email(2, "RE: Fwd: Alphabet power deal!",
                        f"{shared} " + " ".join(f"bb{i}" for i in range(extra)))
        probe = DayCache(ids=list(day.ids), subjects=list(day.subjects), vectors=list(day.vectors))
        record = redundancy.process(second, probe, ctx)
        assert record.content_similarity is not None
        if t.content_similarity_with_subject <= record.content_similarity < t.content_similarity:
            break
    else:
        pytest.fail("no body landed between the content thresholds")
    assert record.subject_score == 1.0
    assert record.flagged and record.nearest == "e1"

    # The same content with an unrelated subject is not flagged.
    other = _email(3, "Banking forum invitation", second.body)
    probe = DayCache(ids=list(day.ids), subjects=list(day.subjects), vectors=list(day.vectors))
    unrelated = redundancy.process(other, probe, ctx)
    assert unrelated.subject_score is not None and unrelated.subject_score < t.subject_match
    assert not unrelated.flagged


def test_every_email_is_added_to_the_day_cache() -> None:
    ctx = _ctx()
    day = DayCache()
    body = "same words in both of these emails about nvidia supply"
    redundancy.process(_email(1, "a", body), day, ctx)
    record = redundancy.process(_email(2, "b", body), day, ctx)
    assert record.flagged and day.ids == ["e1", "e2"]


class CountingEmbedder(FakeEmbedder):
    max_tokens = 20

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.batches.append(list(texts))
        return super().embed(texts)


def test_long_body_is_chunked_in_one_embed_call() -> None:
    embedder = CountingEmbedder()
    budget = embedder.max_tokens - thresholds.SPECIAL_TOKEN_HEADROOM
    paragraphs = [" ".join(f"p{p}w{w}" for w in range(5)) + "." for p in range(4)]
    long_sentence = " ".join(f"long{w}" for w in range(40))
    body = "\n\n".join(paragraphs) + "\n\n" + "Short one. " + long_sentence + "."
    vec = email_vector(body, embedder)

    assert len(embedder.batches) == 1
    chunks = embedder.batches[0]
    assert len(chunks) > 1
    assert all(embedder.count_tokens(c) <= budget for c in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(body.split())  # nothing lost
    assert vec.dtype == np.float32 and abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_short_body_is_one_chunk() -> None:
    embedder = CountingEmbedder()
    email_vector("A short note.", embedder)
    assert embedder.batches == [["A short note."]]


@pytest.mark.parametrize(("a", "b", "expected"), [
    ("RE: Fwd: FW: Alphabet power deal!", "alphabet power deal", 1.0),
    ("Re:re: NVDA supply", "nvda supply", 1.0),
    ("Banking forum", "Nvidia supply", None),
])
def test_subject_similarity(a: str, b: str, expected: float | None) -> None:
    score = subject_similarity(a, b)
    assert 0.0 <= score <= 1.0
    if expected is None:
        assert score < thresholds.SUBJECT_MATCH
    else:
        assert score == expected


def test_normalize_subject() -> None:
    assert normalize_subject("Fwd: RE: Alphabet nears 1.2 GW deal?") == "alphabet nears 1 2 gw deal"
    assert normalize_subject("Remarks on capex") == "remarks on capex"  # "re" only as a prefix
