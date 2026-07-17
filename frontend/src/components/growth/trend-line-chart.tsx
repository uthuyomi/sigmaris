"use client";
// 役割: Citation Precision / Contradiction Rateの推移を、/chatと統一感の
// あるダーク配色で可視化する。/timelineのevent-volume-chart.tsxと同じ
// Recharts利用パターン(BarChart→LineChartへ変更しただけ)を踏襲した。

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type TrendLine = {
  dataKey: string;
  name: string;
  color: string;
};

type TrendPoint = Record<string, string | number | null>;

type TrendLineChartProps = {
  data: TrendPoint[];
  lines: TrendLine[];
};

export function TrendLineChart({ data, lines }: TrendLineChartProps) {
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#8e8ea0", fontSize: 11 }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
            tick={{ fill: "#8e8ea0", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip
            formatter={(value) =>
              typeof value === "number" ? `${Math.round(value * 100)}%` : "未測定"
            }
            contentStyle={{
              backgroundColor: "#2a2a2a",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "0.75rem",
              color: "#ececec",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#8e8ea0" }}
          />
          {lines.map((line) => (
            <Line
              key={line.dataKey}
              type="monotone"
              dataKey={line.dataKey}
              name={line.name}
              stroke={line.color}
              strokeWidth={2}
              dot={{ r: 3, fill: line.color, strokeWidth: 0 }}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
