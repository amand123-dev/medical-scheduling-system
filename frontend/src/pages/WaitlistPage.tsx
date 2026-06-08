import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWaitlist, acceptOffer, declineOffer, offerSlot } from "../api/waitlist";
import { fetchProviders, fetchVisitTypes } from "../api/appointments";
import { useAuthStore } from "../store/auth";
import { PatientUUID } from "../components/shared/PatientUUID";
import type { WaitlistEntry } from "../types";

// ── Hold countdown ────────────────────────────────────────────────────────────
function HoldCountdown({ offeredAt, holdMinutes }: { offeredAt: string; holdMinutes: number }) {
  const expiry = new Date(offeredAt).getTime() + holdMinutes * 60 * 1000;
  const [remaining, setRemaining] = useState(() => Math.max(0, expiry - Date.now()));
  useEffect(() => {
    if (remaining <= 0) return;
    const id = setInterval(() => setRemaining(Math.max(0, expiry - Date.now())), 1000);
    return () => clearInterval(id);
  }, [expiry, remaining]);
  const m = Math.floor(remaining / 60000);
  const s = Math.floor((remaining % 60000) / 1000);
  return (
    <span className={`text-xs font-mono font-medium ${remaining === 0 ? "text-red-600" : "text-yellow-700"}`}>
      {remaining === 0 ? "⌛ Expired" : `⏱ ${m}:${String(s).padStart(2, "0")} left`}
    </span>
  );
}

// ── Score estimator ───────────────────────────────────────────────────────────
function estimateScore(entry: WaitlistEntry, w1 = 1.0, w2 = 0.5, w3 = 0.3): number {
  const waitDays = (Date.now() - new Date(entry.requested_at).getTime()) / 86400000;
  const declineRisk = entry.decline_count / Math.max(1, entry.decline_count + 1);
  return w1 * entry.priority + w2 * waitDays - w3 * declineRisk;
}

