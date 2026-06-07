import { useState } from "react";
import { fetchPatientIdentity } from "../../api/identity";
import type { PatientIdentityResponse } from "../../types";

interface Props {
  uuid: string;
  onClose: () => void;
}

export function IdentityLookupModal({ uuid, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [identity, setIdentity] = useState<PatientIdentityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchPatientIdentity(uuid);
      setIdentity(result);
    } catch {
      setError("Lookup failed. Admin or provider role required.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <span aria-hidden="true">🔒</span> Resolve Patient Identity
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>

        {!identity ? (
          <>
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800 mb-4">
              <p className="font-medium mb-1">This lookup will be permanently recorded in the audit log.</p>
              <p className="text-xs font-mono mt-1 break-all">{uuid}</p>
            </div>
            <p className="text-sm text-gray-500 mb-5">
              Only perform this lookup when clinically or administratively necessary.
            </p>
            {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={loading}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? "Looking up…" : "Confirm Lookup"}
              </button>
            </div>
          </>
        ) : (
          <>
            <dl className="space-y-2 text-sm mb-5">
              <div className="flex justify-between">
                <dt className="text-gray-500">Name</dt>
                <dd className="font-semibold">{identity.first_name} {identity.last_name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Date of birth</dt>
                <dd>{identity.dob}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Phone</dt>
                <dd>{identity.phone}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Email</dt>
                <dd className="truncate max-w-[180px] text-right">{identity.email}</dd>
              </div>
            </dl>
            <p className="text-xs text-center text-amber-700 bg-amber-50 rounded px-3 py-2 mb-4">
              Access recorded in the audit log.
            </p>
            <button
              onClick={onClose}
              className="w-full px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200"
            >
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
}
