import { useState } from "react";
import { useAuthStore } from "../../store/auth";
import { IdentityLookupModal } from "./IdentityLookupModal";

interface Props {
  uuid: string;
  label?: string;
}

export function PatientUUID({ uuid, label = "Patient" }: Props) {
  const [showFull, setShowFull] = useState(false);
  const [showLookup, setShowLookup] = useState(false);
  const role = useAuthStore((s) => s.role);
  const canLookup = role === "admin" || role === "provider";
  const short = uuid.slice(0, 8);

  return (
    <>
      <span className="inline-flex items-center gap-1 group relative">
        <span
          className="text-xs font-mono text-gray-600 cursor-pointer hover:text-gray-900"
          onClick={() => setShowFull((v) => !v)}
          title={showFull ? "Click to hide" : "Click to reveal full UUID"}
        >
          {label ? `${label} ` : ""}{showFull ? uuid : `${short}…`}
        </span>
        <span
          className="text-gray-400 text-xs"
          title="Identity restricted — UUID only. Name resolution is role-gated and audit-logged."
          aria-label="Identity restricted"
        >
          🔒
        </span>
        {canLookup && (
          <button
            onClick={() => setShowLookup(true)}
            className="text-xs text-blue-500 hover:text-blue-700 opacity-0 group-hover:opacity-100 transition-opacity ml-0.5"
            title="Resolve patient name (will be audit-logged)"
          >
            Resolve
          </button>
        )}
      </span>

      {showLookup && (
        <IdentityLookupModal uuid={uuid} onClose={() => setShowLookup(false)} />
      )}
    </>
  );
}
