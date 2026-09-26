import importlib

import pytest

CLIS = [
    ("pocketsql.synth.__main__", "M3"),
    ("pocketsql.release.gate", "M5"),
]


@pytest.mark.parametrize(("module", "milestone"), CLIS)
def test_stub_exits_with_milestone(module: str, milestone: str) -> None:
    main = importlib.import_module(module).main
    with pytest.raises(SystemExit, match=milestone):
        main([])
