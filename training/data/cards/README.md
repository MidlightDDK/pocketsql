---
license: cc-by-sa-4.0
language:
  - en
pretty_name: PocketSQL data (DuckDB text-to-SQL)
task_categories:
  - text-generation
tags:
  - text-to-sql
  - duckdb
  - spider
size_categories:
  - 1K<n<10K
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.jsonl
      - split: validation
        path: val.jsonl
      - split: test
        path: spider_dev_duckdb.jsonl
---

# PocketSQL data

Question → DuckDB SQL pairs used to fine-tune [PocketSQL](https://github.com/MidlightDDK/pocketsql), a sub-1B model that writes DuckDB SQL in the browser. Every pair was checked by running it: the DuckDB query must return the same result as Spider's original SQLite query on the same data.

**Version:** v0 (milestone M1): Spider-derived pairs only. Synthetic pairs for the app's demo schemas, with a manual review, are added in M3.

## Files

| File | Rows | What |
|---|---|---|
| `train.jsonl` | 7,376 | Spider train pairs, 130 databases |
| `val.jsonl` | 858 | Spider train pairs from 16 held-out databases (no database is in both train and val) |
| `spider_dev_duckdb.jsonl` | 981 | Spider dev pairs, 20 databases: the test set. Never used for training. |
| `databases.zip` | 36 files | DuckDB files for the val and test databases, for execution scoring |

Train/val row: `{id, db_id, schema_text, question, sql, source, difficulty}`. Test row: `{id, db_id, question, gold_sql, gold_result_hash, difficulty}`. `difficulty` is Spider's official hardness (easy, medium, hard, extra), computed from Spider's parsed SQL.

`schema_text` is the prompt's schema: one `CREATE TABLE t (col TYPE, …);` line per table, with up to 2 example values for text columns that have at most 20 distinct values. The full prompt is the base model's chat template (thinking disabled) with the system message "Write one DuckDB SQL query that answers the question. Output only SQL." and the user message `schema_text + "\n\nQuestion: " + question`. The target is the SQL alone, ending with `;`.

## How it was built

Code: `training/src/pocketsql/data/` in the GitHub repo (`python -m pocketsql.data.prepare`).

1. **Source.** Spider 1.0 `spider_data.zip` from the official release, sha256 `00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b`.
2. **SQLite → DuckDB.** Each database is copied with DuckDB's SQLite scanner using the declared column types. Where SQLite's loose typing breaks that, columns are loaded as text and cast back when every value allows it. Empty strings in numeric columns are read as NULL (114 columns). Text columns whose values are all canonical numbers become BIGINT or DOUBLE (165 columns); codes with leading zeros stay text.
3. **Gold SQL → DuckDB** with sqlglot 30.19.0, plus four rewrites that keep SQLite's meaning: double-quoted strings become string literals, `LIKE` becomes `ILIKE` (SQLite's LIKE ignores case), bare columns next to `GROUP BY` are added to the GROUP BY list, and sqlglot's `NULLIF` / `NULLS FIRST` guards are dropped.
4. **Execution filter.** A pair is kept only if the DuckDB result equals the SQLite result: order matters only when the query has a top-level ORDER BY, floats match within 1e-6, and ints, floats, and numeric strings compare as numbers.
5. **Dedupe and split.** 42 exact duplicates (same database, question, and SQL) were removed from train. Val is a seeded set of Spider train databases (about 10% of pairs).
6. **Leakage check.** No train or val item shares a database and a normalized question or SQL with a test item, or has question token-Jaccard ≥ 0.9 with one (`python -m pocketsql.data.leakage`, run in CI against this dataset).

## Retention

| Split | Spider pairs | Kept | Retention | DuckDB error | Result mismatch | SQLite error |
|---|---|---|---|---|---|---|
| train | 7,733 | 7,417 | 95.9% | 66 | 247 | 3 |
| val | 926 | 859 | 92.8% | 14 | 53 | 0 |
| test (dev) | 1,034 | 981 | 94.9% | 11 | 42 | 0 |

Most mismatches are ORDER BY ties that SQLite and DuckDB break differently (gold queries whose answer depends on tie order). Per-database retention and every conversion note are in `stats.json` in the GitHub repo (`training/data/cards/stats.json`).

| Difficulty | easy | medium | hard | extra |
|---|---|---|---|---|
| train | 1,741 | 2,518 | 1,614 | 1,503 |
| val | 203 | 355 | 200 | 100 |
| test | 236 | 433 | 164 | 148 |

Prompt + SQL length with the Qwen3 tokenizer: median 297 tokens, p95 701, max 2,249.

## Limitations

- 1,580 train/val pairs (19%) and 49 test pairs return an empty result on Spider's sample data, which makes their execution match weaker evidence.
- Spider's known annotation issues remain where the query still runs; only execution equivalence between engines is checked, not the question-to-SQL meaning.

## License and attribution

Derived from Spider (Yu et al., 2018), licensed CC BY-SA 4.0; this dataset keeps the same license.

```bibtex
@inproceedings{yu-etal-2018-spider,
  title     = {{Spider}: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-{SQL} Task},
  author    = {Yu, Tao and Zhang, Rui and Yang, Kai and Yasunaga, Michihiro and Wang, Dongxu and Li, Zifan and Ma, James and Li, Irene and Yao, Qingning and Roman, Shanelle and Zhang, Zilin and Radev, Dragomir},
  booktitle = {Proceedings of EMNLP},
  year      = {2018}
}
```
