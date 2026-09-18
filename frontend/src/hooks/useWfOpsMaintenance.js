import { useCallback, useEffect, useRef, useState } from "react";
import { getManagementWfOpsMaintenance } from "../api";

const REFETCH_WHEN_ON_MS = 60_000;

/**
 * Single Management-page lookup of org wf_ops_maintenance.
 * Refetches on window focus; while ON, light interval (not per-row polling).
 */
export default function useWfOpsMaintenance({ enabled = true } = {}) {
  const [maintenanceOn, setMaintenanceOn] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const seqRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const seq = ++seqRef.current;
    try {
      const res = await getManagementWfOpsMaintenance();
      if (seq !== seqRef.current) return;
      setMaintenanceOn(Boolean(res?.data?.maintenance_on));
      setError("");
      setLoaded(true);
    } catch (err) {
      if (seq !== seqRef.current) return;
      // Fail open for reads: do not lock UI if status cannot be fetched.
      setError(err?.response?.data?.error || err?.message || "status unavailable");
      setLoaded(true);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    refresh();
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled || !maintenanceOn) return undefined;
    const id = window.setInterval(() => refresh(), REFETCH_WHEN_ON_MS);
    return () => window.clearInterval(id);
  }, [enabled, maintenanceOn, refresh]);

  return {
    maintenanceOn,
    loaded,
    error,
    refresh,
    wfMutationsLocked: Boolean(maintenanceOn),
  };
}
