from pocketsql.evalx.compare import has_order_by, result_hash, results_match


def test_unordered_multiset() -> None:
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], ordered=False)
    assert not results_match([(1,), (1,)], [(1,)], ordered=False)


def test_ordered() -> None:
    assert not results_match([(1,), (2,)], [(2,), (1,)], ordered=True)


def test_normalization_and_tolerance() -> None:
    assert results_match([(1, 2.5, "3")], [(1.0, 2.5000000001, 3)], ordered=True)
    assert not results_match([(1.0,)], [(1.001,)], ordered=True)
    assert not results_match([("a",)], [("a", None)], ordered=True)


def test_hash_ignores_order_when_unordered() -> None:
    assert result_hash([(1,), (2,)], False) == result_hash([(2,), (1.0,)], False)
    assert result_hash([(1,), (2,)], True) != result_hash([(2,), (1,)], True)


def test_has_order_by() -> None:
    assert has_order_by("SELECT a FROM t ORDER BY a")
    assert not has_order_by("SELECT a FROM (SELECT a FROM t ORDER BY a) AS s")
