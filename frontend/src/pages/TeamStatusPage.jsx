/**
 * PIN hub → Team Status (manager attendance/role roster).
 * Requires pin-hub app session from EmployeePinHub unlock with team_status.
 */
import { useCallback, useMemo } from "react";
import { authLogout, clearAuthSession } from "../api";
import TeamStatusFlow from "../opsMobile/TeamStatusFlow";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubAppSession,
} from "../utils/pinHubSession";

export default function TeamStatusPage({ onPinHubDone }) {
  const pinHubApp = useMemo(() => loadPinHubAppSession(), []);

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
    await clearWashproSession();
  }, [clearWashproSession]);

  const onLock = useCallback(async () => {
    clearPinHubSession();
    clearPinHubAppSession();
    await clearWashproSession();
  }, [clearWashproSession]);

  if (!pinHubApp) return null;

  return <TeamStatusFlow onBack={onBack} onLock={onLock} />;
}