// ── Score breakdown drawer ────────────────────────────────────────────────────
function ScoreBreakdown({ entry, providerName, visitTypeName }: { entry: WaitlistEntry; providerName: string; visitTypeName: string }) {
  const [open, setOpen] = useState(false);
  const w1 = 1.0, w2 = 0.5, w3 = 0.3;
  const waitDays = (Date.now() - new Date(entry.requested_at).getTime()) / 86400000;
  const declineRisk = entry.decline_count / Math.max(1, entry.decline_count + 1);
  const total = w1 * entry.priority + w2 * waitDays - w3 * declineRisk;

  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
      >
        {open ? "▲" : "▼"} Why this score?
      </button>
      {open && (
        <div className="mt-1.5 bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs space-y-1.5 min-w-[200px]">
          <div className="font-semibold text-gray-700 mb-1">Score: {total.toFixed(2)}</div>
          <div className="flex justify-between text-green-700">
            <span>Priority (×{w1})</span>
            <span>+{(w1 * entry.priority).toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-green-700">
            <span>Wait time (×{w2})</span>
            <span>+{(w2 * waitDays).toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-red-600">
            <span>Decline penalty (×{w3})</span>
            <span>−{(w3 * declineRisk).toFixed(2)}</span>
          </div>
          <div className="border-t pt-1.5 mt-1 space-y-0.5 text-gray-500">
            <div className="flex justify-between">
              <span>Provider match</span>
              <span className="text-green-600">✓ {providerName.replace("Dr. ", "Dr ")}</span>
            </div>
            <div className="flex justify-between">
              <span>Visit type match</span>
              <span className="text-green-600">✓ {visitTypeName}</span>
            </div>
            <div className="flex justify-between">
              <span>Time window</span>
              <span>{entry.earliest_window ? `${entry.earliest_window}–${entry.latest_window}` : "any"}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Simulate text modal ───────────────────────────────────────────────────────
function SimulateTextModal({
  entry,
  providerName,
  visitTypeName,
  onClose,
}: {
  entry: WaitlistEntry;
  providerName: string;
  visitTypeName: string;
  onClose: () => void;
}) {
  const slot = entry.offered_slot_start
    ? new Date(entry.offered_slot_start).toLocaleString([], {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "next available slot";

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-base font-semibold">📱 Simulated SMS</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        {/* Phone mockup */}
        <div className="bg-gray-100 rounded-xl p-4 text-sm space-y-2 mb-4">
          <div className="text-xs text-gray-400 text-center mb-2">SmallPractice · SMS</div>
          <div className="bg-white rounded-lg px-3 py-2 shadow-sm text-gray-800 leading-relaxed">
            Hi {entry.patient_uuid.slice(0, 6)}…, a slot has opened with {providerName} on {slot}{" "}
            for your <strong>{visitTypeName}</strong>.
            <br /><br />
            Reply <strong>YES</strong> to confirm or <strong>NO</strong> to decline.
            Offer expires in 30 min.
          </div>
          <div className="text-xs text-center text-gray-400 pt-1">
            Delivered · {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
        <p className="text-xs text-gray-400 text-center mb-4">
          No SMS was sent — this is a simulated log entry only.
        </p>
        <button
          onClick={onClose}
          className="w-full bg-gray-100 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-200"
        >
          Close
        </button>
      </div>
    </div>
  );
}

// ── Status style maps ─────────────────────────────────────────────────────────
const STATUS_STYLE: Record<string, string> = {
  waiting: "bg-blue-100 text-blue-800",
  offered: "bg-yellow-100 text-yellow-800",
  booked: "bg-green-100 text-green-800",
  declined: "bg-gray-100 text-gray-500",
  expired: "bg-red-100 text-red-800",
};
const STATUS_ICON: Record<string, string> = {
  waiting: "⏳", offered: "📨", booked: "✓", declined: "✕", expired: "⌛",
};

const DEFAULT_HOLD_MINUTES = 30;

// ── Main page ─────────────────────────────────────────────────────────────────
export function WaitlistPage() {
  const qc = useQueryClient();
  const { role, providerId: myProviderId } = useAuthStore();
  const isProvider = role === "provider";
  const [simulateEntry, setSimulateEntry] = useState<WaitlistEntry | null>(null);

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["waitlist", isProvider ? myProviderId : null],
    queryFn: () => fetchWaitlist(isProvider && myProviderId ? myProviderId : undefined),
    refetchInterval: 30_000,
  });
  const { data: providers = [] } = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const { data: visitTypes = [] } = useQuery({ queryKey: ["visitTypes"], queryFn: fetchVisitTypes });

  const providerMap = Object.fromEntries(providers.map((p) => [p.id, p.name]));
  const vtMap = Object.fromEntries(visitTypes.map((v) => [v.id, v.name]));

  const acceptMut = useMutation({
    mutationFn: (id: string) => acceptOffer(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["waitlist"] });
      qc.invalidateQueries({ queryKey: ["appointments"] });
    },
  });
  const declineMut = useMutation({
    mutationFn: (id: string) => declineOffer(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["waitlist"] }),
  });
  const offerMut = useMutation({
    mutationFn: (id: string) => offerSlot(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["waitlist"] }),
  });

  const offered = entries.filter((e) => e.status === "offered");
  const waiting = entries.filter((e) => e.status === "waiting");
  const other = entries.filter((e) => e.status !== "offered" && e.status !== "waiting");

  function renderRow(e: WaitlistEntry) {
    const isOffered = e.status === "offered";
    const isWaiting = e.status === "waiting";
    const score = (isOffered || isWaiting) ? estimateScore(e).toFixed(1) : null;
    const provName = providerMap[e.provider_id] ?? "—";
    const vtName = vtMap[e.visit_type_id] ?? "—";

    return (
      <tr key={e.id} className={`hover:bg-gray-50 ${isOffered ? "bg-yellow-50" : ""}`}>
        {/* Patient */}
        <td className="px-4 py-3">
          <PatientUUID uuid={e.patient_uuid} />
        </td>

        {/* Provider */}
        <td className="px-4 py-3 text-gray-800 text-sm">{provName}</td>

        {/* Visit type */}
        <td className="px-4 py-3 text-gray-800 text-sm">{vtName}</td>

        {/* Priority + score + breakdown */}
        <td className="px-4 py-3 text-center">
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-bold ${
              e.priority >= 4
                ? "bg-red-100 text-red-800"
                : e.priority >= 2
                  ? "bg-yellow-100 text-yellow-800"
                  : "bg-green-100 text-green-800"
            }`}
            title="Priority (0 = standard, 5 = urgent)"
          >
            P{e.priority}
          </span>
          {score !== null && (
            <div className="text-xs text-gray-400 mt-0.5" title="Estimated match score">
              ~{score}
            </div>
          )}
          {(isOffered || isWaiting) && (
            <div className="mt-1">
              <ScoreBreakdown entry={e} providerName={provName} visitTypeName={vtName} />
            </div>
          )}
        </td>

        {/* Wait time */}
        <td className="px-4 py-3 text-sm text-gray-500">
          {Math.ceil((Date.now() - new Date(e.requested_at).getTime()) / 86400000)}d
        </td>

        {/* Status badge */}
        <td className="px-4 py-3">
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLE[e.status] ?? ""}`}
          >
            <span aria-hidden="true">{STATUS_ICON[e.status]}</span>
            {e.status}
          </span>
        </td>

        {/* Action column */}
        <td className="px-4 py-3">
          <div className="flex flex-col gap-1.5">
            {isOffered && e.offered_at && (
              <>
                <HoldCountdown offeredAt={e.offered_at} holdMinutes={DEFAULT_HOLD_MINUTES} />
                {e.offered_slot_start && (
                  <span className="text-xs text-gray-500">
                    Slot:{" "}
                    {new Date(e.offered_slot_start).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                )}
                <div className="flex gap-1 flex-wrap">
                  <button
                    onClick={() => acceptMut.mutate(e.id)}
                    disabled={acceptMut.isPending}
                    className="px-2 py-1 bg-green-600 text-white rounded text-xs hover:bg-green-700 disabled:opacity-50"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => declineMut.mutate(e.id)}
                    disabled={declineMut.isPending}
                    className="px-2 py-1 bg-gray-200 text-gray-700 rounded text-xs hover:bg-gray-300 disabled:opacity-50"
                  >
                    Decline
                  </button>
                  <button
                    onClick={() => setSimulateEntry(e)}
                    className="px-2 py-1 bg-blue-50 text-blue-700 border border-blue-200 rounded text-xs hover:bg-blue-100"
                  >
                    📱 Preview SMS
                  </button>
                </div>
              </>
            )}

            {isWaiting && (
              <div className="flex gap-1 flex-wrap">
                <button
                  onClick={() => offerMut.mutate(e.id)}
                  disabled={offerMut.isPending}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700 disabled:opacity-50"
                  title="Find next available slot and send offer"
                >
                  {offerMut.isPending ? "Finding…" : "Offer Slot"}
                </button>
                <button
                  onClick={() => setSimulateEntry(e)}
                  className="px-2 py-1 bg-gray-100 text-gray-600 border border-gray-200 rounded text-xs hover:bg-gray-200"
                >
                  📱 Preview SMS
                </button>
              </div>
            )}

            {e.decline_count > 0 && (
              <span className="text-xs text-gray-400">{e.decline_count} decline{e.decline_count > 1 ? "s" : ""}</span>
            )}
          </div>
        </td>
      </tr>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Waitlist</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Score = w1×priority + w2×wait_days − w3×decline_risk (configurable in Settings)
          </p>
        </div>
        <div className="flex gap-2">
          {offered.length > 0 && (
            <span className="bg-yellow-100 text-yellow-800 text-sm font-medium px-3 py-1 rounded-full">
              {offered.length} offer{offered.length > 1 ? "s" : ""} pending
            </span>
          )}
          {waiting.length > 0 && (
            <span className="bg-blue-100 text-blue-800 text-sm font-medium px-3 py-1 rounded-full">
              {waiting.length} waiting
            </span>
          )}
        </div>
      </div>

      {isLoading ? (
        <p className="text-gray-400">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-gray-400">No waitlist entries.</p>
      ) : (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Patient</th>
                <th className="px-4 py-3 text-left">Provider</th>
                <th className="px-4 py-3 text-left">Visit Type</th>
                <th className="px-4 py-3 text-center">Priority / Score</th>
                <th className="px-4 py-3 text-left">Wait</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {/* Offered entries float to top */}
              {[...offered, ...waiting, ...other].map(renderRow)}
            </tbody>
          </table>
        </div>
      )}

      {simulateEntry && (
        <SimulateTextModal
          entry={simulateEntry}
          providerName={providerMap[simulateEntry.provider_id] ?? "Provider"}
          visitTypeName={vtMap[simulateEntry.visit_type_id] ?? "visit"}
          onClose={() => setSimulateEntry(null)}
        />
      )}
    </div>
  );
}
