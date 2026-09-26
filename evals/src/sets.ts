// Mirrors training/src/pocketsql/evalx/sets.py (set files, the seeded Spider-dev
// sample, the parity prompts, and the shared schema text).
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const EVALS = join(import.meta.dirname, "..");
const SETS = join(EVALS, "sets");
const FILES: Record<string, string> = {
  own_test: "own_test.jsonl",
  spider_dev: "spider_dev_duckdb.jsonl",
};
const SUBSET_SEED = "pocketsql-dev100-v1";

export interface Item {
  id: string;
  db_id: string;
  question: string;
  gold_sql: string;
  gold_result_hash: string;
  difficulty: string;
}

export function readJsonl<T>(path: string): T[] {
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as T);
}

const byKey = <T>(a: [string, T], b: [string, T]) =>
  a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;

export function loadSet(name: string): Item[] {
  const file = FILES[name];
  if (file) return readJsonl<Item>(join(SETS, file));
  if (name === "parity") {
    return ["own_test", "spider_dev_100"].flatMap((base) =>
      loadSet(base).filter((_, i) => i % 10 === 0),
    );
  }
  if (name === "spider_dev_100") {
    const hash = (i: Item) =>
      createHash("sha256").update(`${SUBSET_SEED}:${i.id}`).digest("hex");
    return loadSet("spider_dev")
      .map((i): [string, Item] => [hash(i), i])
      .sort(byKey)
      .slice(0, 100)
      .map(([, i]): [string, Item] => [i.id, i])
      .sort(byKey)
      .map(([, i]) => i);
  }
  throw new Error(`unknown set ${name}`);
}

export function loadSchemas(): Record<string, string> {
  return JSON.parse(readFileSync(join(SETS, "schemas.json"), "utf8"));
}
