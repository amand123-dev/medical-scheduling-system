import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell } from "recharts";
import { fetchDashboardMetrics } from "../api/appointments";
import { Legend } from "../components/shared/Legend";

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl shadow p-6">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className="text-3xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function DonutChart({
  value,
  color,
  label,
  sub,
}: {
  value: number;
  color: string;
  label: string;
  sub: string;
}) {
  const data = [
    { name: "filled", value },
    { name: "rest", value: 1 - value },
  ];
  return (
    <div className="bg-white rounded-xl shadow p-6 flex flex-col items-center">
      <p className="text-sm text-gray-500 mb-3">{label}</p>
      <div className="relative">
        <PieChart width={120} height={120}>
          <Pie
            data={data}
            innerRadius={38}
            outerRadius={55}
            dataKey="value"
            startAngle={90}
            endAngle={-270}
            strokeWidth={0}
          >
            <Cell fill={color} />
            <Cell fill="#f3f4f6" />
          </Pie>
        </PieChart>
        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-gray-900">
          {(value * 100).toFixed(0)}%
        </span>
      </div>
      <p className="text-xs text-gray-400 mt-2 text-center">{sub}</p>
    </div>
  );
}

const DAY_OPTIONS = [7, 30, 90] as const;

export function DashboardPage() {
  const [days, setDays] = useState<number>(30);

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", days],
    queryFn: () => fetchDashboardMetrics(days),
  });

  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-4 py-1.5 font-medium transition-colors ${
                days === d
                  ? "bg-blue-600 text-white"
                  : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-white rounded-xl shadow p-6 animate-pulse">
              <div className="h-3 bg-gray-200 rounded w-24 mb-3" />
              <div className="h-8 bg-gray-200 rounded w-20 mb-2" />
              <div className="h-2 bg-gray-100 rounded w-32" />
            </div>
          ))}
        </div>
      )}

      {!isLoading && data && (
        <>
          <p className="text-xs text-gray-400 mb-4">Rolling {data.days} days</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <MetricCard
              label="Fill Rate"
              value={pct(data.fill_rate)}
              sub="Completed ÷ (scheduled + completed)"
            />
            <MetricCard
              label="No-Show Rate"
              value={pct(data.no_show_rate)}
              sub="No-shows ÷ total booked"
            />
            <MetricCard
              label="Slots Recovered"
              value={String(data.slots_recovered)}
              sub="Via waitlist backfill"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <DonutChart
              value={data.fill_rate}
              color="#22c55e"
              label="Fill Rate"
              sub="Completed appointments"
            />
            <DonutChart
              value={data.no_show_rate}
              color="#ef4444"
              label="No-Show Rate"
              sub="Missed appointments"
            />
          </div>
        </>
      )}

      <Legend />
    </div>
  );
}
