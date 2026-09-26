"""Prompt token ids through the base model's chat template (thinking disabled).

`python -m pocketsql.data.tokens --write` regenerates the ids in
packages/sqlgen/fixtures/tokens.json from the golden fixtures; the Python and
Transformers.js tests both compare against that file.
"""

import argparse
import json
from functools import cache

from transformers import AutoTokenizer, PreTrainedTokenizerBase

from pocketsql.data import paths
from pocketsql.data.schema import messages, serialize

TOKENS = paths.FIXTURES / "tokens.json"
GOLDEN = paths.FIXTURES / "golden"


@cache
def tokenizer() -> PreTrainedTokenizerBase:
    spec = json.loads(TOKENS.read_text(encoding="utf-8"))
    return AutoTokenizer.from_pretrained(spec["model"], revision=spec["revision"])


def prompt_ids(schema_text: str, question: str) -> list[int]:
    enc = tokenizer().apply_chat_template(
        messages(schema_text, question),
        add_generation_prompt=True,
        enable_thinking=False,
        tokenize=True,
        return_dict=True,
    )
    return list(enc["input_ids"])


def golden_ids() -> dict[str, list[int]]:
    out = {}
    for path in sorted(GOLDEN.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = prompt_ids(serialize(case["schema"]), case["question"])
    return out


def _dump(spec: dict) -> str:
    """JSON with one line per id list."""
    ids = ",\n".join(
        f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in spec["ids"].items()
    )
    head = "".join(
        f"  {json.dumps(k)}: {json.dumps(v)},\n" for k, v in spec.items() if k != "ids"
    )
    return "{\n" + head + '  "ids": {\n' + ids + "\n  }\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.data.tokens")
    parser.add_argument("--write", action="store_true", help="rewrite tokens.json ids")
    args = parser.parse_args(argv)
    spec = json.loads(TOKENS.read_text(encoding="utf-8"))
    ids = golden_ids()
    if args.write:
        spec["ids"] = ids
        TOKENS.write_text(_dump(spec), encoding="utf-8")
    for name, seq in ids.items():
        print(name, len(seq), "match" if spec["ids"].get(name) == seq else "DIFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
