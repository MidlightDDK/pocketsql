// Mirrors training/src/pocketsql/evalx/postprocess.py; both must pass
// fixtures/clean_sql.json.

const THINK = /<think>[\s\S]*?<\/think>/g;
const FENCE = /```[A-Za-z]*[ \t]*\n?([\s\S]*?)(?:```|$)/;

/** Everything up to the first `;` outside quotes and comments. */
export function firstStatement(sql: string): string {
  let quote = "";
  let i = 0;
  while (i < sql.length) {
    const ch = sql[i];
    if (quote) {
      if (ch === quote) quote = "";
    } else if (ch === "'" || ch === '"') {
      quote = ch;
    } else if (sql.startsWith("--", i)) {
      const end = sql.indexOf("\n", i);
      i = end < 0 ? sql.length : end;
      continue;
    } else if (sql.startsWith("/*", i)) {
      const end = sql.indexOf("*/", i + 2);
      i = end < 0 ? sql.length : end + 2;
      continue;
    } else if (ch === ";") {
      return sql.slice(0, i);
    }
    i++;
  }
  return sql;
}

/** Drop thinking blocks and code fences; keep the first statement, ending in `;`. */
export function cleanSql(text: string): string {
  let out = text.replace(THINK, "");
  if (out.includes("</think>"))
    out = out.slice(out.lastIndexOf("</think>") + 8);
  const fence = FENCE.exec(out);
  if (fence) out = fence[1] ?? "";
  const sql = firstStatement(out).trim();
  return sql ? `${sql};` : "";
}
