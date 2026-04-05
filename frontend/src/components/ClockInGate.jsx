import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircularProgress, Box } from "@mui/material";
import { Navigate, useLocation } from "react-router-dom";
import { getClockPayrollUiSettings, getTaSessionCurrent } from "../api";
import { useAuth } from "../context/AuthContext";
import { asBool } from "../utils/bool";

function isLoginPath(path) {
  const p = path || "";
  return p === "/login" || p.startsWith("/login/");
}

/**
 * Redirects users who must clock in to /clock until they have an active session.
 * Honors clock_payroll_ui clock.clock_in_gate_enabled (default on).
 */
export default function ClockInGate({ user, children }) {
  const location = useLocation();
  const { hasPerm, loading: authLoading } = useAuth();
  const path = location.pathname || "/";

  const [ui, setUi] = useState(null);
  const [sessionOk, setSessionOk] = useState(false);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const prevPathRef = useRef(path);
  const initialSessionPollRef = useRef(false);

  useEffect(() => {
    getClockPayrollUiSettings()
      .then((res) => setUi(res.data || null))
      .catch(() => setUi(null));
  }, []);

  const gateEnabled = useMemo(() => {
    const c = ui?.clock || {};
    return asBool(c.clock_in_gate_enabled, true);
  }, [ui]);

  const exempt = useMemo(() => {
    if (!user) return true;
    if (!gateEnabled) return true;
    const roles = (user.roles || []).map((r) => String(r).toUpperCase());
    if (roles.includes("ADMIN")) return true;
    if (!hasPerm("ta.clock")) return true;
    if (hasPerm("ta.monitor") || hasPerm("ta.settings")) return true;
    return false;
  }, [user, gateEnabled, hasPerm]);

  const pollSession = useCallback(() => {
    if (exempt || !hasPerm("ta.clock")) {
      setSessionOk(true);
      setSessionLoaded(true);
      return;
    }
    getTaSessionCurrent({})
      .then((res) => {
        setSessionOk(!!res.data?.session);
        setSessionLoaded(true);
      })
      .catch(() => {
        setSessionOk(false);
        setSessionLoaded(true);
      });
  }, [exempt, hasPerm]);

  /**
   * Re-fetch session on navigation. When leaving /clock, clear sessionLoaded first so we do not
   * redirect home → /clock with a stale "no session" from before clock-in.
   */
  useEffect(() => {
    if (authLoading || !uiLoaded) return;
    if (isLoginPath(path)) return;
    const fromClock = prevPathRef.current === "/clock" && path !== "/clock";
    prevPathRef.current = path;
    if (fromClock) setSessionLoaded(false);
    pollSession();
  }, [authLoading, uiLoaded, path, pollSession, user?.id]);

  useEffect(() => {
    if (exempt || !uiLoaded) return;
    const id = setInterval(pollSession, 60000);
    return () => clearInterval(id);
  }, [exempt, uiLoaded, pollSession]);

  useEffect(() => {
    if (exempt) return;
    const onVis = () => {
      if (document.visibilityState === "visible") pollSession();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [exempt, pollSession]);

  if (!user || isLoginPath(path)) return children;

  if (authLoading) {
    return (
      <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (exempt) return children;

  if (!sessionLoaded) {
    return (
      <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (!sessionOk && path !== "/clock") {
    return <Navigate to="/clock" replace state={{ from: location }} />;
  }

  return children;
}
