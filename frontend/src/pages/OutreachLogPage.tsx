import { useQuery } from "@tanstack/react-query";
import { fetchOutreachLog } from "../api/outreach";
import { PatientUUID } from "../components/shared/PatientUUID";

const EVENT_META: Record<string, { label: string; icon: string; style: string }> = {
  offer_sent:       { label: "Offer sent",        icon: "📨", style: "bg-blue-50 text-blue-700" },
  reminder_queued:  { label: "Reminder queued",   icon: "✉",  style: "bg-gray-50 text-gray-700" },
  reminder_followup:{ label: "Follow-up queued",  icon: "⚠",  style: "bg-yellow-50 text-yellow-700" },
  follow_up_created:{ label: "Staff follow-up",   icon: "☎",  style: "bg-red-50 text-red-700" },
};

const STATUS_STYLE: Record<string, string> = {
  offered:  "bg-yellow-100 text-yellow-800",
  booked:   "bg-green-100 text-green-800",
  declined: "bg-gray-100 text-gray-500",
  expired:  "bg-red-100 text-red-700",
  queued:   "bg-blue-50 text-blue-700",
  waiting:  "bg-blue-50 text-blue-700",
};

export function OutreachLogPage() {
  const { data: events = [], isLoading } = useQuery({
    queryKey: ["outreach-log"],
    queryFn: () => fetchOutreachLog(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const offerCount   = events.filter((e) => e.event_type === "offer_sent").length;
  const reminderCount = events.filter((e) => e.event_type.startsWith("reminder")).length;
  const followUpCount = events.filter((e) => e.event_type === "follow_up_created").length;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-gray-900">Outreach Log</h1>
        <p className="text-sm text-gray-500 mt-1">
          All simulated communication events — waitlist offers, appointment reminders, and staff follow-ups.
          No messages are actually sent; all events are logged here only.
        </p>
      </div>

      {/* Summary chips */}
      <div className="flex gap-3 mb-5 flex-wrap">
        <span className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-700 text-sm font-medium px-3 py-1.5 rounded-full">
          📨 {offerCount} waitlist offer{offerCount !== 1 ? "s" : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 bg-gray-50 text-gray-700 text-sm font-medium px-3 py-1.5 rounded-full">
          ✉ {reminderCount} reminder{reminderCount !== 1 ? "s" : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 bg-red-50 text-red-700 text-sm font-medium px-3 py-1.5 rounded-full">
          ☎ {followUpCount} staff follow-up{followUpCount !== 1 ? "s" : ""}
        </span>
      </div>

      {isLoading && <p className="text-gray-400 text-sm">Loading…</p>}

      {!isLoading && events.length === 0 && (
        <div className="bg-white rounded-xl shadow px-6 py-10 text-center text-gray-400 text-sm">
          No outreach events yet. They appear when appointments are booked, waitlist offers are sent,
          or reminders are queued.
        </div>
      )}

      {events.length > 0 && (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Timestamp</th>
                <th className="px-4 py-3 text-left">Patient</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Message preview</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Slot</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {events.map((e) => {
                const meta = EVENT_META[e.event_type] ?? { label: e.event_type, icon: "•", style: "bg-gray-50 text-gray-700" };
                return (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                      {new Date(e.at).toLocaleString([], {
                        month: "short", day: "numeric",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <PatientUUID uuid={e.patient_uuid} label="" />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${meta.style}`}>
                        <span aria-hidden="true">{meta.icon}</span>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-xs">
                      <p className="truncate text-xs" title={e.message_preview}>
                        {e.message_preview}
                      </p>
                      {(e.provider_name || e.visit_type_name) && (
                        <p className="text-xs text-gray-400 mt-0.5">
                          {[e.visit_type_name, e.provider_name].filter(Boolean).join(" · ")}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLE[e.status] ?? "bg-gray-100 text-gray-600"}`}>
                        {e.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {e.slot_time
                        ? new Date(e.slot_time).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-3 border-t text-xs text-gray-400">
            {events.length} event{events.length !== 1 ? "s" : ""} · No messages were actually sent — simulation only
          </div>
        </div>
      )}
    </div>
  );
}
