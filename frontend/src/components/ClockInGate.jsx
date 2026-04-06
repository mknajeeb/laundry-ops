import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircularProgress, Box } from "@mui/material";
import { Navigate, useLocation } from "react-router-dom";
import { getTaBootstrap, getTaSessionCurrent } from "../api";
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

  const gateEnabled = useMemo(() => {
    const c = ui?.clock || {};
    return asBool(c.clock_in_gate_enabled, true);
  }, [ui]);

  const strictGate = useMemo(() => asBool(ui?.clock?.clock_in_gate_strict, false), [ui]);

  /** Users who might be blocked by the gate — parallel-fetch UI + session for latency; gate-off wins over session. */
  const needsUiForGate = useMemo(() => {
    if (!user) return false;
    const roles = Array.isArray(user.roles)
      ? user.roles.map((r) => String(r).toUpperCase())
      : user.role_code
        ? [String(user.role_code).toUpperCase()]
        : [];
    if (roles.includes("ADMIN")) return false;
    if (!hasPerm("ta.clock")) return false;
    if (hasPerm("ta.monitor") || hasPerm("ta.settings")) return false;
    return true;
  }, [user, hasPerm]);

  const exempt = useMemo(() => {
    if (!user) return true;
    if (!gateEnabled) return true;
    if (!hasPerm("ta.clock")) return true;
    if (strictGate) return false;
    const roles = Array.isArray(user.roles)
      ? user.roles.map((r) => String(r).toUpperCase())
      : user.role_code
        ? [String(user.role_code).toUpperCase()]
        : [];
    if (roles.includes("ADMIN")) return true;
    if (hasPerm("ta.monitor") || hasPerm("ta.settings")) return true;
    return false;
  }, [user, gateEnabled, hasPerm, strictGate]);

  const pollSession = useCallback(() => {
    if (exempt || !hasPerm("ta.clock")) {
      setSessionOk(true);
      setSessionLoaded(true);
      return;
    }
    if (needsUiForGate) {
      getTaBootstrap({})
        .catch(() => null)
        .then((res) => {
          if (!res?.data) {
            setSessionLoaded(true);
            setSessionOk(false);
            return;
          }
          const uiPayload = res.data.clock_payroll_ui;
          if (uiPayload) setUi(uiPayload);
          const c = uiPayload?.clock || {};
          if (!asBool(c.clock_in_gate_enabled, true)) {
            setSessionOk(true);
            setSessionLoaded(true);
            return;
          }
          setSessionOk(!!res.data.session_state?.session);
          setSessionLoaded(true);
        });
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
  }, [exempt, hasPerm, needsUiForGate]);

  useEffect(() => {
    initialSessionPollRef.current = false;
  }, [user?.id]);

  /** Load clock UI (strict gate, toggles) for anyone with ta.clock so exemptions stay accurate. */
  useEffect(() => {
    if (authLoading || !user || isLoginPath(path)) return;
    if (!hasPerm("ta.clock")) return;
    getTaBootstrap({})
      .then((res) => {
        const uiPayload = res?.data?.clock_payroll_ui;
        if (uiPayload) {
          setUi((prev) => ({
            clock: { ...(prev?.clock || {}), ...(uiPayload.clock || {}) },
            payroll: { ...(prev?.payroll || {}), ...(uiPayload.payroll || {}) },
          }));
        }
      })
      .catch(() => {});
  }, [authLoading, user?.id, hasPerm, path]);

  /**
   * Poll session on first load, when leaving /clock, or when path/user changes meaningfully —
   * not on every arbitrary route change.
   */
  useEffect(() => {
    if (authLoading) return;
    if (isLoginPath(path)) return;
    const fromClock = prevPathRef.current === "/clock" && path !== "/clock";
    prevPathRef.current = path;
    if (fromClock) setSessionLoaded(false);
    const needPoll = fromClock || !initialSessionPollRef.current;
    if (needPoll) {
      initialSessionPollRef.current = true;
      pollSession();
    }
  }, [authLoading, path, pollSession, user?.id]);

  useEffect(() => {
    if (exempt) return;
    const id = setInterval(pollSession, 120000);
    return () => clearInterval(id);
  }, [exempt, pollSession]);

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
