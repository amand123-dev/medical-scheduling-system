import type { AppointmentStatus, RiskBucket } from "../../types";
import { StatusBadge } from "./StatusBadge";
import { RiskBadge } from "./RiskBadge";

const STATUSES: AppointmentStatus[] = ["scheduled", "completed", "cancelled", "no_show"];
const BUCKETS: RiskBucket[] = ["low", "medium", "high", "insufficient_data"];

export function Legend() {
  return (
    <div className="mt-8 bg-white rounded-xl shadow-sm p-5 border border-gray-100">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Legend</h2>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Appointment status</p>
          <div className="space-y-1.5">
            {STATUSES.map((s) => <StatusBadge key={s} status={s} />)}
          </div>
        </div>
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">No-show risk</p>
          <div className="space-y-1.5">
            {BUCKETS.map((b) => <RiskBadge key={b} bucket={b} />)}
          </div>
        </div>
      </div>
      <p className="text-xs text-gray-400 mt-3">
        Calendar dots (🟢🟡🔴) show risk level inline. Purple{" "}
        <span className="text-purple-600 font-medium">ML demo</span> badge uses the
        Kaggle-trained model with synthetic demographic features.
      </p>
    </div>
  );
}
