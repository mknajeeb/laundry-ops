import { useCallback, useEffect, useMemo } from "react";
import { Box } from "@mui/material";
import { authLogout, clearAuthSession } from "../api";
import HangDryFloorFlow from "../opsMobile/HangDryFloorFlow";
import {
  clearPinHubSession,
  loadPinHubAppSession,
} from "../utils/pinHubSession";

/**
 * PIN Hang Dry route — thin wrapper over Management Rinse HD production APIs.
 */
export default function HangDryFloorPage({ onPinHubDone }) {
  const pinHubApp = useMemo(() => loadPinHubAppSession(), []);

  useEffect(() => {
    if (!pinHubApp) {
      window.location.replace("/management/rinse-hd");
    }
  }, [pinHubApp]);

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
      <HangDryFloorFlow onBack={returnToPinMenu} onLock={lockToPinEntry} />
    </Box>
  );
}
