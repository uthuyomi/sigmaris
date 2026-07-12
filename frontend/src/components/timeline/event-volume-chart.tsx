"use client";
// 役割: event種別記憶の週次件数を、/chatと統一感のあるダーク配色で可視化する。

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EventVolumePoint } from "@/lib/timeline/transform";

type EventVolumeChartProps = {
  data: EventVolumePoint[];
};

export function EventVolumeChart({ data }: EventVolumeChartProps) {
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#8e8ea0", fontSize: 11 }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "#8e8ea0", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <Tooltip
            cursor={{ fill: "rgba(155,89,182,0.12)" }}
            contentStyle={{
              backgroundColor: "#2a2a2a",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "0.75rem",
              color: "#ececec",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#8e8ea0" }}
          />
          <Bar dataKey="count" name="出来事の件数" fill="#9b59b6" radius={[6, 6, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
