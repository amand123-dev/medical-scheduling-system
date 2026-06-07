import { useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAppointment, fetchAppointments, fetchProviders, fetchVisitTypes, findNextAvailable } from "../../api/appointments";
import { useAuthStore } from "../../store/auth";

interface Props {
  onClose: () => void;
  prefillDate?: string;
}

export function BookingModal({ onClose, prefillDate }: Props) {
  const qc = useQueryClient();
  const { role, providerId: myProviderId } = useAuthStore();
  const isProvider = role === "provider";

  const { data: providers = [] } = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const { data: visitTypes = [] } = useQuery({ queryKey: ["visitTypes"], queryFn: fetchVisitTypes });
  const { data: allAppointments = [] } = useQuery({ queryKey: ["appointments"], queryFn: () => fetchAppointments() });

  // Distinct patient UUIDs known to the system (from appointment history)
  const knownPatientUuids = useMemo(
    () => [...new Set(allAppointments.map((a) => a.patient_uuid))],
    [allAppointments]
  );

  // Providers are pre-locked to their own ID
  const [providerId, setProviderId] = useState(isProvider ? (myProviderId ?? "") : "");
  const [visitTypeId, setVisitTypeId] = useState("");
  const [patientUuid, setPatientUuid] = useState("");
  const [startTime, setStartTime] = useState(prefillDate ?? "");
  const [error, setError] = useState("");
  const [nextSlotLoading, setNextSlotLoading] = useState(false);

  const mutation = useMutation({
    mutationFn: createAppointment,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["appointments"] });
      onClose();
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      // FastAPI returns an array of validation errors on 422
      const msg = Array.isArray(detail)
        ? detail.map((e: { loc?: string[]; msg?: string }) => `${e.loc?.slice(1).join(".")} — ${e.msg}`).join(" | ")
        : typeof detail === "string"
          ? detail
          : "Failed to book appointment.";
      setError(msg);
      console.error("Booking 422 detail:", detail);
    },
  });

  async function handleFindNextSlot() {
    if (!providerId || !visitTypeId) return;
    setNextSlotLoading(true);
    setError("");
    try {
      const result = await findNextAvailable(providerId, visitTypeId);
      const d = new Date(result.start_time);
      const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      setStartTime(local);
    } catch {
      setError("No available slot found in the next 60 days.");
    } finally {
      setNextSlotLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    // datetime-local gives local time with no tz — convert to UTC ISO so the backend stores
    // the correct absolute time and FullCalendar renders it at the right local hour.
    const utcStart = new Date(startTime).toISOString();
    mutation.mutate({ provider_id: providerId, patient_uuid: patientUuid, visit_type_id: visitTypeId, start_time: utcStart });
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-lg p-6 w-full max-w-md">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">Book Appointment</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Patient UUID
              <span className="ml-1 text-xs text-gray-400 font-normal">
                ({knownPatientUuids.length} known — type or select)
              </span>
            </label>
            <input
              type="text"
              list="known-patients"
              value={patientUuid}
              onChange={(e) => setPatientUuid(e.target.value)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
              required
            />
            <datalist id="known-patients">
              {knownPatientUuids.map((uuid) => (
                <option key={uuid} value={uuid} />
              ))}
            </datalist>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
            {isProvider ? (
              <input
                type="text"
                value={providers.find((p) => p.id === myProviderId)?.name ?? "My schedule"}
                readOnly
                className="w-full border border-gray-200 bg-gray-50 rounded-lg px-3 py-2 text-sm text-gray-600 cursor-not-allowed"
              />
            ) : (
              <select
                value={providerId}
                onChange={(e) => setProviderId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                required
              >
                <option value="">Select provider…</option>
                {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Visit Type</label>
            <select
              value={visitTypeId}
              onChange={(e) => setVisitTypeId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              required
            >
              <option value="">Select visit type…</option>
              {visitTypes.map((v) => (
                <option key={v.id} value={v.id}>{v.name} ({v.duration_minutes} min)</option>
              ))}
            </select>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">Start Time</label>
              {providerId && visitTypeId && (
                <button
                  type="button"
                  onClick={handleFindNextSlot}
                  disabled={nextSlotLoading}
                  className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-50"
                >
                  {nextSlotLoading ? "Finding…" : "Find next available slot"}
                </button>
              )}
            </div>
            <input
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              required
            />
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending ? "Booking…" : "Book"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
