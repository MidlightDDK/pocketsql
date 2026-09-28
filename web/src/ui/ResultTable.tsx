import type { Result } from "../db";
import { formatCell, formatMs } from "../format";

export function ResultTable({ result }: { result: Result }) {
  const { columns, rows, rowCount } = result;
  return (
    <div>
      <div className="max-h-80 overflow-auto rounded-md border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900">
            <tr>
              {columns.map((c, i) => (
                <th
                  // biome-ignore lint/suspicious/noArrayIndexKey: column names may repeat
                  key={i}
                  scope="col"
                  className="px-3 py-2 font-medium whitespace-nowrap"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {rows.map((r, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: rows have no identity
              <tr key={i}>
                {r.map((v, j) => (
                  <td
                    // biome-ignore lint/suspicious/noArrayIndexKey: cells have no identity
                    key={j}
                    className={`px-3 py-1.5 whitespace-nowrap ${typeof v === "number" ? "text-right tabular-nums" : ""} ${v === null ? "text-zinc-400" : ""}`}
                  >
                    {formatCell(v, columns[j])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        {rowCount === 1 ? "1 row" : `${rowCount.toLocaleString("en-US")} rows`}
        {rowCount > rows.length ? ` (showing ${rows.length})` : ""}
        {result.ms > 0 ? ` · ran in ${formatMs(result.ms)}` : ""}
      </p>
    </div>
  );
}
