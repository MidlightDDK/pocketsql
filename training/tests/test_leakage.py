from pocketsql.data.leakage import check, find_leaks

TEST = [
    {
        "id": "t1",
        "db_id": "db",
        "question": "How many singers are there?",
        "gold_sql": "SELECT count(*) FROM singer;",
    }
]


def _item(i: str, q: str, sql: str = "SELECT 1;", db: str = "db") -> dict:
    return {"id": i, "db_id": db, "question": q, "sql": sql}


def test_exact_and_near_duplicates_are_flagged() -> None:
    leaks = find_leaks(
        [
            _item("a", "how many singers are there"),
            _item("b", "How many singers are there in total?"),
            _item("c", "Something else", "select COUNT(*) from singer"),
            _item("d", "How many singers are there?", db="other"),
            _item("e", "List all singer names."),
        ],
        TEST,
    )
    assert [leak.split()[0] for leak in leaks] == ["a", "c"]


def test_jaccard_threshold() -> None:
    q = "what are the names of all singers ordered by age from oldest to youngest"
    test = [{**TEST[0], "question": q, "gold_sql": "x"}]
    near = q.replace("youngest", "the youngest")  # 13/14 shared tokens
    assert find_leaks([_item("n", near)], test)


def test_val_must_not_share_databases_with_train() -> None:
    problems = check([_item("a", "q1")], [_item("b", "q2")], [])
    assert problems == ["database db is in both train and val"]
