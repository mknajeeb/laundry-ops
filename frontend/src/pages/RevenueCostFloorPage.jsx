import { useCallback, useEffect, useMemo } from "react";
import { Box } from "@mui/material";
import { authLogout, clearAuthSession } from "../api";
import RevenueCostFloorFlow from "../opsMobile/RevenueCostFloorFlow";
import {
  clearPinHubSession,
  loadPinHubAppSession,
} from "../utils/pinHubSession";

/**
 * Dedicated PIN Revenue & Cost route — never loads manager Finance dashboard.
 */
export default function RevenueCostFloorPage({ user, onPinHubDone }) {
  const pinHubApp = useMemo(() => loadPinHubAppSession(), []);

  useEffect(() => {
    if (!pinHubApp && user) {
      window.location.replace("/finance/daily-revenue-cost");
    }
  }, [pinHubApp, user]);

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

  const returnToPinMenu = useCallback(async () => {
    await clearWashproSession();
  }, [clearWashproSession]);

  const lockToPinEntry = useCallback(async () => {
    clearPinHubSession();
    await clearWashproSession();
  }, [clearWashproSession]);

  return (
    <Box sx={{ minHeight: "100%", width: "100%" }}>
      <RevenueCostFloorFlow
        user={user}
        onBack={returnToPinMenu}
        onDone={returnToPinMenu}
        onLock={lockToPinEntry}
      />
    </Box>
  );
}
