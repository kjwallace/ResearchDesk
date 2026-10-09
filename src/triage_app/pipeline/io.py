"""Read and write stage files: each is a JSON list of one contract, or a single object."""

import json
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def read_list(path: Path, model: type[M]) -> list[M]:
    return [model.model_validate(item) for item in json.loads(path.read_text())]


def write_list(path: Path, items: list[M]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i.model_dump(mode="json") for i in items], indent=2, ensure_ascii=False) + "\n")


def read_one(path: Path, model: type[M]) -> M:
    return model.model_validate_json(path.read_text())


def write_one(path: Path, item: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(item.model_dump_json(indent=2) + "\n")


_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to one space; the form quotes are checked in."""
    return _WS.sub(" ", text).strip()


def quote_in(quote: str, body: str) -> bool:
    """True when `quote` appears verbatim in `body` after whitespace normalization."""
    q = normalize_ws(quote)
    return bool(q) and q in normalize_ws(body)
