import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  acceptMyOffer,
  cancelMyAppointment,
  declineMyOffer,
  fetchMyAppointments,
  fetchMyWaitlist,
  fetchPatientMe,
} from "../../api/patient";
import type { Appointment, WaitlistEntry } from "../../types";

function statusBadge(status: string) {
  const map: Record<string, string> = {
    scheduled: "bg-green-100 text-green-700",
    completed: "bg-gray-100 text-gray-600",
    cancelled: "bg-red-100 text-red-600",
    no_show: "bg-orange-100 text-orange-700",
    waiting: "bg-yellow-100 text-yellow-700",
    offered: "bg-blue-100 text-blue-700",
    booked: "bg-green-100 text-green-700",
    declined: "bg-gray-100 text-gray-500",
    expired: "bg-gray-100 text-gray-400",
  };
  return `text-xs px-2 py-0.5 rounded font-medium ${map[status] ?? "bg-gray-100 text-gray-600"}`;
}

function AppointmentCard({
  appt,
  onCancel,
  cancelling,
}: {
  appt: Appointment;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const dt = parseISO(appt.start_time);
  return (
    <div className="flex items-center justify-between p-4 border border-gray-200 rounded-xl bg-white">
      <div>
        <p className="font-medium text-gray-900 text-sm">{format(dt, "EEEE, MMM d, yyyy")}</p>
        <p className="text-gray-500 text-sm">{format(dt, "h:mm a")}</p>
      </div>
      <div className="flex items-center gap-3">
        <span className={statusBadge(appt.status)}>{appt.status.replace("_", " ")}</span>
        {appt.status === "scheduled" && (
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50 font-medium"
          >
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        )}
      </div>
    </div>
  );
}

function WaitlistCard({
  entry,
  onAccept,
  onDecline,
  busy,
}: {
  entry: WaitlistEntry;
  onAccept: () => void;
  onDecline: () => void;
  busy: boolean;
}) {
  const isOffered = entry.status === "offered";
  const slotStart = entry.offered_slot_start ? parseISO(entry.offered_slot_start) : null;

  return (
    <div
      className={`p-4 border rounded-xl bg-white ${isOffered ? "border-blue-300 bg-blue-50" : "border-gray-200"}`}
    >
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium text-gray-900">
          {isOffered && slotStart
            ? `Slot offered: ${format(slotStart, "MMM d 'at' h:mm a")}`
            : "On waitlist"}
        </p>
        <span className={statusBadge(entry.status)}>{entry.status}</span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Requested {format(parseISO(entry.requested_at), "MMM d, yyyy")}
      </p>
      {isOffered && (
        <div className="flex gap-2">
          <button
            onClick={onAccept}
            disabled={busy}
            className="flex-1 bg-blue-600 text-white text-sm py-1.5 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            Accept slot
          </button>
          <button
            onClick={onDecline}
            disabled={busy}
            className="flex-1 border border-gray-300 text-gray-700 text-sm py-1.5 rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            Decline
          </button>
        </div>
      )}
    </div>
  );
}

export function PatientDashboard() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["patient-me"], queryFn: fetchPatientMe });
  const { data: appointments = [], isLoading: apptLoading } = useQuery({
    queryKey: ["my-appointments"],
    queryFn: fetchMyAppointments,
  });
  const { data: waitlist = [], isLoading: wlLoading } = useQuery({
    queryKey: ["my-waitlist"],
    queryFn: fetchMyWaitlist,
  });

  const cancelMut = useMutation({
    mutationFn: cancelMyAppointment,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-appointments"] }),
  });

  const acceptMut = useMutation({
    mutationFn: acceptMyOffer,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-waitlist"] });
      qc.invalidateQueries({ queryKey: ["my-appointments"] });
    },
  });

  const declineMut = useMutation({
    mutationFn: declineMyOffer,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-waitlist"] }),
  });

  const upcoming = appointments
    .filter((a) => a.status === "scheduled")
    .sort((a, b) => a.start_time.localeCompare(b.start_time));

  const past = appointments
    .filter((a) => a.status !== "scheduled")
    .sort((a, b) => b.start_time.localeCompare(a.start_time))
    .slice(0, 5);

  const activeWaitlist = waitlist.filter((w) =>
    ["waiting", "offered"].includes(w.status)
  );

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-8">
      {me && (
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Welcome, {me.first_name}
          </h1>
          <p className="text-gray-500 text-sm mt-0.5">{me.email}</p>
        </div>
      )}

      {/* Upcoming appointments */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-900">Upcoming appointments</h2>
          <a
            href="/portal/book"
            className="text-sm text-blue-600 hover:underline font-medium"
          >
            Book new +
          </a>
        </div>
        {apptLoading ? (
          <p className="text-sm text-gray-400">Loading…</p>
        ) : upcoming.length === 0 ? (
          <p className="text-sm text-gray-500 bg-gray-50 rounded-xl p-4 text-center">
            No upcoming appointments.{" "}
            <a href="/portal/book" className="text-blue-600 hover:underline">
              Book one now.
            </a>
          </p>
        ) : (
          <div className="space-y-3">
            {upcoming.map((a) => (
              <AppointmentCard
                key={a.id}
                appt={a}
                onCancel={() => cancelMut.mutate(a.id)}
                cancelling={cancelMut.isPending && cancelMut.variables === a.id}
              />
            ))}
          </div>
        )}
      </section>

      {/* Waitlist */}
      {(wlLoading || activeWaitlist.length > 0) && (
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-3">Waitlist spots</h2>
          {wlLoading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : (
            <div className="space-y-3">
              {activeWaitlist.map((w) => (
                <WaitlistCard
                  key={w.id}
                  entry={w}
                  onAccept={() => acceptMut.mutate(w.id)}
                  onDecline={() => declineMut.mutate(w.id)}
                  busy={
                    (acceptMut.isPending && acceptMut.variables === w.id) ||
                    (declineMut.isPending && declineMut.variables === w.id)
                  }
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Past appointments */}
      {past.length > 0 && (
        <section>
          <h2 className="text-base font-semibold text-gray-900 mb-3">Recent history</h2>
          <div className="space-y-2">
            {past.map((a) => (
              <AppointmentCard
                key={a.id}
                appt={a}
                onCancel={() => cancelMut.mutate(a.id)}
                cancelling={false}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
