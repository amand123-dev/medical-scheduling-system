import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelAppointment,
  completeAppointment,
  fetchMLRisk,
  fetchProviders,
  fetchReminders,
  fetchVisitTypes,
  noShowAppointment,
} from "../api/appointments";
import { AppointmentCalendar } from "../components/Calendar/AppointmentCalendar";
import { BookingModal } from "../components/Booking/BookingModal";
import { CancellationBackfillPanel } from "../components/Booking/CancellationBackfillPanel";
import { StatusBadge } from "../components/shared/StatusBadge";
import { RiskBadge } from "../components/shared/RiskBadge";
import { PatientUUID } from "../components/shared/PatientUUID";
import { useAuthStore } from "../store/auth";
import type { Appointment, RiskBucket } from "../types";

const REMINDER_ICON: Record<string, string> = {
  standard: "✉",
  followup: "⚠",
  call_requested: "☎",
};
const REMINDER_LABEL: Record<string, string> = {
  standard: "Standard reminder",
  followup: "Follow-up reminder",
  call_requested: "Call requested",
};
const REMINDER_STYLE: Record<string, string> = {
  standard: "bg-blue-50 text-blue-700",
  followup: "bg-yellow-50 text-yellow-700",
  call_requested: "bg-red-50 text-red-700",
};

