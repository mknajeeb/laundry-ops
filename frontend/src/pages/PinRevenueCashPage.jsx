import { useCallback, useMemo } from "react";
import { authLogout, clearAuthSession } from "../api";
import PinRevenueCashFlow from "../opsMobile/PinRevenueCashFlow";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubAppSession,
} from "../utils/pinHubSession";

/**
 * PIN hub → Revenue / Cash (Management entry surface).
 * Requires an active pin-hub app session from EmployeePinHub unlock.
 */
export default function PinRevenueCashPage({ onPinHubDone }) {
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

  /** Back — leave Washpro session; keep PIN hub unlock. */
  const onBack = useCallback(async () => {
    await clearWashproSession();
  }, [clearWashproSession]);

  /** Lock — clear hub unlock and Washpro session. */
  const onLock = useCallback(async () => {
    clearPinHubSession();
    clearPinHubAppSession();
    await clearWashproSession();
  }, [clearWashproSession]);

  if (!pinHubApp) return null;

  return <PinRevenueCashFlow onBack={onBack} onLock={onLock} />;
}
