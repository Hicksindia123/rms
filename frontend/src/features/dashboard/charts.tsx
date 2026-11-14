import { useId, useState, type ReactNode } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/**
 * Dashboard charts (P4-01). Colours come from the `--chart-*` tokens (validated categorical
 * slots, fixed order). Every chart has a data-table view (toggle) and a screen-reader table, so
 * identity never depends on colour alone (§11 accessibility).
 */

export interface Column<R> {
  key: string;
  header: string;
  value: (row: R) => ReactNode;
  numeric?: boolean;
}

function DataTable<R>({
  caption,
  rows,
  columns,
  hidden,
}: {
  caption: string;
  rows: R[];
  columns: Column<R>[];
  hidden?: boolean;
}) {
  const table = (
    <table className={hidden ? undefined : 'dash-table'}>
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} scope="col" className={c.numeric ? 'num' : undefined}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {columns.map((c) => (
              <td key={c.key} className={c.numeric ? 'num' : undefined}>
                {c.value(r)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
  // `overflow: hidden` does not clip a table box, so the visually hidden copy sits in a div.
  return hidden ? <div className="sr-only">{table}</div> : table;
}

/** Chart + table toggle. The chart itself is hidden from assistive tech; the table is not. */
export function ChartFrame<R>({
  caption,
  rows,
  columns,
  height,
  children,
}: {
  caption: string;
  rows: R[];
  columns: Column<R>[];
  height: number;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <figure className="dash-figure" aria-labelledby={id}>
      <figcaption id={id} className="dash-figure__caption">
        <span>{caption}</span>
        <button
          type="button"
          className="dash-link-button"
          aria-pressed={asTable}
          onClick={(e) => {
            e.stopPropagation();
            setAsTable((v) => !v);
          }}
        >
          {asTable ? 'Chart' : 'Table'}
        </button>
      </figcaption>
      {asTable ? (
        <div className="dash-table-wrap">
          <DataTable caption={caption} rows={rows} columns={columns} />
        </div>
      ) : (
        <>
          <div aria-hidden="true" style={{ width: '100%', height }}>
            <ResponsiveContainer width="100%" height="100%">
              {children as React.ReactElement}
            </ResponsiveContainer>
          </div>
          <DataTable caption={caption} rows={rows} columns={columns} hidden />
        </>
      )}
    </figure>
  );
}

/** Legend labels wear the text colour; the swatch beside them carries the series identity. */
const legendText = (value: string) => <span style={{ color: 'var(--color-fg)' }}>{value}</span>;

const AXIS = { fontSize: 12, fill: 'var(--color-muted)' };
const TOOLTIP_STYLE = {
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  fontSize: 13,
  color: 'var(--color-fg)',
};

/** Horizontal single-series bars (magnitude per category). */
export function HorizontalBars({
  data,
  label,
  valueName,
}: {
  data: Array<{ name: string; value: number }>;
  label: string;
  valueName: string;
}) {
  const height = Math.max(120, data.length * 30 + 30);
  return (
    <ChartFrame
      caption={label}
      rows={data}
      height={height}
      columns={[
        { key: 'name', header: 'Status', value: (r) => r.name },
        { key: 'value', header: valueName, value: (r) => r.value, numeric: true },
      ]}
    >
      <BarChart
        accessibilityLayer={false}
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
      >
        <CartesianGrid horizontal={false} stroke="var(--color-border)" />
        <XAxis type="number" allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="name"
          width={120}
          tick={AXIS}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--color-bg)' }} />
        <Bar
          dataKey="value"
          name={valueName}
          fill="var(--chart-1)"
          radius={[0, 4, 4, 0]}
          maxBarSize={18}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFrame>
  );
}

/** Two counts per period side by side (grouped bars, one axis): equal values never hide. */
export function GroupedBars({
  data,
  label,
  series,
  xHeader,
}: {
  data: Array<Record<string, string | number>>;
  label: string;
  series: Array<{ key: string; name: string; color: string }>;
  xHeader: string;
}) {
  return (
    <ChartFrame
      caption={label}
      rows={data}
      height={220}
      columns={[
        { key: 'x', header: xHeader, value: (r) => String(r.x) },
        ...series.map((s) => ({
          key: s.key,
          header: s.name,
          value: (r: Record<string, string | number>) => r[s.key],
          numeric: true,
        })),
      ]}
    >
      <BarChart
        accessibilityLayer={false}
        data={data}
        margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
        barGap={2}
      >
        <CartesianGrid vertical={false} stroke="var(--color-border)" />
        <XAxis dataKey="x" tick={AXIS} axisLine={false} tickLine={false} minTickGap={8} />
        <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} width={32} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--color-bg)' }} />
        <Legend wrapperStyle={{ fontSize: 13 }} formatter={legendText} />
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name}
            fill={s.color}
            radius={[4, 4, 0, 0]}
            maxBarSize={18}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ChartFrame>
  );
}

/** Stacked bars per period (parts of a whole per month). */
export function StackedBars({
  data,
  label,
  series,
  xHeader,
  format,
}: {
  data: Array<Record<string, string | number>>;
  label: string;
  series: Array<{ key: string; name: string; color: string }>;
  xHeader: string;
  format: (v: number) => string;
}) {
  return (
    <ChartFrame
      caption={label}
      rows={data}
      height={240}
      columns={[
        { key: 'x', header: xHeader, value: (r) => String(r.x) },
        ...series.map((s) => ({
          key: s.key,
          header: s.name,
          value: (r: Record<string, string | number>) => format(Number(r[s.key] ?? 0)),
          numeric: true,
        })),
      ]}
    >
      <BarChart
        accessibilityLayer={false}
        data={data}
        margin={{ top: 8, right: 16, bottom: 4, left: 8 }}
      >
        <CartesianGrid vertical={false} stroke="var(--color-border)" />
        <XAxis dataKey="x" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          width={56}
          tickFormatter={(v: number) => format(v)}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: 'var(--color-bg)' }}
          formatter={(v) => format(Number(v ?? 0))}
        />
        <Legend wrapperStyle={{ fontSize: 13 }} formatter={legendText} />
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name}
            stackId="a"
            fill={s.color}
            stroke="var(--color-surface)"
            strokeWidth={2}
            maxBarSize={36}
            radius={i === series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ChartFrame>
  );
}
