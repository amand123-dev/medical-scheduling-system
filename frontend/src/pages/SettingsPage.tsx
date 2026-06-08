import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../api/client";
import { fetchBlocks, createBlock, createBlocksBulk, deleteBlock, fetchProviders, updateProvider } from "../api/appointments";
import type { PracticeSettings, Provider } from "../types";

const fetchSettings = () => client.get<PracticeSettings>("/settings").then((r) => r.data);
const patchSettings = (body: Partial<PracticeSettings>) =>
  client.patch<PracticeSettings>("/settings", body).then((r) => r.data);

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function parseDays(work_days: string | null): boolean[] {
  if (!work_days) return [true, true, true, true, true, false, false];
  const set = new Set(work_days.split(",").map(Number));
  return DAYS.map((_, i) => set.has(i));
}

function serializeDays(checked: boolean[]): string | null {
  const days = checked.map((v, i) => v ? String(i) : null).filter(Boolean).join(",");
  return days || null;
}

type Tab = "scheduler" | "blocked" | "providers";

export function SettingsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("scheduler");

  // --- Scheduler settings ---
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const mutation = useMutation({
    mutationFn: patchSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const [form, setForm] = useState<Partial<PracticeSettings>>({});
  useEffect(() => { if (data) setForm(data); }, [data]);

  function handleChange(key: keyof PracticeSettings, value: string) {
    const num = key === "work_start_hour" || key === "work_end_hour" || key === "hold_window_minutes"
      ? parseInt(value) || 0
      : parseFloat(value) || 0;
    setForm((f) => ({ ...f, [key]: num }));
  }

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    mutation.mutate(form);
  }

  // --- Blocked days ---
  const { data: providers = [] } = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const { data: blocks = [], isLoading: blocksLoading } = useQuery({
    queryKey: ["schedule-blocks"],
    queryFn: () => fetchBlocks(),
  });
  const createBlockMut = useMutation({
    mutationFn: createBlock,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["schedule-blocks"] }); setBlockForm(emptyBlock()); setBlockError(""); },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setBlockError(msg ?? "Failed to add block — please try again.");
    },
  });
  const deleteBlockMut = useMutation({
    mutationFn: deleteBlock,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedule-blocks"] }),
  });

  const bulkMut = useMutation({
    mutationFn: createBlocksBulk,
    onSuccess: (data) => { qc.invalidateQueries({ queryKey: ["schedule-blocks"] }); setBulkMsg(`Added ${data.added} block(s).`); },
    onError: () => setBulkMsg("Failed — please try again."),
  });
  const [bulkMsg, setBulkMsg] = useState("");

  const emptyBlock = () => ({ provider_id: "", start_date: "", end_date: "", reason: "" });
  const [blockForm, setBlockForm] = useState(emptyBlock());
  const [blockError, setBlockError] = useState("");

  function handleBlockSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBlockError("");
    if (!blockForm.start_date || !blockForm.end_date) { setBlockError("Start and end date are required."); return; }
    if (blockForm.start_date > blockForm.end_date) { setBlockError("End date must be on or after start date."); return; }
    createBlockMut.mutate({
      provider_id: blockForm.provider_id || null,
      start_date: blockForm.start_date,
      end_date: blockForm.end_date,
      reason: blockForm.reason || null,
    });
  }

  function fmtDate(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function generateWeekends(startYear: number, endYear: number) {
    const items: Array<{ provider_id: null; start_date: string; end_date: string; reason: string }> = [];
    const d = new Date(startYear, 0, 1);
    const end = new Date(endYear, 11, 31);
    while (d.getDay() !== 6) d.setDate(d.getDate() + 1);
    while (d <= end) {
      const sat = fmtDate(d);
      const sun = new Date(d); sun.setDate(sun.getDate() + 1);
      items.push({ provider_id: null, start_date: sat, end_date: sun <= end ? fmtDate(sun) : sat, reason: "Weekend" });
      d.setDate(d.getDate() + 7);
    }
    return items;
  }

  function generateFederalHolidays(year: number) {
    function nthWeekday(y: number, month: number, weekday: number, n: number): Date {
      const d = new Date(y, month, 1); let count = 0;
      while (true) { if (d.getDay() === weekday && ++count === n) return new Date(d); d.setDate(d.getDate() + 1); }
    }
    function lastMonday(y: number, month: number): Date {
      const d = new Date(y, month + 1, 0);
      while (d.getDay() !== 1) d.setDate(d.getDate() - 1);
      return d;
    }
    function obs(d: Date): Date {
      if (d.getDay() === 6) return new Date(d.getFullYear(), d.getMonth(), d.getDate() - 1);
      if (d.getDay() === 0) return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
      return d;
    }
    const holidays = [
      { d: obs(new Date(year, 0, 1)),    name: "New Year's Day" },
      { d: nthWeekday(year, 0, 1, 3),    name: "Martin Luther King Jr. Day" },
      { d: nthWeekday(year, 1, 1, 3),    name: "Presidents' Day" },
      { d: lastMonday(year, 4),          name: "Memorial Day" },
      { d: obs(new Date(year, 5, 19)),   name: "Juneteenth" },
      { d: obs(new Date(year, 6, 4)),    name: "Independence Day" },
      { d: nthWeekday(year, 8, 1, 1),   name: "Labor Day" },
      { d: nthWeekday(year, 9, 1, 2),   name: "Columbus Day" },
      { d: obs(new Date(year, 10, 11)),  name: "Veterans Day" },
      { d: nthWeekday(year, 10, 4, 4),  name: "Thanksgiving Day" },
      { d: obs(new Date(year, 11, 25)),  name: "Christmas Day" },
    ];
    return holidays.map(({ d, name }) => ({ provider_id: null as null, start_date: fmtDate(d), end_date: fmtDate(d), reason: name }));
  }

  function handleBulkWeekends() {
    setBulkMsg("");
    const year = new Date().getFullYear();
    bulkMut.mutate(generateWeekends(year, year + 1));
  }

  function handleBulkHolidays() {
    setBulkMsg("");
    const year = new Date().getFullYear();
    bulkMut.mutate([...generateFederalHolidays(year), ...generateFederalHolidays(year + 1)]);
  }

  const schedulerFields: Array<{ key: keyof PracticeSettings; label: string; desc: string; step: string }> = [
    { key: "matcher_w1", label: "Waitlist weight: priority (w1)", desc: "Weight for patient priority in backfill scoring", step: "0.1" },
    { key: "matcher_w2", label: "Waitlist weight: wait time (w2)", desc: "Weight for how long the patient has been waiting", step: "0.1" },
    { key: "matcher_w3", label: "Waitlist weight: decline risk (w3)", desc: "Penalty for patients who have declined previous offers", step: "0.1" },
    { key: "hold_window_minutes", label: "Offer hold window (minutes)", desc: "How long a waitlist offer is held before cascading", step: "5" },
    { key: "risk_low_threshold", label: "No-show risk: low threshold", desc: "Scores below this are low risk", step: "0.05" },
    { key: "risk_high_threshold", label: "No-show risk: high threshold", desc: "Scores at or above this are high risk", step: "0.05" },
    { key: "work_start_hour", label: "Working hours: start (hour)", desc: "Earliest bookable hour (24h). Used by find-next-available.", step: "1" },
    { key: "work_end_hour", label: "Working hours: end (hour)", desc: "Latest bookable hour (24h). Slots that end after this are skipped.", step: "1" },
    { key: "buffer_minutes", label: "Buffer between appointments (minutes)", desc: "Dead time after each appointment — prevents back-to-back scheduling.", step: "5" },
  ];

  if (isLoading) return <div className="p-6 text-gray-400">Loading…</div>;

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-semibold text-gray-900 mb-2">Practice Settings</h1>
      <p className="text-sm text-gray-500 mb-5">Configure scheduling engine parameters. Changes take effect immediately.</p>

      {/* Tab bar */}
      <div className="flex border-b mb-6 text-sm">
        <button
          onClick={() => setTab("scheduler")}
          className={`px-4 py-2 font-medium ${tab === "scheduler" ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
        >
          Scheduler
        </button>
        <button
          onClick={() => setTab("blocked")}
          className={`px-4 py-2 font-medium ${tab === "blocked" ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
        >
          Blocked Days
        </button>
        <button
          onClick={() => setTab("providers")}
          className={`px-4 py-2 font-medium ${tab === "providers" ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500 hover:text-gray-700"}`}
        >
          Providers
        </button>
      </div>

      {tab === "scheduler" && (
        <form onSubmit={handleSave} className="space-y-4">
          {schedulerFields.map(({ key, label, desc, step }) => (
            <div key={key} className="bg-white rounded-xl shadow p-4">
              <label className="block text-sm font-medium text-gray-800 mb-0.5">{label}</label>
              <p className="text-xs text-gray-400 mb-2">{desc}</p>
              <input
                type="number"
                step={step}
                value={form[key] ?? ""}
                onChange={(e) => handleChange(key, e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          ))}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={mutation.isPending}
              className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending ? "Saving…" : "Save settings"}
            </button>
            {mutation.isSuccess && <span className="text-green-600 text-sm">Saved</span>}
            {mutation.isError && <span className="text-red-600 text-sm">Save failed — please try again.</span>}
          </div>
        </form>
      )}

      {tab === "blocked" && (
        <div className="space-y-6">
          {/* Add block form */}
          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="text-base font-semibold text-gray-800 mb-3">Add block</h2>
            <form onSubmit={handleBlockSubmit} className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Provider (leave blank for clinic-wide)</label>
                <select
                  value={blockForm.provider_id}
                  onChange={(e) => setBlockForm((f) => ({ ...f, provider_id: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Clinic-wide (all providers)</option>
                  {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Start date</label>
                  <input
                    type="date"
                    value={blockForm.start_date}
                    onChange={(e) => setBlockForm((f) => ({ ...f, start_date: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                    required
                  />
                </div>
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">End date</label>
                  <input
                    type="date"
                    value={blockForm.end_date}
                    onChange={(e) => setBlockForm((f) => ({ ...f, end_date: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                    required
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reason (optional)</label>
                <input
                  type="text"
                  value={blockForm.reason}
                  onChange={(e) => setBlockForm((f) => ({ ...f, reason: e.target.value }))}
                  placeholder="e.g. Holiday, Conference, Vacation"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>
              {blockError && <p className="text-red-600 text-sm">{blockError}</p>}
              <button
                type="submit"
                disabled={createBlockMut.isPending}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {createBlockMut.isPending ? "Adding…" : "Add block"}
              </button>
            </form>
          </div>

          {/* Quick add */}
          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="text-base font-semibold text-gray-800 mb-1">Quick add</h2>
            <p className="text-xs text-gray-400 mb-3">Bulk-add clinic-wide blocks for the current and next calendar year. Skips dates already blocked.</p>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={handleBulkWeekends}
                disabled={bulkMut.isPending}
                className="bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
              >
                {bulkMut.isPending ? "Adding…" : "Block all weekends"}
              </button>
              <button
                onClick={handleBulkHolidays}
                disabled={bulkMut.isPending}
                className="bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
              >
                {bulkMut.isPending ? "Adding…" : "Block federal holidays (US)"}
              </button>
            </div>
            {bulkMsg && (
              <p className={`mt-2 text-sm ${bulkMsg.startsWith("Failed") ? "text-red-600" : "text-green-600"}`}>
                {bulkMsg}
              </p>
            )}
          </div>

          {/* Existing blocks list */}
          <div>
            <h2 className="text-base font-semibold text-gray-800 mb-3">Current blocks</h2>
            {blocksLoading ? (
              <p className="text-sm text-gray-400">Loading…</p>
            ) : blocks.length === 0 ? (
              <p className="text-sm text-gray-400">No blocked days configured.</p>
            ) : (
              <div className="space-y-2">
                {blocks.map((b) => {
                  const providerName = b.provider_id
                    ? providers.find((p) => p.id === b.provider_id)?.name ?? "Unknown provider"
                    : "Clinic-wide";
                  return (
                    <div key={b.id} className="bg-white rounded-xl shadow px-4 py-3 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-gray-800">
                          {b.start_date === b.end_date ? b.start_date : `${b.start_date} → ${b.end_date}`}
                        </p>
                        <p className="text-xs text-gray-500">
                          {providerName}{b.reason ? ` · ${b.reason}` : ""}
                        </p>
                      </div>
                      <button
                        onClick={() => deleteBlockMut.mutate(b.id)}
                        disabled={deleteBlockMut.isPending}
                        className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50 shrink-0"
                        aria-label="Remove block"
                      >
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "providers" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Override work days and hours per provider. Leave blank to use practice-wide defaults.
          </p>
          {providers.map((p) => (
            <ProviderAvailabilityCard key={p.id} provider={p} practiceSettings={data!} onSaved={() => qc.invalidateQueries({ queryKey: ["providers"] })} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProviderAvailabilityCard({
  provider,
  practiceSettings,
  onSaved,
}: {
  provider: Provider;
  practiceSettings: PracticeSettings;
  onSaved: () => void;
}) {
  const [days, setDays] = useState<boolean[]>(() => parseDays(provider.work_days));
  const [startHour, setStartHour] = useState<string>(
    provider.work_start_hour != null ? String(provider.work_start_hour) : ""
  );
  const [endHour, setEndHour] = useState<string>(
    provider.work_end_hour != null ? String(provider.work_end_hour) : ""
  );
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: () =>
      updateProvider(provider.id, {
        work_days: serializeDays(days),
        work_start_hour: startHour !== "" ? parseInt(startHour) : null,
        work_end_hour: endHour !== "" ? parseInt(endHour) : null,
      }),
    onSuccess: () => { setSaved(true); setErr(""); onSaved(); setTimeout(() => setSaved(false), 2000); },
    onError: () => setErr("Save failed — please try again."),
  });

  function handleReset() {
    setDays(parseDays(null));
    setStartHour("");
    setEndHour("");
  }

  return (
    <div className="bg-white rounded-xl shadow p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-semibold text-gray-800">{provider.name}</p>
          {provider.specialty && <p className="text-xs text-gray-400">{provider.specialty}</p>}
        </div>
        <button onClick={handleReset} className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2">
          Reset to defaults
        </button>
      </div>

      {/* Day checkboxes */}
      <div className="mb-3">
        <p className="text-xs font-medium text-gray-600 mb-1.5">Work days</p>
        <div className="flex gap-1.5 flex-wrap">
          {DAYS.map((label, i) => (
            <label key={i} className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={days[i]}
                onChange={(e) => setDays((d) => d.map((v, idx) => idx === i ? e.target.checked : v))}
                className="rounded border-gray-300 text-blue-600"
              />
              <span className="text-xs text-gray-700">{label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Work hours */}
      <div className="flex gap-3 mb-4">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Start hour <span className="text-gray-400">(default: {practiceSettings.work_start_hour})</span>
          </label>
          <input
            type="number"
            min={0} max={23}
            placeholder={String(practiceSettings.work_start_hour)}
            value={startHour}
            onChange={(e) => setStartHour(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            End hour <span className="text-gray-400">(default: {practiceSettings.work_end_hour})</span>
          </label>
          <input
            type="number"
            min={1} max={24}
            placeholder={String(practiceSettings.work_end_hour)}
            value={endHour}
            onChange={(e) => setEndHour(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => mut.mutate()}
          disabled={mut.isPending}
          className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {mut.isPending ? "Saving…" : "Save"}
        </button>
        {saved && <span className="text-green-600 text-sm">Saved</span>}
        {err && <span className="text-red-600 text-sm">{err}</span>}
      </div>
    </div>
  );
}
