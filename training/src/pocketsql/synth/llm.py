"""Groq chat calls for synthetic data: cached by request body, paced per model.

Free tier, per model: 30 RPM, 1K RPD, 8K TPM, 200K TPD
(https://console.groq.com/docs/rate-limits, checked 2026-09-26). qwen3.8-27b also has
a 1K output-tokens-per-minute limit (OTPM) that rejects any request whose
max_completion_tokens exceeds 1000 (seen in its 429 message, not in the docs).
Responses are cached in .cache/groq/, so an interrupted run resumes without spending
quota again.
"""

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter

from pocketsql.data import paths
from pocketsql.evalx.predict_groq import URL, api_key

CACHE = paths.REPO / ".cache" / "groq"
TPM = 7000  # pace below the 8K tokens-per-minute limit
OTPM = {"qwen/qwen3.8-27b": 950}  # output tokens per minute, where limited
MAX_WAIT_S = 900  # a longer retry-after means the daily quota is spent


class QuotaExhausted(Exception):
    pass


class NotCached(Exception):
    """A call missing from the cache in cached-only mode."""


class Groq:
    def __init__(self, cached_only: bool = False) -> None:
        self.cached_only = cached_only
        self.key: str | None = None
        self.next_ok: dict[str, float] = {}
        self.tokens: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()

    def chat(self, body: dict) -> dict:
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cached = CACHE / f"{digest[:32]}.json"
        if cached.exists():
            out = json.loads(cached.read_text(encoding="utf-8"))
        elif self.cached_only:
            raise NotCached(body["model"])
        else:
            out = self._post(body)
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(out), encoding="utf-8")
        self.tokens[body["model"]] += out.get("usage", {}).get("total_tokens", 0)
        self.calls[body["model"]] += 1
        return out

    def _post(self, body: dict) -> dict:
        model = body["model"]
        time.sleep(max(0.0, self.next_ok.get(model, 0.0) - time.monotonic()))
        self.key = self.key or api_key()
        data = json.dumps(body).encode()
        for attempt in range(40):
            req = urllib.request.Request(
                URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                    "User-Agent": "pocketsql-synth",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    out = json.load(resp)
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode(errors="replace")
                if e.code == 429:
                    if "Request too large" in detail:
                        raise SystemExit(f"Groq ({model}): {detail}") from e
                    # The daily limit is a rolling window: a short retry-after means
                    # enough of the day-old usage expires soon.
                    wait = float(e.headers.get("retry-after") or 30) + 2
                    if wait > MAX_WAIT_S:
                        raise QuotaExhausted(f"{model}: {detail}") from e
                elif e.code >= 500:
                    wait = min(2 ** (attempt + 2), 120)
                else:
                    raise SystemExit(f"Groq HTTP {e.code} ({model}): {detail}") from e
                print(f"{model}: HTTP {e.code} {detail[:160]!r}, retry in {wait:.0f} s")
                time.sleep(wait)
                continue
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"{model}: {e}, retrying", flush=True)
                time.sleep(2 ** (attempt + 2))
                continue
            usage = out.get("usage", {})
            minutes = max(
                usage.get("total_tokens", 0) / TPM,
                usage.get("completion_tokens", 0) / OTPM.get(model, TPM),
            )
            self.next_ok[model] = time.monotonic() + minutes * 60
            return out
        raise SystemExit(f"Groq ({model}): too many retries")


def json_content(out: dict) -> dict | None:
    """The message content parsed as a JSON object, or None."""
    text = out["choices"][0]["message"].get("content") or ""
    for candidate in (text, *re.findall(r"\{.*\}", text, flags=re.S)):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
