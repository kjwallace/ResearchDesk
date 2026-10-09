"""Stage 2 Check for repeats: parsed.json -> redundancy.json, vectors.npy.

Owned by work package 3 (Redundancy). See SPEC.md: Redundancy check; Starting values.

For each email, in arrival order: embed the cleaned body (chunked mean, L2-normalized),
find the most similar earlier email of the same day by cosine, score the two subjects by
token-set similarity, flag a potential repeat, and add the email to the day cache. The flag
is a hint only; stage 4 decides the label. No generative model is called here.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from triage_app import thresholds
from triage_app.embed import Embedder, Vector
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import read_list, write_list
from triage_app.schema import Email, RedundancyRecord

STAGE = "redundancy"


_PREFIX = re.compile(r"^\s*(?:re|fwd|fw)\s*:\s*")
_PUNCT = re.compile(r"[^\w\s]")
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DayCache:
    """Earlier emails of the same day: IDs, normalized subjects and vectors, in arrival order."""

    ids: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    vectors: list[Vector] = field(default_factory=list)

    def add(self, email_id: str, subject: str, vector: Vector) -> None:
        self.ids.append(email_id)
        self.subjects.append(subject)
        self.vectors.append(vector)

    def nearest(self, vector: Vector) -> tuple[str, float, str] | None:
        """(email_id, cosine, normalized subject) of the most similar earlier email, if any."""
        if not self.ids:
            return None
        sims = np.vstack(self.vectors) @ vector
        i = int(np.argmax(sims))
        return self.ids[i], float(sims[i]), self.subjects[i]


def normalize_subject(subject: str) -> str:
    """Lower-case, strip leading re:/fw:/fwd: prefixes repeatedly, strip punctuation."""
    s = subject.lower()
    while (m := _PREFIX.match(s)) is not None:
        s = s[m.end():]
    return " ".join(_PUNCT.sub(" ", s).split())


def subject_similarity(a: str, b: str) -> float:
    """Token-set similarity of two subjects after normalization, 0 to 1."""
    return float(fuzz.token_set_ratio(normalize_subject(a), normalize_subject(b))) / 100.0


def _pack(pieces: list[str], sep: str, budget: int, embedder: Embedder) -> list[str]:
    """Greedily join consecutive pieces while the joined text stays within `budget` tokens."""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{sep}{piece}" if current else piece
        if current and embedder.count_tokens(candidate) > budget:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, embedder: Embedder) -> list[str]:
    """Split text into chunks that fit the embedder's input limit.

    Paragraphs first, then sentences within an oversized paragraph, then words within an
    oversized sentence (a last resort so no chunk is ever truncated by the model).
    """
    budget = max(1, embedder.max_tokens - thresholds.SPECIAL_TOKEN_HEADROOM)
    pieces: list[str] = []
    for para in (p.strip() for p in _PARAGRAPH.split(text)):
        if not para:
            continue
        if embedder.count_tokens(para) <= budget:
            pieces.append(para)
            continue
        for sentence in (s.strip() for s in _SENTENCE.split(para)):
            if not sentence:
                continue
            if embedder.count_tokens(sentence) <= budget:
                pieces.append(sentence)
            else:
                pieces.extend(_pack(sentence.split(), " ", budget, embedder))
    chunks = _pack(pieces, "\n\n", budget, embedder)
    return chunks or [text.strip()]


def email_vector(text: str, embedder: Embedder) -> Vector:
    """Mean of the chunk vectors, L2-normalized, as float32. One embed call for all chunks."""
    rows = embedder.embed(chunk_text(text, embedder))
    mean = rows.mean(axis=0, dtype=np.float64)
    norm = float(np.linalg.norm(mean))
    return (mean / norm if norm else mean).astype(np.float32)


def process(email: Email, day: DayCache, ctx: RunContext) -> RedundancyRecord:
    """Compare one email with the earlier emails in `day` (the day cache), then add it to the cache."""
    vector = email_vector(email.body, ctx.embedder)
    subject = normalize_subject(email.subject)
    found = day.nearest(vector)
    day.add(email.email_id, subject, vector)
    if found is None:
        return RedundancyRecord(email_id=email.email_id, nearest=None, content_similarity=None,
                                subject_score=None, flagged=False)
    nearest_id, content, nearest_subject = found
    subject_score = float(fuzz.token_set_ratio(subject, nearest_subject)) / 100.0
    t = ctx.thresholds
    flagged = content >= t.content_similarity or (
        content >= t.content_similarity_with_subject and subject_score >= t.subject_match)
    return RedundancyRecord(email_id=email.email_id, nearest=nearest_id, content_similarity=content,
                            subject_score=subject_score, flagged=flagged)


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    emails = read_list(in_dir / "parsed.json", Email)
    order = sorted(range(len(emails)), key=lambda i: (emails[i].received_at, i))
    day = DayCache()
    records: dict[int, RedundancyRecord] = {}
    vectors: dict[int, Vector] = {}
    for i in order:
        email = emails[i]
        with ctx.recorder.stage(STAGE, email.email_id):
            records[i] = process(email, day, ctx)
        vectors[i] = day.vectors[-1]
    write_list(out_dir / "redundancy.json", [records[i] for i in range(len(emails))])
    dim = vectors[0].shape[0] if vectors else 0
    matrix = (np.vstack([vectors[i] for i in range(len(emails))]) if emails
              else np.zeros((0, dim), dtype=np.float32))
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "vectors.npy", matrix.astype(np.float32))
