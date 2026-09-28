// DuckDB-WASM, loaded from jsDelivr (the wasm files exceed the Workers 25 MiB asset
// limit); the pinned npm version decides the CDN URLs, and the service worker
// precaches them (vite.config.ts). One connection per dataset, each `USE`-ing it.
import * as duckdb from "@duckdb/duckdb-wasm";
import { introspect, serializeSchema } from "@pocketsql/sqlgen";

export type Cell = string | number | boolean | null;
export interface Result {
  columns: string[];
  rows: Cell[][];
  /** Rows the query returned; `rows` keeps at most MAX_ROWS. */
  rowCount: number;
  ms: number;
}

export const MAX_ROWS = 500;
const TIMEOUT_MS = 10_000;

export const BUNDLES = duckdb.getJsDelivrBundles();

interface Engine {
  db: duckdb.AsyncDuckDB;
  conns: Map<string, Promise<duckdb.AsyncDuckDBConnection>>;
  version: string;
}

let engine: Promise<Engine> | null = null;
let uploads = 0;

async function start(): Promise<Engine> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  if (!bundle.mainWorker)
    throw new Error("No DuckDB-WASM build for this browser");
  // Cross-origin workers are not allowed: a same-origin blob worker pulls the CDN script.
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts(${JSON.stringify(bundle.mainWorker)});`], {
      type: "text/javascript",
    }),
  );
  const db = new duckdb.AsyncDuckDB(
    new duckdb.VoidLogger(),
    new Worker(workerUrl),
  );
  try {
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  } finally {
    URL.revokeObjectURL(workerUrl);
  }
  await db.open({
    query: {
      castBigIntToDouble: true,
      castDecimalToDouble: true,
      castTimestampToDate: true,
    },
  });
  const version = await db.getVersion();
  return { db, conns: new Map(), version };
}

export function getEngine(): Promise<Engine> {
  engine ??= start().catch((err: unknown) => {
    engine = null; // retry on the next call
    throw err;
  });
  return engine;
}

const quoteIdent = (name: string) => `"${name.replaceAll('"', '""')}"`;
const quoteString = (s: string) => `'${s.replaceAll("'", "''")}'`;

/** A demo database from /data/<id>.duckdb, attached read-only as catalog <id>. */
function connection(id: string): Promise<duckdb.AsyncDuckDBConnection> {
  return getEngine().then(({ db, conns }) => {
    let conn = conns.get(id);
    if (!conn) {
      conn = (async () => {
        const res = await fetch(`/data/${id}.duckdb`);
        if (!res.ok) throw new Error(`Could not load the ${id} database`);
        const file = `${id}.duckdb`;
        await db.registerFileBuffer(
          file,
          new Uint8Array(await res.arrayBuffer()),
        );
        const c = await db.connect();
        await c.query(
          `ATTACH ${quoteString(file)} AS ${quoteIdent(id)} (READ_ONLY)`,
        );
        await c.query(`USE ${quoteIdent(id)}`);
        return c;
      })();
      conn.catch(() => conns.delete(id));
      conns.set(id, conn);
    }
    return conn;
  });
}

function toCell(v: unknown): Cell {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" || typeof v === "string" || typeof v === "boolean")
    return v;
  if (typeof v === "bigint") return Number(v);
  if (v instanceof Date) {
    const iso = v.toISOString();
    return iso.endsWith("T00:00:00.000Z")
      ? iso.slice(0, 10)
      : iso.replace(".000Z", "Z");
  }
  if (typeof v === "object" && "toJSON" in v && typeof v.toJSON === "function")
    return JSON.stringify(v.toJSON());
  return String(v);
}

/** Runs one statement on dataset `id`, cancelling it after 10 s. */
export async function runSql(id: string, sql: string): Promise<Result> {
  const conn = await connection(id);
  const start = performance.now();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    void conn.cancelSent();
  }, TIMEOUT_MS);
  try {
    // send() polls a pending query, which is what makes cancelSent() work.
    const reader = await conn.send(sql.replace(/;\s*$/, ""), false);
    // open() reads the schema message; iterating closes the reader and drops it.
    await reader.open();
    const columns = reader.schema.fields.map((f) => f.name);
    const rows: Cell[][] = [];
    let rowCount = 0;
    for await (const batch of reader) {
      rowCount += batch.numRows;
      const width = batch.numCols;
      for (let r = 0; r < batch.numRows && rows.length < MAX_ROWS; r++) {
        rows.push(
          Array.from({ length: width }, (_, c) =>
            toCell(batch.getChildAt(c)?.get(r)),
          ),
        );
      }
    }
    return { columns, rows, rowCount, ms: performance.now() - start };
  } catch (err) {
    if (timedOut)
      throw new Error("The query took longer than 10 s and was stopped.");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** DuckDB's own error for SQL that would not run, or null when it plans fine. */
export async function explain(id: string, sql: string): Promise<string | null> {
  const conn = await connection(id);
  try {
    await conn.query(`EXPLAIN ${sql.replace(/;\s*$/, "")}`);
    return null;
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

async function rows(conn: duckdb.AsyncDuckDBConnection, sql: string) {
  const table = await conn.query(sql);
  return table.toArray().map((row) => Object.values(row.toJSON()));
}

/** The prompt schema for dataset `id`, read the way training read it. */
export async function schemaText(id: string): Promise<string> {
  const conn = await connection(id);
  return serializeSchema(await introspect((sql) => rows(conn, sql)));
}

/** A table name from a file name: lowercase letters, digits, and underscores. */
export function tableName(fileName: string): string {
  const base = fileName.replace(/\.[^.]+$/, "").toLowerCase();
  const name = base.replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z_]/.test(name) ? name : `t_${name || "data"}`;
}

/** Loads a CSV or Parquet file into a new in-memory catalog; returns its id and schema. */
export async function addUpload(
  file: File,
): Promise<{ id: string; table: string; schema: string }> {
  const { db, conns } = await getEngine();
  const parquet = /\.parquet$/i.test(file.name);
  const id = `upload_${++uploads}`;
  const path = `${id}${parquet ? ".parquet" : ".csv"}`;
  await db.registerFileBuffer(path, new Uint8Array(await file.arrayBuffer()));
  const conn = await db.connect();
  const table = tableName(file.name);
  const reader = parquet ? "read_parquet" : "read_csv";
  await conn.query(`ATTACH ':memory:' AS ${id}`);
  await conn.query(`USE ${id}`);
  await conn.query(
    `CREATE TABLE ${quoteIdent(table)} AS SELECT * FROM ${reader}(${quoteString(path)})`,
  );
  conns.set(id, Promise.resolve(conn));
  const schema = serializeSchema(await introspect((sql) => rows(conn, sql)));
  return { id, table, schema };
}
