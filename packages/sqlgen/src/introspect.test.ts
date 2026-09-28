import { expect, it } from "vitest";
import { introspect } from "./introspect.ts";
import { serializeSchema } from "./schema.ts";

// A fake DuckDB: answers the introspection queries for two small tables.
const TABLES: Record<string, [string, string, unknown[]][]> = {
  pets: [
    ["id", "BIGINT", [1, 2, 3]],
    ["kind", "VARCHAR", ["dog", "cat", "dog", null]],
  ],
  Owners: [["note", "VARCHAR", ["a*/b", "x\ty", "ok"]]],
};

async function query(sql: string): Promise<unknown[][]> {
  if (sql.includes("information_schema.tables"))
    return Object.keys(TABLES).map((t) => [t]);
  const table = /table_name = '([^']+)'/.exec(sql)?.[1];
  if (table) return (TABLES[table] ?? []).map(([n, t]) => [n, t]);
  const [, col, tbl] =
    /SELECT (?:count\(DISTINCT )?"([^"]+)"\)? FROM "([^"]+)"/.exec(sql) ?? [];
  const values = TABLES[tbl ?? ""]?.find(([n]) => n === col)?.[2] ?? [];
  const nonNull = values.filter((v) => v !== null);
  if (sql.startsWith("SELECT count(DISTINCT")) return [[new Set(nonNull).size]];
  const counts = new Map<unknown, number>();
  for (const v of nonNull) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .map(([v]) => [v]);
}

it("sorts tables case-insensitively and keeps usable examples", async () => {
  expect(serializeSchema(await introspect(query))).toBe(
    "CREATE TABLE Owners (note VARCHAR /* e.g. 'ok' */);\n" +
      "CREATE TABLE pets (id BIGINT, kind VARCHAR /* e.g. 'dog', 'cat' */);",
  );
});
