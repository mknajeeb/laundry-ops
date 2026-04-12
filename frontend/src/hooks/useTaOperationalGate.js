import { useCallback, useEffect, useMemo, useState } from "react";
import { getTaSessionCurrent } from "../api";
import { useAuth } from "../context/AuthContext";

/** Fast, cache-friendly read; never rejects — avoids checkout UI freezing on GPS cold start. */
function getQuickPosition(opts = {}) {
  const { timeoutMs = 4000, maximumAgeMs = 120000 } = opts;
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      resolve,
      () => resolve(null),
      {
        enableHighAccuracy: false,
        maximumAge: maximumAgeMs,
        timeout: timeoutMs,
      }
    );
  });
}

/**
 * When signed in with ta.clock, checkout must match Time & Attendance "operational" rules
 * (clocked in, not on break, inside geofence when location is available).
 */
export function useTaOperationalGate({ pollMs = 45000 } = {}) {
  const { token, hasPerm } = useAuth();
  const gateActive = !!(token && hasPerm("ta.clock"));

  const [loading, setLoading] = useState(false);
  const [firstGateSettled, setFirstGateSettled] = useState(false);
  const [operationalAllowed, setOperationalAllowed] = useState(true);
  const [reasons, setReasons] = useState([]);

  const refresh = useCallback(async (options = {}) => {
    const silent = !!options.silent;
    if (!gateActive) {
      setLoading(false);
      setFirstGateSettled(false);
      setOperationalAllowed(true);
      setReasons([]);
      return;
    }
    if (!silent) {
      setLoading(true);
    }
    try {
      const pos = await getQuickPosition({ timeoutMs: silent ? 3500 : 5000 });
      const params =
        pos?.coords != null
          ? { latitude: pos.coords.latitude, longitude: pos.coords.longitude }
          : {};
      const res = await getTaSessionCurrent(params);
      const op = res.data?.operational;
      const allowed = op?.allowed !== false;
      setOperationalAllowed(allowed);
      setReasons(Array.isArray(op?.reasons) ? op.reasons : []);
    } catch {
      setOperationalAllowed(false);
      setReasons(["session_check_failed"]);
    } finally {
      if (!silent) {
        setLoading(false);
        setFirstGateSettled(true);
      }
    }
  }, [gateActive]);

  useEffect(() => {
    if (!gateActive) {
      setFirstGateSettled(false);
    }
  }, [gateActive]);

  useEffect(() => {
    const t = setTimeout(() => {
      refresh({ silent: false });
    }, 0);
    return () => clearTimeout(t);
  }, [refresh]);

  useEffect(() => {
    if (!gateActive) return undefined;
    const id = setInterval(() => {
      refresh({ silent: true });
    }, pollMs);
    return () => clearInterval(id);
  }, [gateActive, pollMs, refresh]);

  // Block checkout only until the first gate result is known, not during background polls.
  const checkoutBlocked = useMemo(
    () => gateActive && (!firstGateSettled || !operationalAllowed),
    [gateActive, firstGateSettled, operationalAllowed]
  );

  const assertCanCheckout = useCallback(async () => {
    if (!gateActive) {
      return { ok: true, reasons: [] };
    }
    const pos = await getQuickPosition({ timeoutMs: 5000, maximumAgeMs: 60000 });
    const params =
      pos?.coords != null
        ? { latitude: pos.coords.latitude, longitude: pos.coords.longitude }
        : {};
    try {
      const res = await getTaSessionCurrent(params);
      const op = res.data?.operational;
      const ok = op?.allowed !== false;
      const r = Array.isArray(op?.reasons) ? op.reasons : [];
      setOperationalAllowed(ok);
      setReasons(r);
      return { ok, reasons: r };
    } catch {
      return { ok: false, reasons: ["session_check_failed"] };
    }
  }, [gateActive]);

  const bannerMessage = useMemo(() => {
    if (!gateActive || loading) return null;
    if (operationalAllowed) return null;
    const r = reasons.length ? reasons.join(", ") : "see Time Clock";
    return `Time & attendance: checkout is blocked until you are clocked in, off break, and within your geofence (${r}).`;
  }, [gateActive, loading, operationalAllowed, reasons]);

  return {
    gateActive,
    loading,
    operationalAllowed,
    reasons,
    checkoutBlocked,
    refresh,
    assertCanCheckout,
    bannerMessage,
  };
}
