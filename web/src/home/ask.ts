import { buildMessages, cleanSql } from "@pocketsql/sqlgen";
import type { Dataset } from "../datasets";
import { explain, type Result, runSql } from "../db";
import { generate } from "../llm/store";

export interface Answer {
  question: string;
  datasetId: string;
  sql: string;
  origin: "precomputed" | "model" | "edited";
  genMs?: number;
  tokens?: number;
  /** The greedy SQL failed EXPLAIN, so a second sample (temperature 0.3) was used. */
  retried?: boolean;
  result?: Result;
  error?: string;
}

const NO_SQL = "The model did not return any SQL.";

/** Generate, check with EXPLAIN, retry once with a sample, then run. */
export async function askModel(
  ds: Dataset,
  question: string,
  onText: (text: string) => void,
): Promise<Answer> {
  const messages = buildMessages(ds.schema, question);
  const first = await generate(messages, false, onText);
  let sql = cleanSql(first.text);
  let genMs = first.ms;
  let tokens = first.tokens;
  let problem = sql ? await explain(ds.id, sql) : NO_SQL;
  let retried = false;
  if (problem) {
    retried = true;
    const second = await generate(messages, true, onText);
    genMs += second.ms;
    tokens += second.tokens;
    const sql2 = cleanSql(second.text);
    const problem2 = sql2 ? await explain(ds.id, sql2) : NO_SQL;
    if (!problem2 || !sql) {
      sql = sql2;
      problem = problem2;
    }
  }
  const answer: Answer = {
    question,
    datasetId: ds.id,
    sql,
    origin: "model",
    genMs,
    tokens,
    retried,
  };
  if (problem) return { ...answer, error: problem };
  return runInto(answer);
}

/** Runs `answer.sql` and attaches the result or DuckDB's error. */
export async function runInto(answer: Answer): Promise<Answer> {
  try {
    return {
      ...answer,
      result: await runSql(answer.datasetId, answer.sql),
      error: undefined,
    };
  } catch (err) {
    return {
      ...answer,
      result: undefined,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
