// Mirrors training/src/pocketsql/data/schema.py byte-for-byte; both must reproduce
// fixtures/golden/*.txt.
import { SYSTEM_PROMPT } from "./prompt.ts";

export interface Column {
  name: string;
  type: string;
  examples?: string[];
}

export interface Table {
  name: string;
  columns: Column[];
}

export interface Schema {
  tables: Table[];
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

// DuckDB 1.5.5: SELECT keyword_name FROM duckdb_keywords()
//   WHERE keyword_category = 'reserved'
const RESERVED = new Set(
  (
    "all analyse analyze and any array as asc asymmetric both case cast " +
    "check collate column constraint create default deferrable desc " +
    "describe distinct do else end except false fetch for foreign from " +
    "group having in initially intersect into lambda lateral leading limit " +
    "not null offset on only or order pivot pivot_longer pivot_wider " +
    "placing primary qualify references returning select show some " +
    "summarize symmetric table then to trailing true union unique unpivot " +
    "using variadic when where window with"
  ).split(" "),
);
const PLAIN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const EDGE_WHITESPACE = /^[ \t\n\r]+|[ \t\n\r]+$/g;

export function ident(name: string): string {
  if (PLAIN.test(name) && !RESERVED.has(name.toLowerCase())) return name;
  return `"${name.replaceAll('"', '""')}"`;
}

function column(c: Column): string {
  let out = `${ident(c.name)} ${c.type}`;
  if (c.examples?.length) {
    const quoted = c.examples
      .map((v) => `'${v.replaceAll("'", "''")}'`)
      .join(", ");
    out += ` /* e.g. ${quoted} */`;
  }
  return out;
}

/** One `CREATE TABLE t (col TYPE, …);` line per table. */
export function serializeSchema(schema: Schema): string {
  return schema.tables
    .map(
      (t) =>
        `CREATE TABLE ${ident(t.name)} (${t.columns.map(column).join(", ")});`,
    )
    .join("\n");
}

export function buildUserPrompt(schemaText: string, question: string): string {
  return `${schemaText}\n\nQuestion: ${question.replace(EDGE_WHITESPACE, "")}`;
}

export function buildMessages(
  schemaText: string,
  question: string,
): ChatMessage[] {
  return [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: buildUserPrompt(schemaText, question) },
  ];
}
