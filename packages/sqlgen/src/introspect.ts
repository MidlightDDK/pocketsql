// Mirrors introspect() in training/src/pocketsql/data/schema.py, so a schema read
// from DuckDB-WASM (e.g. an uploaded file) is serialized the way training saw it.
// One difference: it reads only the current catalog, since the browser attaches
// several databases to one DuckDB instance (Python opens one file).
import type { Column, Schema, Table } from "./schema.ts";

/** Runs one SQL statement and returns its rows as arrays of values. */
export type Query = (sql: string) => Promise<unknown[][]>;

const MAX_DISTINCT = 20;
const MAX_EXAMPLES = 2;
const MAX_EXAMPLE_CHARS = 40;

const quoteIdent = (name: string) => `"${name.replaceAll('"', '""')}"`;
const quoteString = (value: string) => `'${value.replaceAll("'", "''")}'`;

function usableExample(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const chars = [...v];
  const noControl = chars.every((ch) => {
    const code = ch.codePointAt(0) ?? 0;
    return code >= 32 && code !== 127;
  });
  return (
    chars.length > 0 &&
    chars.length <= MAX_EXAMPLE_CHARS &&
    noControl &&
    !v.includes("*/")
  );
}

/**
 * Reads schema `main`: tables sorted case-insensitively, columns in table order.
 * Examples: for VARCHAR columns with 1–20 distinct values, the 2 most frequent
 * values (ties by value) that are 1–40 chars, without control chars or a
 * comment terminator.
 */
export async function introspect(query: Query): Promise<Schema> {
  const names = (
    await query(
      "SELECT table_name FROM information_schema.tables " +
        "WHERE table_catalog = current_database() AND table_schema = 'main' " +
        "AND table_type = 'BASE TABLE'",
    )
  ).map((r) => String(r[0]));
  names.sort((a, b) => {
    const [la, lb] = [a.toLowerCase(), b.toLowerCase()];
    if (la !== lb) return la < lb ? -1 : 1;
    return a < b ? -1 : a > b ? 1 : 0;
  });
  const tables: Table[] = [];
  for (const t of names) {
    const columns: Column[] = [];
    const rows = await query(
      "SELECT column_name, data_type FROM information_schema.columns " +
        "WHERE table_catalog = current_database() AND table_schema = 'main' " +
        `AND table_name = ${quoteString(t)} ` +
        "ORDER BY ordinal_position",
    );
    for (const [name, type] of rows) {
      const col: Column = { name: String(name), type: String(type) };
      if (col.type === "VARCHAR") {
        const [c, qt] = [quoteIdent(col.name), quoteIdent(t)];
        const distinct = Number(
          (await query(`SELECT count(DISTINCT ${c}) FROM ${qt}`))[0]?.[0] ?? 0,
        );
        if (distinct > 0 && distinct <= MAX_DISTINCT) {
          const values = await query(
            `SELECT ${c} FROM ${qt} WHERE ${c} IS NOT NULL ` +
              `GROUP BY ${c} ORDER BY count(*) DESC, ${c}`,
          );
          const examples = values.map((r) => r[0]).filter(usableExample);
          if (examples.length) col.examples = examples.slice(0, MAX_EXAMPLES);
        }
      }
      columns.push(col);
    }
    tables.push({ name: t, columns });
  }
  return { tables };
}
