import { useCallback, useEffect, useMemo, useState } from "react";
import { getTaSessionCurrent } from "../api";
import { useAuth } from "../context/AuthContext";

/**
 * When signed in with ta.clock, checkout must match Time & Attendance "operational" rules
 * (clocked in, not on break, inside geofence when location is available).
 */
export function useTaOperationalGate({ pollMs = 45000 } = {}) {
  const { token, hasPerm } = useAuth();
  const gateActive = !!(token && hasPerm("ta.clock"));

  const [loading, setLoading] = useState(false);
  const [operationalAllowed, setOperationalAllowed] = useState(true);
  const [reasons, setReasons] = useState([]);

  const refresh = useCallback(async () => {
    if (!gateActive) {
      setLoading(false);
      setOperationalAllowed(true);
      setReasons([]);
      return;
    }
    setLoading(true);
    try {
      let params = {};
      try {
        const pos = await new Promise((resolve) => {
          if (!navigator.geolocation) {
            resolve(null);
            return;
          }
          navigator.geolocation.getCurrentPosition(resolve, () => resolve(null), {
            enableHighAccuracy: true,
            timeout: 8000,
          });
        });
        if (pos?.coords) {
          params = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
        }
      } catch {
        /* optional */
      }
      const res = await getTaSessionCurrent(params);
      const op = res.data?.operational;
      const allowed = op?.allowed !== false;
      setOperationalAllowed(allowed);
      setReasons(Array.isArray(op?.reasons) ? op.reasons : []);
    } catch {
      setOperationalAllowed(false);
      setReasons(["session_check_failed"]);
    } finally {
      setLoading(false);
    }
  }, [gateActive]);

  useEffect(() => {
    const t = setTimeout(() => {
      refresh();
    }, 0);
    return () => clearTimeout(t);
  }, [refresh]);

  useEffect(() => {
    if (!gateActive) return undefined;
    const id = setInterval(() => {
      refresh();
    }, pollMs);
    return () => clearInterval(id);
  }, [gateActive, pollMs, refresh]);

  const checkoutBlocked = useMemo(
    () => gateActive && (loading || !operationalAllowed),
    [gateActive, loading, operationalAllowed]
  );

  const assertCanCheckout = useCallback(async () => {
    if (!gateActive) {
      return { ok: true, reasons: [] };
    }
    let params = {};
    try {
      const pos = await new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error("no geolocation"));
          return;
        }
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15000,
        });
      });
      params = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
    } catch {
      /* still call API — server may allow without coords */
    }
    try {
      const res = await getTaSessionCurrent(params);
      const op = res.data?.operational;
      const ok = op?.allowed === true;
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
