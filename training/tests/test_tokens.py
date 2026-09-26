import json

from pocketsql.data.tokens import TOKENS, golden_ids


def test_golden_token_ids_match_fixture() -> None:
    expected = json.loads(TOKENS.read_text(encoding="utf-8"))["ids"]
    assert golden_ids() == expected
