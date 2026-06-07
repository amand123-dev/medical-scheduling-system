import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import { useQuery } from "@tanstack/react-query";
import { fetchAppointments, fetchBlocks } from "../../api/appointments";
import type { Appointment, AppointmentStatus, Provider, VisitType } from "../../types";

const STATUS_COLORS: Record<AppointmentStatus, string> = {
  scheduled: "#3b82f6",
  completed: "#22c55e",
  cancelled: "#9ca3af",
  no_show: "#ef4444",
};

function outreachInfo(risk: number | null): { dot: string; label: string } | null {
  if (risk === null) return null;
  if (risk >= 0.5) return { dot: "🔴", label: "High outreach" };
  if (risk >= 0.2) return { dot: "🟡", label: "Med outreach" };
  return { dot: "🟢", label: "Low outreach" };
}

function providerInitials(name: string): string {
  return name
    .replace(/^Dr\.\s*/, "")
    .split(" ")
    .map((w) => w[0] ?? "")
    .join("");
}

interface Props {
  providerId?: string;
  onEventClick?: (appointment: Appointment) => void;
  providers?: Provider[];
  visitTypes?: VisitType[];
}

export function AppointmentCalendar({
  providerId,
  onEventClick,
  providers = [],
  visitTypes = [],
}: Props) {
  const provMap = Object.fromEntries(providers.map((p) => [p.id, p.name]));
  const vtMap = Object.fromEntries(visitTypes.map((v) => [v.id, v.name]));

  const { data: appointments = [] } = useQuery({
    queryKey: ["appointments", providerId],
    queryFn: () => fetchAppointments(providerId),
  });

  const { data: blocks = [] } = useQuery({
    queryKey: ["schedule-blocks", providerId],
    queryFn: () => fetchBlocks(providerId),
  });

  const apptEvents = appointments.map((a) => ({
    id: a.id,
    title: vtMap[a.visit_type_id] ?? "Appointment",
    start: a.start_time,
    end: a.end_time,
    backgroundColor: STATUS_COLORS[a.status],
    borderColor: STATUS_COLORS[a.status],
    extendedProps: { appointment: a },
  }));

  const blockEvents = blocks.map((b) => ({
    id: `block-${b.id}`,
    title: b.reason ? `Blocked: ${b.reason}` : b.provider_id ? "Provider blocked" : "Clinic closed",
    start: b.start_date,
    end: b.end_date,
    display: "background" as const,
    backgroundColor: "#fca5a5",
    allDay: true,
  }));

  return (
    <div className="bg-white rounded-xl shadow p-4">
      {/* Legend — color always paired with label and icon, never color alone */}
      <div className="flex gap-4 mb-3 text-xs flex-wrap items-center">
        {(Object.entries(STATUS_COLORS) as [AppointmentStatus, string][]).map(([status, color]) => (
          <span key={status} className="flex items-center gap-1 text-gray-600">
            <span className="inline-block w-3 h-3 rounded-sm" style={{ background: color }} aria-hidden="true" />
            {status.replace("_", " ")}
          </span>
        ))}
        <span className="flex items-center gap-1 text-gray-600">
          <span className="inline-block w-3 h-3 rounded-sm bg-red-300" aria-hidden="true" />
          blocked / closed
        </span>
        <span className="text-gray-400">·</span>
        <span className="text-gray-600">Reminder plan: 🟢 low · 🟡 med · 🔴 high outreach</span>
      </div>

      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
        initialView="timeGridWeek"
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,timeGridWeek,timeGridDay",
        }}
        slotMinTime="07:00:00"
        slotMaxTime="19:00:00"
        events={[...apptEvents, ...blockEvents]}
        eventContent={(arg) => {
          const appt = arg.event.extendedProps?.appointment as Appointment | undefined;
          if (!appt) return undefined; // background block events use default rendering
          const vt = vtMap[appt.visit_type_id] ?? "Appt";
          const initials = providerInitials(provMap[appt.provider_id] ?? "");
          const outreach = outreachInfo(appt.no_show_risk);
          const durationMins =
            arg.event.start && arg.event.end
              ? (arg.event.end.getTime() - arg.event.start.getTime()) / 60000
              : 60;

          // Short slots (≤30 min): single compact line
          if (durationMins <= 30) {
            return (
              <div className="text-xs px-1 py-0.5 truncate font-medium leading-tight">
                {outreach ? `${outreach.dot} ` : ""}{vt}
                {initials ? ` · ${initials}` : ""}
              </div>
            );
          }

          // Standard two-line layout
          return (
            <div className="text-xs px-1 py-0.5 overflow-hidden h-full flex flex-col gap-0.5">
              <div className="font-semibold leading-tight truncate">{vt}</div>
              <div className="opacity-90 leading-tight truncate">
                {initials}
                {outreach && <span> · {outreach.dot} {outreach.label}</span>}
              </div>
            </div>
          );
        }}
        eventClick={(info) => {
          if (onEventClick) {
            const appt = info.event.extendedProps?.appointment as Appointment | undefined;
            if (appt) onEventClick(appt);
          }
        }}
        height="auto"
      />
    </div>
  );
}
