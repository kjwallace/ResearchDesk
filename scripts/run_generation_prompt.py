"""Run one generation prompt from prompts/ with the analysis model (via OpenRouter) and write its drafts.

Sends only the text below the prompt's first '---' line. Output written:
  - for multi-file prompts, each '=== <path> ===' block to <path> under the repo root;
  - for --json-out, the single JSON document to that path.
The request and the raw response are saved under transcripts/generation/.

Reads OPENROUTER_API_KEY from the environment or .env. Never prints it.

Usage:
    uv run python scripts/run_generation_prompt.py prompts/01_book.prompt.md --json-out data/seed/models_draft.json
    uv run python scripts/run_generation_prompt.py prompts/02_jev_criteria.prompt.md
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from triage_app import config  # noqa: E402
from triage_app.llm import Message, OpenRouterClient  # noqa: E402

BLOCK = re.compile(r"^=== (\S+) ===\s*$", re.MULTILINE)


def prompt_body(path: Path) -> str:
    text = path.read_text()
    parts = re.split(r"^---\s*$", text, maxsplit=1, flags=re.MULTILINE)
    if len(parts) != 2:
        raise SystemExit(f"{path}: no '---' line found")
    return parts[1].strip()


def strip_fence(text: str) -> str:
    m = re.match(r"^\s*```[a-zA-Z]*\n(.*)\n```\s*$", text, re.DOTALL)
    return m.group(1) if m else text


def split_files(text: str) -> dict[str, str]:
    marks = list(BLOCK.finditer(text))
    if not marks:
        raise SystemExit("response holds no '=== <path> ===' blocks")
    files: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        files[m.group(1)] = strip_fence(text[m.end():end].strip()).strip() + "\n"
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", type=Path)
    parser.add_argument("--json-out", type=Path, help="write the single JSON document here")
    parser.add_argument("--model", default=None, help="defaults to ANALYSIS_MODEL from .env")
    parser.add_argument("--max-tokens", type=int, default=32000)
    parser.add_argument("--extra", default="", help="extra text appended to the prompt body")
    args = parser.parse_args()

    body = prompt_body(args.prompt)
    if args.extra:
        body = f"{body}\n\n{args.extra}"

    completion = OpenRouterClient().complete(
        model=args.model or config.ANALYSIS_MODEL, max_tokens=args.max_tokens,
        messages=[Message(role="user", content=body)], namespace="generation",
    )
    text = completion.text

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_dir = ROOT / "transcripts" / "generation"
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}_{args.prompt.stem}"
    (log_dir / f"{stem}.request.md").write_text(body)
    (log_dir / f"{stem}.response.md").write_text(text)
    (log_dir / f"{stem}.meta.json").write_text(json.dumps({
        "model": completion.model,
        "input_tokens": completion.input_tokens, "output_tokens": completion.output_tokens,
    }, indent=2))

    written: list[str] = []
    if args.json_out:
        doc = json.loads(strip_fence(text.strip()))
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(doc, indent=2) + "\n")
        written.append(str(args.json_out))
    else:
        for rel, content in split_files(text).items():
            out = (ROOT / rel).resolve()
            if ROOT not in out.parents:
                raise SystemExit(f"refusing to write outside the repo: {rel}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content)
            written.append(rel)
    print(f"model={completion.model} in={completion.input_tokens} out={completion.output_tokens}")
    print("wrote:", *written, sep="\n  ")


if __name__ == "__main__":
    main()
