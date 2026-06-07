import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuthStore } from "./store/auth";
import { LoginPage } from "./pages/LoginPage";
import { CalendarPage } from "./pages/CalendarPage";
import { WaitlistPage } from "./pages/WaitlistPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { OutreachLogPage } from "./pages/OutreachLogPage";
import type { StaffRole } from "./types";

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const active = pathname === to;
  return (
    <Link
      to={to}
      className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${active ? "bg-blue-100 text-blue-700" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"}`}
    >
      {children}
    </Link>
  );
}

// Redirect away if user's role isn't in the allowed list
function RequireRole({ allowed, children }: { allowed: StaffRole[]; children: React.ReactNode }) {
  const role = useAuthStore((s) => s.role);
  if (role && !allowed.includes(role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function Layout() {
  const { isAuthenticated, username, role, logout } = useAuthStore();
  if (!isAuthenticated) return <Navigate to="/login" replace />;

  const isAdmin = role === "admin";
  const isRoleBadge: Record<string, string> = {
    admin: "bg-purple-100 text-purple-700",
    provider: "bg-blue-100 text-blue-700",
    front_desk: "bg-gray-100 text-gray-600",
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
        <span className="font-semibold text-gray-900 text-sm mr-2">SmallPractice</span>
        <NavLink to="/">Calendar</NavLink>
        <NavLink to="/waitlist">Waitlist</NavLink>
        <NavLink to="/outreach">Outreach Log</NavLink>
        <NavLink to="/dashboard">Dashboard</NavLink>
        {isAdmin && <NavLink to="/settings">Settings</NavLink>}
        {isAdmin && <NavLink to="/audit-log">Audit Log</NavLink>}
        <div className="ml-auto flex items-center gap-3 text-sm text-gray-500">
          <span>{username}</span>
          {role && (
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${isRoleBadge[role] ?? "bg-gray-100 text-gray-600"}`}>
              {role.replace("_", " ")}
            </span>
          )}
          <button onClick={logout} className="text-gray-400 hover:text-red-600">Sign out</button>
        </div>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="/waitlist" element={<WaitlistPage />} />
          <Route path="/outreach" element={<OutreachLogPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route
            path="/settings"
            element={
              <RequireRole allowed={["admin"]}>
                <SettingsPage />
              </RequireRole>
            }
          />
          <Route
            path="/audit-log"
            element={
              <RequireRole allowed={["admin"]}>
                <AuditLogPage />
              </RequireRole>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/*" element={<Layout />} />
      </Routes>
    </BrowserRouter>
  );
}
