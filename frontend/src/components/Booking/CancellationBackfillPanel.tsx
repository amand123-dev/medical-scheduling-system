import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWaitlist } from "../../api/waitlist";
import { offerSlot } from "../../api/waitlist";
import { fetchProviders, fetchVisitTypes } from "../../api/appointments";
import type { WaitlistEntry } from "../../types";
import { PatientUUID } from "../shared/PatientUUID";

function score(e: WaitlistEntry, w1 = 1.0, w2 = 0.5, w3 = 0.3): number {
  const waitDays = (Date.now() - new Date(e.requested_at).getTime()) / 86400000;
  const declineRisk = e.decline_count / Math.max(1, e.decline_count + 1);
  return w1 * e.priority + w2 * waitDays - w3 * declineRisk;
}

interface Props {
  providerId: string;
  visitTypeId: string;
  onClose: () => void;
}

export function CancellationBackfillPanel({ providerId, visitTypeId, onClose }: Props) {
  const qc = useQueryClient();

  const { data: allWaiting = [] } = useQuery<WaitlistEntry[]>({
    queryKey: ["waitlist"],
    queryFn: () => fetchWaitlist(),
  });
  const { data: providers = [] } = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const { data: visitTypes = [] } = useQuery({ queryKey: ["visitTypes"], queryFn: fetchVisitTypes });

  const provMap = Object.fromEntries(providers.map((p) => [p.id, p.name]));
  const vtMap = Object.fromEntries(visitTypes.map((v) => [v.id, v.name]));

  const relevant = allWaiting.filter(
    (e) => e.provider_id === providerId && e.visit_type_id === visitTypeId
  );

  // Auto-offered entry (backfill engine already sent the offer)
  const autoOffered = relevant.filter((e) => e.status === "offered");

  // Remaining waiting entries, ranked by score
  const matches = relevant
    .filter((e) => e.status === "waiting")
    .map((e) => ({ entry: e, score: score(e) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);

  const offerMut = useMutation({
    mutationFn: (id: string) => offerSlot(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["waitlist"] });
      qc.invalidateQueries({ queryKey: ["outreach-log"] });
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Slot freed — Backfill matches</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {vtMap[visitTypeId] ?? "Visit"} · {provMap[providerId] ?? "Provider"}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2.5 text-sm text-green-800 mb-4 flex items-center gap-2">
          <span aria-hidden="true">✓</span>
          Appointment cancelled. Backfill engine scored the waitlist and sent the top offer automatically.
        </div>

        {/* Auto-offered entry */}
        {autoOffered.length > 0 && (
          <div className="mb-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Auto-offered by engine</p>
            {autoOffered.map((e) => (
              <div key={e.id} className="flex items-center gap-3 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
                <span className="text-green-600 text-sm">📨</span>
                <div className="min-w-0 flex-1">
                  <PatientUUID uuid={e.patient_uuid} label="" />
                  <p className="text-xs text-green-700 mt-0.5">Offer sent · P{e.priority} · {Math.ceil((Date.now() - new Date(e.requested_at).getTime()) / 86400000)}d wait</p>
                </div>
                <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded font-medium">offered</span>
              </div>
            ))}
          </div>
        )}

        {matches.length === 0 && autoOffered.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">
            No waiting patients match this provider + visit type.
          </p>
        ) : matches.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Remaining waitlist — manual offer</p>
            <div className="space-y-2">
            {matches.map(({ entry, score: s }, i) => (
              <div
                key={entry.id}
                className={`flex items-center justify-between rounded-lg border px-4 py-3 ${i === 0 ? "border-blue-200 bg-blue-50" : "border-gray-100 bg-gray-50"}`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`text-xs font-bold w-5 text-center ${i === 0 ? "text-blue-700" : "text-gray-400"}`}>
                    #{i + 1}
                  </span>
                  <div className="min-w-0">
                    <PatientUUID uuid={entry.patient_uuid} label="" />
                    <div className="flex gap-2 text-xs text-gray-500 mt-0.5">
                      <span>P{entry.priority}</span>
                      <span>·</span>
                      <span>{Math.ceil((Date.now() - new Date(entry.requested_at).getTime()) / 86400000)}d wait</span>
                      <span>·</span>
                      <span>Score {s.toFixed(1)}</span>
                      {entry.decline_count > 0 && (
                        <><span>·</span><span className="text-orange-500">{entry.decline_count} decline{entry.decline_count > 1 ? "s" : ""}</span></>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => offerMut.mutate(entry.id)}
                  disabled={offerMut.isPending}
                  className={`ml-3 shrink-0 px-3 py-1.5 rounded text-xs font-medium ${i === 0 ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-gray-200 text-gray-700 hover:bg-gray-300"} disabled:opacity-50`}
                >
                  {offerMut.isPending ? "Offering…" : "Offer Slot"}
                </button>
              </div>
            ))}
          </div>
          </div>
        )}

        <div className="flex justify-between items-center mt-5 pt-4 border-t">
          <p className="text-xs text-gray-400">
            Score = w1×priority + w2×wait_days − w3×decline_risk
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