export function CalendarPage() {
  const qc = useQueryClient();
  const { role, providerId: myProviderId } = useAuthStore();
  const isProvider = role === "provider";

  const [showBooking, setShowBooking] = useState(false);
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [filterProvider, setFilterProvider] = useState(isProvider ? (myProviderId ?? "") : "");
  const [showReminders, setShowReminders] = useState(false);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const [backfillAppt, setBackfillAppt] = useState<Appointment | null>(null);
  const [backfillBanner, setBackfillBanner] = useState<string | null>(null);
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: providers = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: fetchProviders,
  });
  const { data: visitTypes = [] } = useQuery({
    queryKey: ["visitTypes"],
    queryFn: fetchVisitTypes,
  });

  const vtMap = Object.fromEntries(visitTypes.map((v) => [v.id, v.name]));
  const provMap = Object.fromEntries(providers.map((p) => [p.id, p.name]));

  const cancelMut = useMutation({
    mutationFn: cancelAppointment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["appointments"] });
      qc.invalidateQueries({ queryKey: ["waitlist"] });
      // Transition to backfill panel instead of just a banner
      setBackfillAppt(selected);
      setSelected(null);
      setCancelConfirm(false);
    },
  });
  const completeMut = useMutation({
    mutationFn: completeAppointment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["appointments"] });
      setSelected(null);
    },
  });
  const noShowMut = useMutation({
    mutationFn: noShowAppointment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["appointments"] });
      setSelected(null);
    },
  });

  useEffect(() => () => { if (bannerTimer.current) clearTimeout(bannerTimer.current); }, []);

  const { data: reminders = [] } = useQuery({
    queryKey: ["reminders", selected?.id],
    queryFn: () => fetchReminders(selected!.id),
    enabled: showReminders && selected != null,
  });

  const { data: mlRisk, isLoading: mlLoading } = useQuery({
    queryKey: ["mlRisk", selected?.patient_uuid],
    queryFn: () => fetchMLRisk(selected!.patient_uuid),
    enabled: selected != null,
    retry: false,
  });

  function riskBucket(risk: number | null): RiskBucket {
    if (risk === null) return "insufficient_data";
    if (risk < 0.2) return "low";
    if (risk < 0.5) return "medium";
    return "high";
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Backfill banner */}
      {backfillBanner && (
        <div className="mb-4 flex items-center justify-between bg-green-50 border border-green-200 text-green-800 text-sm rounded-lg px-4 py-3">
          <span>✓ {backfillBanner}</span>
          <button
            onClick={() => setBackfillBanner(null)}
            className="text-green-600 hover:text-green-900 ml-4 font-medium"
          >
            &times;
          </button>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">Appointment Calendar</h1>
        <div className="flex gap-3 items-center">
          {/* Providers are locked to their own view; admin/front_desk can switch */}
          {!isProvider ? (
            <select
              value={filterProvider}
              onChange={(e) => setFilterProvider(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All providers</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          ) : (
            <span className="text-sm text-gray-500">
              {providers.find((p) => p.id === myProviderId)?.name ?? "My schedule"}
            </span>
          )}
          <button
            onClick={() => setShowBooking(true)}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
          >
            + Book Appointment
          </button>
        </div>
      </div>

      <AppointmentCalendar
        providerId={filterProvider || undefined}
        onEventClick={setSelected}
        providers={providers}
        visitTypes={visitTypes}
      />

      {showBooking && <BookingModal onClose={() => setShowBooking(false)} />}

      {backfillAppt && (
        <CancellationBackfillPanel
          providerId={backfillAppt.provider_id}
          visitTypeId={backfillAppt.visit_type_id}
          onClose={() => setBackfillAppt(null)}
        />
      )}

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-lg p-6 w-full max-w-sm">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Appointment Details</h2>
              <button
                onClick={() => { setSelected(null); setShowReminders(false); }}
                className="text-gray-400 hover:text-gray-600 text-xl"
              >
                &times;
              </button>
            </div>

            {/* Tab bar */}
            <div className="flex border-b mb-4 text-sm">
              <button
                onClick={() => setShowReminders(false)}
                className={`px-3 py-2 font-medium ${!showReminders ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
              >
                Details
              </button>
              <button
                onClick={() => setShowReminders(true)}
                className={`px-3 py-2 font-medium ${showReminders ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
              >
                Reminders
              </button>
            </div>

            {!showReminders ? (
              <>
                <dl className="space-y-2 text-sm mb-4">
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Visit type</dt>
                    <dd className="font-medium">{vtMap[selected.visit_type_id] ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Provider</dt>
                    <dd>{provMap[selected.provider_id] ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Status</dt>
                    <dd><StatusBadge status={selected.status} /></dd>
                  </div>
                  <div className="flex justify-between items-center">
                    <dt className="text-gray-500">
                      No-show risk <span className="text-xs text-gray-400">(history)</span>
                    </dt>
                    <dd><RiskBadge bucket={riskBucket(selected.no_show_risk)} /></dd>
                  </div>
                  <div className="flex justify-between items-center">
                    <dt className="text-gray-500">
                      No-show risk <span className="text-xs font-medium text-purple-600">(ML demo)</span>
                    </dt>
                    <dd>
                      {mlLoading ? (
                        <span className="text-xs text-gray-400">…</span>
                      ) : mlRisk ? (
                        <RiskBadge bucket={(mlRisk.bucket as RiskBucket) ?? "insufficient_data"} />
                      ) : (
                        <span className="text-xs text-gray-400">unavailable</span>
                      )}
                    </dd>
                  </div>
                  {mlRisk && (
                    <div className="flex items-start gap-1.5 bg-purple-50 text-purple-700 text-xs rounded px-2 py-1.5">
                      <span aria-hidden="true">🧪</span>
                      <span>ML demo — Kaggle model with synthetic demographic features. Not for clinical use.</span>
                    </div>
                  )}
                  {riskBucket(selected.no_show_risk) === "high" && (
                    <div className="flex items-center gap-2 bg-red-50 text-red-700 text-xs rounded px-2 py-1.5">
                      <span aria-hidden="true">☎</span>
                      <span>Call requested — front desk follow-up needed</span>
                    </div>
                  )}
                  <div className="flex justify-between items-center">
                    <dt className="text-gray-500">Patient</dt>
                    <dd><PatientUUID uuid={selected.patient_uuid} /></dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Start</dt>
                    <dd>{new Date(selected.start_time).toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">End</dt>
                    <dd>{new Date(selected.end_time).toLocaleString()}</dd>
                  </div>
                </dl>
                {selected.status === "scheduled" && !cancelConfirm && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => completeMut.mutate(selected.id)}
                      disabled={completeMut.isPending}
                      className="flex-1 bg-green-600 text-white rounded-lg py-2 text-sm hover:bg-green-700 disabled:opacity-50"
                    >
                      Complete
                    </button>
                    <button
                      onClick={() => noShowMut.mutate(selected.id)}
                      disabled={noShowMut.isPending}
                      className="flex-1 bg-yellow-500 text-white rounded-lg py-2 text-sm hover:bg-yellow-600 disabled:opacity-50"
                    >
                      No-show
                    </button>
                    <button
                      onClick={() => setCancelConfirm(true)}
                      className="flex-1 bg-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-300"
                    >
                      Cancel
                    </button>
                  </div>
                )}

                {/* Cancellation confirmation step */}
                {selected.status === "scheduled" && cancelConfirm && (
                  <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 text-sm">
                    <p className="font-medium text-orange-800 mb-2">Cancel this appointment?</p>
                    <p className="text-orange-700 text-xs mb-3">
                      The slot will be freed and the backfill engine will rank waiting patients
                      for this provider and visit type.
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setCancelConfirm(false)}
                        className="flex-1 px-3 py-1.5 text-xs border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
                      >
                        Keep appointment
                      </button>
                      <button
                        onClick={() => cancelMut.mutate(selected.id)}
                        disabled={cancelMut.isPending}
                        className="flex-1 px-3 py-1.5 text-xs bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                      >
                        {cancelMut.isPending ? "Cancelling…" : "Confirm cancel"}
                      </button>
                    </div>
                  </div>
                )}

                {/* Close button for terminal statuses */}
                {(selected.status === "completed" || selected.status === "cancelled" || selected.status === "no_show") && (
                  <button
                    onClick={() => { setSelected(null); setShowReminders(false); }}
                    className="w-full bg-gray-100 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-200"
                  >
                    Close
                  </button>
                )}
              </>
            ) : (
              <div className="space-y-2">
                {reminders.length === 0 ? (
                  <p className="text-sm text-gray-400">No reminders logged.</p>
                ) : (
                  reminders.map((r) => (
                    <div
                      key={r.id}
                      className={`flex items-start gap-2 rounded px-3 py-2 text-sm ${REMINDER_STYLE[r.message_type] ?? "bg-gray-50 text-gray-700"}`}
                    >
                      <span aria-hidden="true" className="mt-0.5">{REMINDER_ICON[r.message_type]}</span>
                      <div>
                        <p className="font-medium">{REMINDER_LABEL[r.message_type]}</p>
                        <p className="text-xs opacity-75">
                          via {r.channel} · {new Date(r.sent_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
