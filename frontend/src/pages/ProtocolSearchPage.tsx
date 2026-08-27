import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { askProtocols } from "../api/rag";

// Starting points for someone seeing the page for the first time. These map onto
// the protocol docs in backend/data/protocols/.
const EXAMPLE_QUERIES = [
  "How long is a new patient visit?",
  "What do we do when a patient no-shows twice?",
  "How long does a waitlist offer stay open?",
  "What should a patient do before a fasting lab draw?",
  "When is a post-op follow-up due?",
];

const RESULT_COUNTS = [3, 5, 10];

// Renders inline [1] citations as badges so they read as references rather than
// stray brackets. The number maps to the passage card of the same number below.
function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
      {parts.map((part, i) =>
        /^\[\d+\]$/.test(part) ? (
          <span
            key={i}
            className="inline-block mx-0.5 px-1.5 rounded bg-blue-100 text-blue-700 text-xs font-medium tabular-nums align-baseline"
            title={`From passage ${part.slice(1, -1)} below`}
          >
            {part.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const pct = Math.round(Math.min(Math.max(score, 0), 1) * 100);
  return (
    <span className="inline-flex items-center gap-2 shrink-0" title="Cosine similarity to your query">
      <span className="w-16 h-1.5 rounded-full bg-gray-200 overflow-hidden" aria-hidden="true">
        <span className="block h-full bg-blue-500" style={{ width: `${pct}%` }} />
      </span>
      <span className="text-xs font-medium text-gray-500 tabular-nums">{pct}% match</span>
    </span>
  );
}

export function ProtocolSearchPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [k, setK] = useState(5);

  const trimmed = query.trim();
  const {
    data,
    isFetching,
    error,
  } = useQuery({
    queryKey: ["protocol-ask", trimmed, k],
    queryFn: () => askProtocols(trimmed, k),
    enabled: trimmed.length >= 2,
    staleTime: 5 * 60_000,
  });

  function run(q: string) {
    setInput(q);
    setQuery(q);
  }

  const passages = data?.passages ?? [];

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-gray-900">Protocol Search</h1>
        <p className="text-sm text-gray-500 mt-1">
          Ask a question about how this practice schedules, prepares, and follows up. Answers are
          answered from the practice's own protocol documents, with every claim cited back to the
          passage it came from. The model is given only those passages — it is never asked what it
          knows. Protocol documents contain no patient information.
        </p>
      </div>

      <form
        className="flex gap-2 mb-4"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(input);
        }}
      >
        <input
          type="search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. how long is a new patient visit?"
          aria-label="Search protocols"
          className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
        />
        <select
          value={k}
          onChange={(e) => setK(Number(e.target.value))}
          aria-label="Number of results"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
        >
          {RESULT_COUNTS.map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={input.trim().length < 2}
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:bg-gray-200 disabled:text-gray-400 transition-colors"
        >
          Search
        </button>
      </form>

      <div className="flex gap-2 mb-6 flex-wrap">
        {EXAMPLE_QUERIES.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => run(q)}
            className="text-xs px-3 py-1.5 rounded-full bg-gray-100 text-gray-600 hover:bg-blue-50 hover:text-blue-700 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      {trimmed.length < 2 && (
        <div className="bg-white rounded-xl shadow px-6 py-10 text-center text-gray-400 text-sm">
          Type a question above, or pick one of the examples, to search the protocol library.
        </div>
      )}

      {isFetching && <p className="text-gray-400 text-sm">Searching…</p>}

      {error && (
        <div className="bg-red-50 text-red-700 rounded-xl px-4 py-3 text-sm">
          Search failed. {error instanceof Error ? error.message : "Please try again."}
        </div>
      )}

      {!isFetching && !error && trimmed.length >= 2 && passages.length === 0 && (
        <div className="bg-white rounded-xl shadow px-6 py-10 text-center text-gray-400 text-sm">
          Nothing in the protocol library matched “{trimmed}”.
        </div>
      )}

      {!isFetching && !error && data?.answer && (
        <section className="bg-white rounded-xl shadow border-l-4 border-blue-500 px-5 py-4 mb-5">
          <div className="flex items-center gap-2 mb-2">
            <span aria-hidden="true">💬</span>
            <h2 className="text-sm font-semibold text-gray-900">Answer</h2>
            {data.model && (
              <span className="text-xs text-gray-400 font-mono ml-auto">{data.model}</span>
            )}
          </div>
          <AnswerText text={data.answer} />
          <p className="text-xs text-gray-400 mt-3">
            Generated from the {passages.length} passage{passages.length !== 1 ? "s" : ""} below.
            Numbers refer to those passages — check them before acting on this.
          </p>
        </section>
      )}

      {!isFetching && !error && data && !data.generated && passages.length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-600 mb-5">
          <span aria-hidden="true">ℹ️</span> Answer generation is not configured on this server, so
          the matching passages are shown on their own.
        </div>
      )}

      {!isFetching && passages.length > 0 && (
        <>
          <p className="text-xs text-gray-400 mb-2">
            {passages.length} passage{passages.length !== 1 ? "s" : ""} for “{data?.query}”, best match first
          </p>
          <div className="space-y-3">
            {passages.map((p, i) => (
              <article
                key={`${p.source}-${p.chunk_index}`}
                className="bg-white rounded-xl shadow px-5 py-4"
              >
                <div className="flex items-start justify-between gap-4 mb-2">
                  <div className="min-w-0">
                    <span className="text-xs font-medium text-gray-400 mr-2">#{i + 1}</span>
                    <span className="text-sm font-semibold text-gray-900">{p.title}</span>
                    <p className="text-xs text-gray-400 mt-0.5 font-mono truncate">
                      {p.source} · section {p.chunk_index + 1}
                    </p>
                  </div>
                  <ScoreBadge score={p.score} />
                </div>
                <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
                  {p.content}
                </p>
              </article>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
