import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { confirmWaitlistToken, declineWaitlistToken } from "../api/patient";

type State = "loading" | "success" | "declined" | "error";

export function WaitlistConfirmPage() {
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  const action = searchParams.get("action") ?? "accept";

  const [state, setState] = useState<State>("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) { setState("error"); setMessage("Invalid link."); return; }

    const fn = action === "decline" ? declineWaitlistToken : confirmWaitlistToken;
    fn(token)
      .then((res) => {
        if (res.status === "booked" || res.status === "accepted") {
          setState("success");
        } else if (res.status === "declined") {
          setState("declined");
        } else {
          setState("error");
        }
        setMessage(res.message ?? "");
      })
      .catch(() => {
        setState("error");
        setMessage("This link may have already been used or expired.");
      });
  }, [token, action]);

  const config: Record<State, { icon: string; heading: string; color: string }> = {
    loading: { icon: "⏳", heading: "Processing…", color: "text-gray-600" },
    success: { icon: "✓", heading: "Appointment confirmed!", color: "text-green-700" },
    declined: { icon: "✗", heading: "Offer declined", color: "text-gray-700" },
    error: { icon: "!", heading: "Link unavailable", color: "text-red-700" },
  };

  const { icon, heading, color } = config[state];

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-sm w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-8 text-center">
        <div className={`text-5xl mb-4 font-bold ${color}`}>{icon}</div>
        <h1 className={`text-xl font-bold mb-2 ${color}`}>{heading}</h1>
        {message && <p className="text-sm text-gray-500">{message}</p>}
        <Link
          to="/portal/login"
          className="mt-6 inline-block text-sm text-blue-600 hover:underline"
        >
          Sign in to patient portal
        </Link>
      </div>
    </div>
  );
}
