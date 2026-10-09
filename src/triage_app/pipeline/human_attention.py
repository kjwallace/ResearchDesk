"""Stage A Write attention notes: the corpus emails, results.json -> notes.json.

Owned by work package 5 (Attention notes). See SPEC.md: Attention pathway.

Every email that stage 4 flagged for human attention gets one note. The note explains the
flag and cannot remove it; it never touches the book. Each quoted section is checked by
string match against the email body: failing sections are dropped and counted, the note
stays. `run` prints one summary line with the drop count; `write_note` returns it per email.
"""

from pathlib import Path

from triage_app.modules.attention import AttentionWriter
from triage_app.pipeline.context import RunContext
from triage_app.pipeline.io import quote_in, read_list, write_list
from triage_app.schema import AttentionNote, Email, EmailResult, LinkedSection, NoteDraft

STAGE = "human_attention"


def run(in_dir: Path, out_dir: Path, ctx: RunContext) -> None:
    emails = {e.email_id: e for e in ctx.emails}
    results = read_list(in_dir / "results.json", EmailResult)
    flagged = [r for r in results if r.human_attention]
    writer = AttentionWriter(ctx.chat) if flagged else None
    notes: list[AttentionNote] = []
    dropped = 0
    for result in flagged:
        with ctx.recorder.stage(STAGE, result.email_id):
            note, n = write_note(emails[result.email_id], result, ctx, writer=writer)
        notes.append(note)
        dropped += n
    write_list(out_dir / "notes.json", notes)
    print(f"[{ctx.corpus_set}] {STAGE}: {len(notes)} notes, {dropped} sections dropped "
          f"(quote not found in body)", flush=True)


def process(email: Email, result: EmailResult, ctx: RunContext) -> AttentionNote:
    """A note for one flagged email; sections failing the string match are dropped and counted."""
    return write_note(email, result, ctx)[0]


def write_note(email: Email, result: EmailResult, ctx: RunContext, *,
               writer: AttentionWriter | None = None) -> tuple[AttentionNote, int]:
    """The note and the number of sections dropped for failing the string match."""
    assert result.email_id == email.email_id, "result and email do not match"
    assert result.human_attention, f"{email.email_id} is not flagged for attention"
    assert result.gate != "quarantine", f"{email.email_id} is quarantined; its body reaches no model"
    draft = (writer or AttentionWriter(ctx.chat))(email)
    return build_note(email, draft)


def build_note(email: Email, draft: NoteDraft) -> tuple[AttentionNote, int]:
    """Code builds the stored note: keep sections found verbatim in the body, link them to the email."""
    kept = [LinkedSection(email_id=email.email_id, quote=s.quote)
            for s in draft.sections if quote_in(s.quote, email.body)]
    note = AttentionNote(email_id=email.email_id, summary=draft.summary,
                         why_attention=draft.why_attention, action=draft.action,
                         deadline=draft.deadline, sections=kept)
    return note, len(draft.sections) - len(kept)
