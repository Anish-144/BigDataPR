import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { AXIS, GRID, SERIES, TooltipBody } from "./ChartFrame";
import { fmtCompact } from "../../lib/format";

export interface SeriesDef {
  key: string;
  label: string;
  color?: string;
}

type Fmt = (v: number) => string;
const defaultFmt: Fmt = (v) => fmtCompact(v);

function makeTooltip(series: SeriesDef[], valueFmt: Fmt, labelFmt: (l: unknown) => string, kind: "line" | "rect") {
  return function ChartTooltip({ active, payload, label }: TooltipProps<number, string>) {
    if (!active || !payload || !payload.length) return null;
    const rows = series
      .map((s, i) => {
        const p = payload.find((x) => x.dataKey === s.key);
        if (!p) return null;
        const v = p.value;
        return {
          name: s.label,
          value: typeof v === "number" ? valueFmt(v) : "—",
          color: s.color ?? SERIES[i % SERIES.length],
          kind,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
    return <TooltipBody label={labelFmt(label)} rows={rows} />;
  };
}

/**
 * Time series: one series -> soft area (10% wash) + 2px line; several -> 2px lines.
 * Crosshair tooltip lists every series at the hovered X. One y-axis only.
 */
export function TimeSeriesChart({
  data,
  xKey,
  series,
  height = 220,
  yFormat = defaultFmt,
  xFormat = (v) => String(v),
  yDomain,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  series: SeriesDef[];
  height?: number;
  yFormat?: Fmt;
  xFormat?: (v: unknown) => string;
  yDomain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
}) {
  const single = series.length === 1;
  const Tip = makeTooltip(series, yFormat, xFormat, "line");
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} accessibilityLayer>
        <CartesianGrid vertical={false} {...GRID} />
        <XAxis dataKey={xKey} {...AXIS} tickFormatter={(v) => xFormat(v)} minTickGap={36} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => yFormat(v)} domain={yDomain} />
        <Tooltip content={<Tip />} cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }} isAnimationActive={false} />
        {series.map((s, i) => {
          const color = s.color ?? SERIES[i % SERIES.length];
          return single ? (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={color}
              strokeWidth={2}
              fill={color}
              fillOpacity={0.1}
              dot={false}
              activeDot={{ r: 4, fill: color, stroke: "var(--chart-surface)", strokeWidth: 2 }}
              isAnimationActive={false}
              connectNulls
            />
          ) : (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: color, stroke: "var(--chart-surface)", strokeWidth: 2 }}
              isAnimationActive={false}
              connectNulls
            />
          );
        })}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/**
 * Bars. `horizontal` draws category labels on the y axis (best for long names).
 * Marks: <=24px thick, 4px rounded data-end / square baseline, 2px gaps between bars.
 */
export function BarsChart({
  data,
  categoryKey,
  series,
  horizontal = false,
  stacked = false,
  height,
  valueFormat = defaultFmt,
  categoryFormat = (v) => String(v),
  valueDomain,
  maxCategoryWidth = 220,
}: {
  data: Record<string, unknown>[];
  categoryKey: string;
  series: SeriesDef[];
  maxCategoryWidth?: number;
  horizontal?: boolean;
  stacked?: boolean;
  height?: number;
  valueFormat?: Fmt;
  categoryFormat?: (v: unknown) => string;
  valueDomain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
}) {
  const Tip = makeTooltip(series, valueFormat, categoryFormat, "rect");
  const perCat = stacked ? 1 : series.length;
  const h = height ?? (horizontal ? Math.max(120, data.length * Math.max(26, perCat * 14 + 12) + 36) : 240);
  const longest = Math.max(4, ...data.map((d) => categoryFormat(d[categoryKey]).length));
  const catWidth = Math.min(maxCategoryWidth, Math.max(60, longest * 6.6 + 18));
  const last = series.length - 1;
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart
        data={data}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
        barGap={2}
        barCategoryGap={perCat > 1 ? "18%" : "28%"}
        accessibilityLayer
      >
        <CartesianGrid horizontal={!horizontal} vertical={horizontal} {...GRID} />
        {horizontal ? (
          <>
            <XAxis type="number" {...AXIS} tickFormatter={(v: number) => valueFormat(v)} domain={valueDomain} />
            <YAxis type="category" dataKey={categoryKey} {...AXIS} width={catWidth} tickFormatter={(v) => categoryFormat(v)} interval={0} />
          </>
        ) : (
          <>
            <XAxis dataKey={categoryKey} {...AXIS} tickFormatter={(v) => categoryFormat(v)} interval="preserveStartEnd" minTickGap={8} />
            <YAxis {...AXIS} width={52} tickFormatter={(v: number) => valueFormat(v)} domain={valueDomain} />
          </>
        )}
        <Tooltip content={<Tip />} cursor={{ fill: "rgb(var(--ink) / 0.05)" }} isAnimationActive={false} />
        {series.map((s, i) => {
          const color = s.color ?? SERIES[i % SERIES.length];
          const rounded = !stacked || i === last;
          const radius: [number, number, number, number] = !rounded ? [0, 0, 0, 0] : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
          return (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={color}
              maxBarSize={24}
              radius={radius}
              stackId={stacked ? "s" : undefined}
              stroke={stacked ? "var(--chart-surface)" : undefined}
              strokeWidth={stacked ? 2 : 0}
              isAnimationActive={false}
            />
          );
        })}
      </BarChart>
    </ResponsiveContainer>
  );
}
