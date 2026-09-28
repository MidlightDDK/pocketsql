// An automatic chart for simple result shapes: two columns, one numeric.
// Numbers or dates on x give a line; categories give horizontal bars.
import type { Cell, Result } from "../db";
import { formatCell, formatCompact } from "../format";

export interface ChartSpec {
  kind: "bar" | "line";
  x: number;
  y: number;
}

const DATE = /^\d{4}-\d{2}(-\d{2})?/;

export function chartSpec({ columns, rows }: Result): ChartSpec | null {
  if (columns.length !== 2 || rows.length < 2 || rows.length > 30) return null;
  const numeric = (c: number) => rows.every((r) => typeof r[c] === "number");
  const y = numeric(1) ? 1 : numeric(0) ? 0 : -1;
  if (y < 0) return null;
  const x = 1 - y;
  if (rows.some((r) => r[x] === null)) return null;
  const ordered = rows.every(
    (r) => typeof r[x] === "number" || DATE.test(String(r[x])),
  );
  if (ordered && rows.length >= 3) return { kind: "line", x, y };
  if (rows.some((r) => (r[y] as number) < 0)) return null;
  return { kind: "bar", x, y };
}

export function Chart({ result, spec }: { result: Result; spec: ChartSpec }) {
  const label = `${result.columns[spec.y]} by ${result.columns[spec.x]}`;
  return (
    <figure className="mt-4" aria-label={`Chart: ${label}`}>
      {spec.kind === "bar" ? (
        <Bars result={result} spec={spec} />
      ) : (
        <Line result={result} spec={spec} />
      )}
      <figcaption className="mt-1 text-xs text-zinc-500">{label}</figcaption>
    </figure>
  );
}

function Bars({ result, spec }: { result: Result; spec: ChartSpec }) {
  const values = result.rows.map((r) => r[spec.y] as number);
  const max = Math.max(...values) || 1;
  const xName = result.columns[spec.x] ?? "";
  return (
    <div className="space-y-1">
      {result.rows.map((r, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: rows have no identity
          key={i}
          className="grid grid-cols-[minmax(0,10rem)_1fr] items-center gap-2 text-xs"
        >
          <span
            className="truncate text-zinc-600 dark:text-zinc-400"
            title={formatCell(r[spec.x] as Cell, xName)}
          >
            {formatCell(r[spec.x] as Cell, xName)}
          </span>
          <span className="flex items-center gap-2">
            <span
              className="h-4 rounded-sm bg-teal-600 dark:bg-teal-400"
              style={{
                width: `${Math.max(0.5, ((values[i] ?? 0) / max) * 85)}%`,
              }}
            />
            <span className="tabular-nums text-zinc-700 dark:text-zinc-300">
              {formatCompact(values[i] ?? 0)}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

function Line({ result, spec }: { result: Result; spec: ChartSpec }) {
  const xName = result.columns[spec.x] ?? "";
  const points = result.rows
    .map((r) => ({ x: r[spec.x] as number | string, y: r[spec.y] as number }))
    .sort((a, b) => (a.x < b.x ? -1 : a.x > b.x ? 1 : 0));
  const [W, H, L, R, T, B] = [600, 200, 56, 16, 12, 28];
  const ys = points.map((p) => p.y);
  let [lo, hi] = [Math.min(...ys), Math.max(...ys)];
  if (lo === hi) [lo, hi] = [lo - 1, hi + 1];
  const px = (i: number) => L + (i / (points.length - 1)) * (W - L - R);
  const py = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = points.map((p, i) => `${px(i)},${py(p.y)}`).join(" ");
  const every = Math.ceil(points.length / 8);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full text-zinc-500" role="img">
      <title>{`${result.columns[spec.y]} by ${xName}`}</title>
      <line
        x1={L}
        x2={W - R}
        y1={H - B}
        y2={H - B}
        stroke="currentColor"
        strokeOpacity={0.3}
      />
      {[lo, hi].map((v) => (
        <text
          key={v}
          x={L - 6}
          y={py(v) + 4}
          textAnchor="end"
          fontSize={11}
          fill="currentColor"
        >
          {formatCompact(v)}
        </text>
      ))}
      <polyline
        points={path}
        fill="none"
        className="stroke-teal-600 dark:stroke-teal-400"
        strokeWidth={2}
      />
      {points.map((p, i) => (
        <g key={String(p.x)}>
          <circle
            cx={px(i)}
            cy={py(p.y)}
            r={3}
            className="fill-teal-600 dark:fill-teal-400"
          >
            <title>{`${formatCell(p.x, xName)}: ${formatCell(p.y)}`}</title>
          </circle>
          {i % every === 0 || i === points.length - 1 ? (
            <text
              x={px(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize={11}
              fill="currentColor"
            >
              {formatCell(p.x, xName)}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  );
}
