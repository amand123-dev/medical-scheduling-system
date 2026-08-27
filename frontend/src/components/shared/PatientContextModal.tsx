import { useState } from "react";
import { fetchPatientContext } from "../../api/rag";
import type { Passage } from "../../types";

interface Props {
  uuid: string;
  onClose: () => void;
}

// Deliberately phrased as questions about care history, not about the patient
// as a person. Retrieval here supports coordination, not scrutiny.
const SUGGESTIONS = [
  "What happened at the last visit?",
  "Any preparation instructions for the next appointment?",
  "Why were previous appointments missed?",
  "Is a follow-up due?",
];

function PassageCard({ passage }: { passage: Passage }) {
  const pct = Math.round(Math.min(Math.max(passage.score, 0), 1) * 100);
  return (
    <article className="border border-gray-200 rounded-lg px-4 py-3">
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div className="min-w-0">
          <span className="text-sm font-semibold text-gray-900">
            {passage.title.replace(/_/g, " ")}
          </span>
          <p className="text-xs text-gray-400 font-mono truncate">
            {passage.source} · section {passage.chunk_index + 1}
          </p>
        </div>
        <span className="text-xs font-medium text-gray-500 tabular-nums shrink-0">
          {pct}% match
        </span>
      </div>
      <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{passage.content}</p>
    </article>
  );
}

export function PatientContextModal({ uuid, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [passages, setPassages] = useState<Passage[] | null>(null);
  const [searched, setSearched] = useState("");

  async function run(q: string) {
    const trimmed = q.trim();
    if (trimmed.length < 2) return;
    setQuery(trimmed);
    setLoading(true);
    setError(null);
    try {
      const result = await fetchPatientContext(uuid, trimmed);
      setPassages(result.passages);
      setSearched(trimmed);
    } catch {
      setError("Retrieval failed. Admin or provider role required.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <span aria-hidden="true">🔒</span> Patient Care Context
          </h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800 mb-4">
          <p className="font-medium">Every search here is permanently recorded in the audit log.</p>
          <p className="text-xs mt-1">
            Documents are de-identified and scoped to this patient only. Passages are returned as
            written — nothing is summarised or sent to an external model.
          </p>
          <p className="text-xs font-mono mt-1.5 break-all">{uuid}</p>
        </div>

        <form
          className="flex gap-2 mb-3"
          onSubmit={(e) => {
            e.preventDefault();
            void run(query);
          }}
        >
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about this patient's care history…"
            aria-label="Search this patient's documents"
            className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
          />
          <button
            type="submit"
            disabled={loading || query.trim().length < 2}
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:bg-gray-200 disabled:text-gray-400"
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </form>

        <div className="flex gap-2 mb-4 flex-wrap">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => void run(s)}
              className="text-xs px-3 py-1.5 rounded-full bg-gray-100 text-gray-600 hover:bg-blue-50 hover:text-blue-700 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto flex-1 -mx-1 px-1">
          {error && <p className="text-red-600 text-sm">{error}</p>}

          {!error && passages === null && !loading && (
            <p className="text-gray-400 text-sm text-center py-8">
              Ask a question to retrieve passages from this patient's documents.
            </p>
          )}

          {!error && passages !== null && passages.length === 0 && (
            <p className="text-gray-400 text-sm text-center py-8">
              No documents on file for this patient matched “{searched}”.
            </p>
          )}

          {!error && passages !== null && passages.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                {passages.length} passage{passages.length !== 1 ? "s" : ""} for “{searched}”, best
                match first
              </p>
              {passages.map((p) => (
                <PassageCard key={`${p.source}-${p.chunk_index}`} passage={p} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
