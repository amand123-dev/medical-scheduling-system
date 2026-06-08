import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { useAuthStore } from "../store/auth";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const loginStore = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const tokens = await login(username, password);
      loginStore(tokens.access_token, username);
      navigate("/");
    } catch {
      setError("Invalid credentials. Check username and password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-xl shadow p-8 w-full max-w-sm">
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">SmallPractice Scheduler</h1>
        <p className="text-sm text-gray-500 mb-6">Sign in to your account</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-5 border-t pt-4">
          <p className="text-xs text-gray-400 text-center mb-2">Demo accounts — click to fill</p>
          <div className="flex gap-2">
            {[
              { label: "Admin", username: "admin", password: "admin123", color: "bg-purple-50 text-purple-700 hover:bg-purple-100" },
              { label: "Provider", username: "dr_chen", password: "provider123", color: "bg-blue-50 text-blue-700 hover:bg-blue-100" },
              { label: "Front desk", username: "front_desk", password: "desk123", color: "bg-gray-100 text-gray-600 hover:bg-gray-200" },
            ].map(({ label, username: u, password: p, color }) => (
              <button
                key={label}
                type="button"
                onClick={() => { setUsername(u); setPassword(p); }}
                className={`flex-1 text-xs font-medium px-2 py-1.5 rounded-lg ${color}`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-gray-400 text-center mt-2">Portfolio demo — synthetic data only.</p>
        </div>
        <div className="mt-4 text-center">
          <a href="/portal/login" className="text-sm text-blue-600 hover:underline">
            Patient portal →
          </a>
        </div>
      </div>
    </div>
  );
}
