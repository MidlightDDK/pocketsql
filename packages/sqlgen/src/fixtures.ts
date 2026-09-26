import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Schema } from "./schema.ts";

export const FIXTURES = join(import.meta.dirname, "..", "fixtures");
const GOLDEN = join(FIXTURES, "golden");

export interface GoldenCase {
  name: string;
  schema: Schema;
  question: string;
  expected: string;
}

export function goldenCases(): GoldenCase[] {
  return readdirSync(GOLDEN)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => {
      const name = f.slice(0, -".json".length);
      const input = JSON.parse(readFileSync(join(GOLDEN, f), "utf8"));
      const expected = readFileSync(join(GOLDEN, `${name}.txt`), "utf8");
      return { name, ...input, expected };
    });
}
