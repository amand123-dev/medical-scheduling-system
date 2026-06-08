import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  bookMyAppointment,
  fetchProvidersPublic,
  fetchVisitTypesPublic,
  findNextAvailablePublic,
  joinWaitlist,
} from "../../api/patient";
import { usePatientAuthStore } from "../../store/patientAuth";
import type { NextAvailable } from "../../types";

export function PatientBookPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const patientUuid = usePatientAuthStore((s) => s.patientUuid);

  const [providerId, setProviderId] = useState("");
  const [visitTypeId, setVisitTypeId] = useState("");
  const [slot, setSlot] = useState<NextAvailable | null>(null);
  const [findError, setFindError] = useState<string | null>(null);
  const [bookError, setBookError] = useState<string | null>(null);
  const [joined, setJoined] = useState(false);

  const { data: providers = [] } = useQuery({
    queryKey: ["providers-public"],
    queryFn: fetchProvidersPublic,
  });
  const { data: visitTypes = [] } = useQuery({
    queryKey: ["visit-types-public"],
    queryFn: fetchVisitTypesPublic,
  });

  const findMut = useMutation({
    mutationFn: () => findNextAvailablePublic(providerId, visitTypeId),
    onSuccess: (data) => {
      setSlot(data);
      setFindError(null);
    },
    onError: () => setFindError("No available slots found. You can join the waitlist instead."),
  });

  const bookMut = useMutation({
    mutationFn: () =>
      bookMyAppointment({
        provider_id: providerId,
        patient_uuid: patientUuid!,
        visit_type_id: visitTypeId,
        start_time: slot!.start_time,
      }),
    onSuccess: () => navigate("/portal/dashboard"),
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Booking failed. Please try again.";
      setBookError(msg);
    },
  });

  const waitlistMut = useMutation({
    mutationFn: () => joinWaitlist({ provider_id: providerId, visit_type_id: visitTypeId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-waitlist"] });
      setJoined(true);
    },
  });

  const activeProviders = providers.filter((p) => p.is_active);
  const canSearch = providerId && visitTypeId;

  if (joined) {
    return (
      <div className="max-w-lg mx-auto px-4 py-8 text-center">
        <div className="bg-white border border-green-200 rounded-2xl p-8">
          <p className="text-4xl mb-3">✓</p>
          <h2 className="text-xl font-bold text-gray-900 mb-2">You're on the waitlist</h2>
          <p className="text-sm text-gray-500 mb-6">
            We'll notify you when a slot opens up. You can accept or decline from your dashboard.
          </p>
          <Link
            to="/portal/dashboard"
            className="inline-block bg-blue-600 text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-blue-700"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-lg mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Book an appointment</h1>

      <div className="bg-white border border-gray-200 rounded-2xl p-6 space-y-5">
        {/* Provider select */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
          <select
            value={providerId}
            onChange={(e) => {
              setProviderId(e.target.value);
              setSlot(null);
              setFindError(null);
            }}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select a provider…</option>
            {activeProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.specialty ? ` — ${p.specialty}` : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Visit type select */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Visit type</label>
          <select
            value={visitTypeId}
            onChange={(e) => {
              setVisitTypeId(e.target.value);
              setSlot(null);
              setFindError(null);
            }}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select visit type…</option>
            {visitTypes.map((vt) => (
              <option key={vt.id} value={vt.id}>
                {vt.name} ({vt.duration_minutes} min)
              </option>
            ))}
          </select>
        </div>

        {/* Find slot button */}
        <button
          onClick={() => findMut.mutate()}
          disabled={!canSearch || findMut.isPending}
          className="w-full bg-gray-900 text-white rounded-lg py-2 text-sm font-medium hover:bg-gray-800 disabled:opacity-40 transition-colors"
        >
          {findMut.isPending ? "Finding slot…" : "Find next available slot"}
        </button>

        {/* No slot found — offer waitlist */}
        {findError && (
          <div className="border border-yellow-200 bg-yellow-50 rounded-xl p-4 space-y-3">
            <p className="text-sm text-yellow-800">{findError}</p>
            <button
              onClick={() => waitlistMut.mutate()}
              disabled={waitlistMut.isPending}
              className="w-full bg-yellow-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-yellow-700 disabled:opacity-50"
            >
              {waitlistMut.isPending ? "Joining…" : "Join waitlist"}
            </button>
          </div>
        )}

        {/* Slot found — confirm or join waitlist */}
        {slot && (
          <div className="border border-blue-200 bg-blue-50 rounded-xl p-4 space-y-3">
            <div>
              <p className="text-sm font-semibold text-gray-900">
                {format(parseISO(slot.start_time), "EEEE, MMMM d, yyyy")}
              </p>
              <p className="text-sm text-gray-600">
                {format(parseISO(slot.start_time), "h:mm a")} –{" "}
                {format(parseISO(slot.end_time), "h:mm a")}
              </p>
            </div>

            {bookError && (
              <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{bookError}</p>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => bookMut.mutate()}
                disabled={bookMut.isPending}
                className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {bookMut.isPending ? "Booking…" : "Confirm booking"}
              </button>
              <button
                onClick={() => {
                  setSlot(null);
                  findMut.mutate();
                }}
                disabled={findMut.isPending}
                className="flex-1 border border-gray-300 text-gray-700 rounded-lg py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
              >
                Next slot
              </button>
            </div>

            <button
              onClick={() => waitlistMut.mutate()}
              disabled={waitlistMut.isPending}
              className="w-full text-sm text-gray-500 hover:text-gray-700 underline"
            >
              {waitlistMut.isPending ? "Joining…" : "Join waitlist for earlier slot instead"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
