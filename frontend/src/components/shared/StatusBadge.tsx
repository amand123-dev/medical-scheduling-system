import type { AppointmentStatus } from "../../types";

const config: Record<AppointmentStatus, { label: string; icon: string; className: string }> = {
  scheduled: { label: "Scheduled", icon: "📅", className: "bg-blue-100 text-blue-800" },
  completed: { label: "Completed", icon: "✓", className: "bg-green-100 text-green-800" },
  cancelled: { label: "Cancelled", icon: "✕", className: "bg-gray-100 text-gray-500" },
  no_show: { label: "No-show", icon: "✗", className: "bg-red-100 text-red-800" },
};

export function StatusBadge({ status }: { status: AppointmentStatus }) {
  const { label, icon, className } = config[status];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${className}`}>
      <span aria-hidden="true">{icon}</span>
      {label}
    </span>
  );
}
