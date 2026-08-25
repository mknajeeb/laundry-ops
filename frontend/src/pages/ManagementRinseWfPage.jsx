import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  getManagementRinseWf,
  getManagementRinseWfSecondary,
  getManagementTodaySupplies,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import ManagementRinseWfSection from "../components/management/ManagementRinseWfSection";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { mergeRinseWfDashboardPayload } from "./managementRinseWfLoadModel";

function todayEtIso() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function formatDayLabel(iso) {
  const parts = String(iso || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !n && n !== 0)) return iso || "";
  const [year, month, day] = parts;
  const dt = new Date(year, month - 1, day);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function isAbortError(err) {
  return (
    err?.code === "ERR_CANCELED"
    || err?.name === "CanceledError"
    || err?.name === "AbortError"
    || Boolean(err?.config?.signal?.aborted)
  );
}

function errorMessage(err, fallback) {
  const fromBody = err?.response?.data?.error || err?.response?.data?.message;
  if (fromBody) return String(fromBody);
  const msg = String(err?.message || "").trim();
  if (!msg || msg === "Network Error") {
    return fallback;
  }
  return msg;
}

/**
 * Management → Rinse WF.
 * Primary dashboard loads first; specialty/review and supplies resolve independently.
 */
export default function ManagementRinseWfPage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [primaryData, setPrimaryData] = useState(null);
  const [secondaryData, setSecondaryData] = useState(null);
  const [primaryLoading, setPrimaryLoading] = useState(true);
  const [secondaryLoading, setSecondaryLoading] = useState(true);
  const [primaryError, setPrimaryError] = useState("");
  const [secondaryError, setSecondaryError] = useState("");
  const [rushFilter, setRushFilter] = useState("all");
  const [supplies, setSupplies] = useState(null);
  const [suppliesLoading, setSuppliesLoading] = useState(false);
  const [suppliesError, setSuppliesError] = useState("");
  const primarySeq = useRef(0);
  const secondarySeq = useRef(0);
  const supplySeq = useRef(0);
  const primaryAbortRef = useRef(null);
  const secondaryAbortRef = useRef(null);
  const supplyAbortRef = useRef(null);
  const loadStartedRef = useRef(null);
  const primaryRenderedRef = useRef(false);

  const loadSupplies = useCallback(async (day, { refresh = false, rush = "all" } = {}) => {
    if (supplyAbortRef.current) supplyAbortRef.current.abort();
    const controller = new AbortController();
    supplyAbortRef.current = controller;
    const seq = ++supplySeq.current;
    setSuppliesLoading(true);
    setSuppliesError("");
    try {
      const res = await getManagementTodaySupplies(day, {
        refresh: refresh ? 1 : undefined,
        rush,
        signal: controller.signal,
      });
      if (seq !== supplySeq.current || controller.signal.aborted) return;
      setSupplies(res.data?.supplies || null);
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      if (seq !== supplySeq.current) return;
      setSuppliesError(err?.response?.data?.error || err?.message || "Supplies unavailable");
      setSupplies((prev) => (refresh && prev?.available ? prev : null));
    } finally {
      if (seq === supplySeq.current) setSuppliesLoading(false);
    }
  }, []);

  const loadPrimary = useCallback(async (day, refresh = false) => {
    if (primaryAbortRef.current) primaryAbortRef.current.abort();
    const controller = new AbortController();
    primaryAbortRef.current = controller;
    const seq = ++primarySeq.current;

    if (!refresh) setPrimaryData(null);
    setPrimaryLoading(true);
    setPrimaryError("");
    try {
      const res = await getManagementRinseWf(day, {
        refresh: refresh ? 1 : undefined,
        signal: controller.signal,
      });
      if (seq !== primarySeq.current || controller.signal.aborted) return;
      setPrimaryData(res.data || null);
      if (!primaryRenderedRef.current) {
        primaryRenderedRef.current = true;
        if (loadStartedRef.current != null && typeof window !== "undefined") {
          window.__wfPrimaryRenderMs = Math.round(performance.now() - loadStartedRef.current);
        }
      }
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      if (seq !== primarySeq.current) return;
      if (!refresh) setPrimaryData(null);
      setPrimaryError(errorMessage(err, "Unable to load Rinse WF — tap refresh to retry"));
    } finally {
      if (seq === primarySeq.current) setPrimaryLoading(false);
    }
  }, []);

  const loadSecondary = useCallback(async (day, refresh = false, attempt = 0) => {
    if (secondaryAbortRef.current) secondaryAbortRef.current.abort();
    const controller = new AbortController();
    secondaryAbortRef.current = controller;
    const seq = ++secondarySeq.current;

    if (!refresh && attempt === 0) setSecondaryData(null);
    setSecondaryLoading(true);
    if (attempt === 0) setSecondaryError("");
    try {
      const res = await getManagementRinseWfSecondary(day, {
        refresh: refresh ? 1 : undefined,
        signal: controller.signal,
      });
      if (seq !== secondarySeq.current || controller.signal.aborted) return;
      setSecondaryData(res.data || null);
      setSecondaryError("");
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      if (seq !== secondarySeq.current) return;
      const noResponse = !err?.response;
      if (noResponse && attempt < 1) {
        // API restart / brief blip — retry once without wiping a good prior payload.
        await new Promise((r) => setTimeout(r, 600));
        if (seq !== secondarySeq.current) return;
        return loadSecondary(day, refresh, attempt + 1);
      }
      setSecondaryError(
        errorMessage(err, "Review metrics temporarily unavailable — tap refresh"),
      );
      if (!refresh) setSecondaryData(null);
    } finally {
      if (seq === secondarySeq.current) setSecondaryLoading(false);
    }
  }, []);

  const load = useCallback(async (day, refresh = false, rush = rushFilter) => {
    loadStartedRef.current = performance.now();
    primaryRenderedRef.current = false;
    const primaryPromise = loadPrimary(day, refresh);
    const secondaryPromise = loadSecondary(day, refresh);
    const supplyPromise = loadSupplies(day, { refresh, rush });
    await Promise.allSettled([primaryPromise, secondaryPromise, supplyPromise]);
  }, [loadPrimary, loadSecondary, loadSupplies, rushFilter]);

  useEffect(() => {
    load(dateEt, false, rushFilter);
    return () => {
      if (primaryAbortRef.current) primaryAbortRef.current.abort();
      if (secondaryAbortRef.current) secondaryAbortRef.current.abort();
      if (supplyAbortRef.current) supplyAbortRef.current.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateEt]);

  const onRushFilterChange = useCallback((next) => {
    setRushFilter(next);
    loadSupplies(dateEt, { rush: next });
  }, [dateEt, loadSupplies]);

  const mergedData = useMemo(
    () => mergeRinseWfDashboardPayload(primaryData, secondaryData),
    [primaryData, secondaryData],
  );

  const refreshedLabel = useMemo(() => {
    if (!primaryData?.generated_at_et) return "";
    return formatFriendlyEtWall(primaryData.generated_at_et);
  }, [primaryData?.generated_at_et]);

  const refreshing = primaryLoading || secondaryLoading || suppliesLoading;

  return (
    <Box
      className="page"
      sx={{
        maxWidth: 720,
        mx: "auto",
        width: "100%",
        px: { xs: 1.5, sm: 2 },
        pb: 3,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <ManagementHubNav activeId="rinse_wf" />

      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 1.25, mb: 1.25 }} spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1, letterSpacing: 0.2 }}>
            RINSE WF
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            {formatDayLabel(dateEt)}
            {refreshedLabel ? ` · ${refreshedLabel}` : ""}
          </Typography>
        </Box>
        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ flexShrink: 0 }}>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            inputProps={{ "aria-label": "Business date" }}
            sx={{ width: 142 }}
          />
          <IconButton
            aria-label="Refresh"
            onClick={() => load(dateEt, true, rushFilter)}
            disabled={refreshing}
            size="small"
            sx={{
              opacity: refreshing ? 0.6 : 1,
            }}
          >
            <RefreshIcon
              sx={
                refreshing
                  ? {
                    animation: "spin 0.9s linear infinite",
                    "@keyframes spin": {
                      "0%": { transform: "rotate(0deg)" },
                      "100%": { transform: "rotate(360deg)" },
                    },
                  }
                  : undefined
              }
            />
          </IconButton>
        </Stack>
      </Stack>

      {primaryError ? <Alert severity="error" sx={{ mb: 1.5 }}>{primaryError}</Alert> : null}
      {secondaryError ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {secondaryError}
        </Alert>
      ) : null}

      <ManagementRinseWfSection
        rinse={mergedData?.rinse || primaryData?.rinse || null}
        review={mergedData?.review || null}
        supplies={supplies}
        suppliesLoading={suppliesLoading}
        suppliesError={suppliesError}
        onRetrySupplies={() => loadSupplies(dateEt, { refresh: true, rush: rushFilter })}
        rushFilter={rushFilter}
        onRushFilterChange={onRushFilterChange}
        selectedDateEt={dateEt}
        onRefresh={() => load(dateEt, true, rushFilter)}
        primaryLoading={primaryLoading}
        secondaryLoading={secondaryLoading}
      />
    </Box>
  );
}
