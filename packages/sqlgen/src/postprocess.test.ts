import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { FIXTURES } from "./fixtures.ts";
import { cleanSql } from "./postprocess.ts";

// Shared with training/tests/test_evalx.py, so both runtimes clean output alike.
const cases: [string, string][] = JSON.parse(
  readFileSync(join(FIXTURES, "clean_sql.json"), "utf8"),
);

it.each(cases)("cleanSql(%j)", (raw, sql) => {
  expect(cleanSql(raw)).toBe(sql);
});
