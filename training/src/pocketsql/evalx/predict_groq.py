"""Large-API-model baseline through Groq: same prompt, temperature 0, cached in .cache/.

`uv run --project training python -m pocketsql.evalx.predict_groq --set own_test`
writes evals/predictions/<model>__groq__<set>.jsonl. Needs GROQ_API_KEY (shell or
training/.env). Free tier for gpt-oss-120b: 30 RPM, 1K RPD, 8K TPM, 200K TPD
(https://console.groq.com/docs/rate-limits); 429s are retried after `retry-after`.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from pocketsql.data import paths
from pocketsql.data.schema import messages
from pocketsql.evalx.models import MODELS
from pocketsql.evalx.sets import SET_NAMES, load_schemas, load_set

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"
NAME = "gpt-oss-120b"
PRICE_PER_M = MODELS[NAME]["price_per_m_usd"]
PARAMS = {"temperature": 0, "reasoning_effort": "low", "max_completion_tokens": 4096}
CACHE = paths.REPO / ".cache" / "groq"
PREDICTIONS = paths.REPO / "evals" / "predictions"


def api_key() -> str:
    key = os.environ.get("GROQ_API_KEY")
    env = paths.REPO / "training" / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GROQ_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise SystemExit("GROQ_API_KEY is not set (shell or training/.env)")
    return key


def complete(body: dict, key: str) -> dict:
    """POST with retries on 429/5xx; returns the response JSON plus latency_ms."""
    data = json.dumps(body).encode()
    for attempt in range(8):
        req = urllib.request.Request(
            URL,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "pocketsql-eval",
            },
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.load(resp)
            out["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            return out
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise SystemExit(f"Groq HTTP {e.code}: {e.read()[:300]!r}") from e
            wait = float(e.headers.get("retry-after") or 2 ** (attempt + 1))
            print(f"HTTP {e.code}, retrying in {wait:.0f} s", flush=True)
            time.sleep(min(wait, 120))
    raise SystemExit("Groq: too many retries")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.evalx.predict_groq")
    parser.add_argument("--set", required=True, choices=SET_NAMES)
    parser.add_argument("--limit", type=int, help="first N items only")
    args = parser.parse_args(argv)
    schemas = load_schemas()
    items = load_set(args.set)[: args.limit]
    CACHE.mkdir(parents=True, exist_ok=True)
    key = None
    rows = []
    for n, item in enumerate(items, 1):
        body = {
            "model": MODEL,
            "messages": messages(schemas[item["db_id"]], item["question"]),
            **PARAMS,
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cached = CACHE / f"{digest[:32]}.json"
        if cached.exists():
            out = json.loads(cached.read_text(encoding="utf-8"))
        else:
            key = key or api_key()
            out = complete(body, key)
            cached.write_text(json.dumps(out), encoding="utf-8")
            time.sleep(8)  # ~1K tokens per call: stay under 8K tokens per minute
        usage = out.get("usage", {})
        rows.append(
            {
                "id": item["id"],
                "sql": out["choices"][0]["message"].get("content") or "",
                "latency_ms": out["latency_ms"],
                "tokens_out": usage.get("completion_tokens"),
                "tokens_in": usage.get("prompt_tokens"),
            }
        )
        if n % 20 == 0:
            print(f"{n}/{len(items)}", flush=True)
    out_path = PREDICTIONS / f"{NAME}__groq__{args.set}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    cost = (
        sum(
            (r["tokens_in"] or 0) * PRICE_PER_M[0]
            + (r["tokens_out"] or 0) * PRICE_PER_M[1]
            for r in rows
        )
        / 1e6
    )
    print(f"wrote {out_path.relative_to(paths.REPO).as_posix()}")
    print(f"cost at list price: ${cost / len(rows):.6f} per query")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
