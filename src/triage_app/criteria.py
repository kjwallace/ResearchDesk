"""Load, check and hash the relevance criteria files in criteria/.

Each file looks like:

    # <label>

    ## Definition
    <fixed text from the corpus prompt>

    ## Rules
    - R1: <one sentence>
    - R2: <one sentence that may wrap
          onto an indented line>

See SPEC.md, "Relevance criteria".
"""

import hashlib
import re
from pathlib import Path

from triage_app.config import CRITERIA_DIR, CRITERIA_FILES, TICKERS
from triage_app.thresholds import RULES_PER_CRITERIA_FILE
from triage_app.schema import CriteriaRule, CriteriaSet, LabelCriteria


class CriteriaError(ValueError):
    pass


_RULE = re.compile(r"^-\s+(R\d+):\s*(.*)$")
_BOOK_ID = re.compile(rf"\b(?:{'|'.join(TICKERS)})\.(?:p\d+|[a-z][a-z_]+)\b")


def parse_file(path: Path) -> LabelCriteria:
    label = path.stem
    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0].strip() != f"# {label}":
        raise CriteriaError(f"{path.name}: first line must be '# {label}'")

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                raise CriteriaError(f"{path.name}: duplicate section '{current}'")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            raise CriteriaError(f"{path.name}: text before the first section")
    if set(sections) != {"Definition", "Rules"}:
        raise CriteriaError(f"{path.name}: needs exactly '## Definition' and '## Rules'")

    definition = " ".join(s.strip() for s in sections["Definition"] if s.strip())
    if not definition:
        raise CriteriaError(f"{path.name}: empty definition")

    rules: list[CriteriaRule] = []
    for line in sections["Rules"]:
        if not line.strip():
            continue
        m = _RULE.match(line)
        if m:
            rules.append(CriteriaRule(id=m.group(1), text=m.group(2).strip()))
        elif line.startswith((" ", "\t")) and rules:
            last = rules[-1]
            rules[-1] = CriteriaRule(id=last.id, text=f"{last.text} {line.strip()}")
        else:
            raise CriteriaError(f"{path.name}: cannot parse rule line {line!r}")

    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise CriteriaError(f"{path.name}: duplicate rule IDs")
    if len(rules) > RULES_PER_CRITERIA_FILE:
        raise CriteriaError(f"{path.name}: {len(rules)} rules; at most {RULES_PER_CRITERIA_FILE}")
    found = _BOOK_ID.search(text)
    if found:
        raise CriteriaError(f"{path.name}: names a book item {found.group(0)!r}; rules hold kinds of information, never views")
    return LabelCriteria(label=label, definition=definition, rules=rules)


def version_of(files: dict[str, str]) -> str:
    """Hash of every file's name and full text, in name order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(b"\0")
        h.update(files[name].encode())
        h.update(b"\0")
    return h.hexdigest()[:12]


def read_files(directory: Path = CRITERIA_DIR) -> dict[str, str]:
    return {f"{name}.md": (directory / f"{name}.md").read_text() for name in CRITERIA_FILES}


def load(directory: Path = CRITERIA_DIR) -> CriteriaSet:
    missing = [n for n in CRITERIA_FILES if not (directory / f"{n}.md").exists()]
    if missing:
        raise CriteriaError(f"missing criteria files: {', '.join(missing)}")
    labels = {n: parse_file(directory / f"{n}.md") for n in CRITERIA_FILES}
    return CriteriaSet(version=version_of(read_files(directory)), labels=labels)


def criteria_text(criteria: CriteriaSet, label: str) -> str:
    """A label's definition and rules as written; the text Jev receives for it."""
    c = criteria.labels[label]
    return "\n".join([c.definition, *(f"{r.id}: {r.text}" for r in c.rules)])
