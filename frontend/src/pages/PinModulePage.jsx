/**
 * Shared shell for supervisor/admin PIN modules opened from the phone hub.
 * Back returns to the dashboard when that module opened this screen.
 */
import { useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { authLogout, clearAuthSession } from "../api";
import { clearOneSignalUser } from "../onesignalUser";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubAppSession,
  loadPinHubSession,
} from "../utils/pinHubSession";

export default function PinModulePage({ onPinHubDone, children }) {
  const pinHubApp = useMemo(() => loadPinHubAppSession(), []);
  const location = useLocation();
  const navigate = useNavigate();

  const clearWashproSession = useCallback(async () => {
    try {
      await authLogout();
    } catch {
      /* ignore */
    }
    clearAuthSession();
    try {
      localStorage.removeItem("ta_token");
    } catch {
      /* ignore */
    }
    onPinHubDone?.();
  }, [onPinHubDone]);

  const onBack = useCallback(async () => {
    if (location.state?.fromDashboard) {
      navigate("/pin-dashboard", { replace: true });
      return;
    }
    await clearWashproSession();
  }, [clearWashproSession, location.state, navigate]);

  const onLock = useCallback(async () => {
    clearOneSignalUser();
    clearPinHubSession();
    clearPinHubAppSession();
    await clearWashproSession();
  }, [clearWashproSession]);

  useEffect(() => {
    if (pinHubApp) return;
    const slug =
      loadPinHubSession()?.organization_slug || loadPinHubAppSession()?.organization_slug || "";
    const next = `${location.pathname}${location.search}`;
    const target = slug
      ? `/pin/${encodeURIComponent(slug)}?next=${encodeURIComponent(next)}`
      : "/pin";
    navigate(target, { replace: true });
  }, [pinHubApp, location.pathname, location.search, navigate]);

  if (!pinHubApp) return null;
  return children({ onBack, onLock });
}
