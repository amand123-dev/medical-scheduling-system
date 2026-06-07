import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAuditLog } from "../api/identity";
import { PatientUUID } from "../components/shared/PatientUUID";

const ACTION_STYLE: Record<string, string> = {
  lookup: "bg-blue-50 text-blue-700",
  booking_context: "bg-purple-50 text-purple-700",
  care_coordination: "bg-green-50 text-green-700",
};

function actionLabel(action: string) {
  return action.replace(/_/g, " ");
}

export function AuditLogPage() {
  const [limit] = useState(100);

  const { data: entries = [], isLoading, isError } = useQuery({
    queryKey: ["audit-log", limit],
    queryFn: () => fetchAuditLog(limit),
    staleTime: 30_000,
  });

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-gray-900">Identity Access Log</h1>
        <p className="text-sm text-gray-500 mt-1">
          Every patient name lookup is role-gated and recorded here. Operational tables
          store UUIDs only — name resolution is a separate, audited step.
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-5 text-sm text-amber-800">
        <span aria-hidden="true" className="mt-0.5">🔒</span>
        <span>
          This log is visible to <strong>admin</strong> users only. Each row represents a
          UUID → identity resolution — a deliberate, permissioned act, not routine data access.
        </span>
      </div>

      {isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
      {isError && (
        <p className="text-red-600 text-sm">
          Failed to load audit log. Admin role required.
        </p>
      )}

      {!isLoading && !isError && entries.length === 0 && (
        <div className="bg-white rounded-xl shadow px-6 py-10 text-center text-gray-400 text-sm">
          No identity lookups recorded yet. They appear here when an admin or provider
          accesses a patient record via <code className="font-mono text-xs">GET /identity/patients/&lt;uuid&gt;</code>.
        </div>
      )}

      {entries.length > 0 && (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Timestamp</th>
                <th className="px-4 py-3 text-left">Staff user</th>
                <th className="px-4 py-3 text-left">Action</th>
                <th className="px-4 py-3 text-left">Patient UUID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {entries.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {new Date(e.at).toLocaleString([], {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </td>
                  <td className="px-4 py-3">
                    {e.accessed_by_username ? (
                      <span className="font-medium text-gray-800">{e.accessed_by_username}</span>
                    ) : (
                      <span className="font-mono text-xs text-gray-400">{e.accessed_by.slice(0, 8)}…</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${ACTION_STYLE[e.action] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {actionLabel(e.action)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <PatientUUID uuid={e.patient_uuid} label="" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-3 border-t text-xs text-gray-400">
            Showing {entries.length} most recent {entries.length === 1 ? "entry" : "entries"}
          </div>
        </div>
      )}
    </div>
  );
}
