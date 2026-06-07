import type { RiskBucket } from "../../types";

const config: Record<RiskBucket, { label: string; icon: string; className: string }> = {
  low: { label: "Low risk", icon: "✓", className: "bg-green-100 text-green-800" },
  medium: { label: "Med risk", icon: "⚠", className: "bg-yellow-100 text-yellow-800" },
  high: { label: "High risk", icon: "!", className: "bg-red-100 text-red-800" },
  insufficient_data: { label: "No data", icon: "?", className: "bg-gray-100 text-gray-500" },
};

export function RiskBadge({ bucket }: { bucket: RiskBucket }) {
  const { label, icon, className } = config[bucket];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${className}`}>
      <span aria-hidden="true">{icon}</span>
      {label}
    </span>
  );
}
