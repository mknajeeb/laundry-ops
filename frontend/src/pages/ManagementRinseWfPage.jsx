import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import { getManagementRinseWf, getManagementTodaySupplies } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import ManagementRinseWfSection from "../components/management/ManagementRinseWfSection";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

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
  );
}

/**
 * Management → Rinse WF.
 * Core WF loads immediately; Supplies load on a separate async request.
 */
export default function ManagementRinseWfPage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [supplies, setSupplies] = useState(null);
  const [suppliesLoading, setSuppliesLoading] = useState(false);
  const [suppliesError, setSuppliesError] = useState("");
  const coreSeq = useRef(0);
  const supplySeq = useRef(0);
  const coreAbortRef = useRef(null);
  const supplyAbortRef = useRef(null);

  const loadSupplies = useCallback(async (day, refresh = false) => {
    if (supplyAbortRef.current) supplyAbortRef.current.abort();
    const controller = new AbortController();
    supplyAbortRef.current = controller;
    const seq = ++supplySeq.current;
    setSuppliesLoading(true);
    setSuppliesError("");
    try {
      const res = await getManagementTodaySupplies(day, {
        refresh: refresh ? 1 : undefined,
        signal: controller.signal,
      });
      if (seq !== supplySeq.current || controller.signal.aborted) return;
      setSupplies(res.data?.supplies || null);
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      if (seq !== supplySeq.current) return;
      setSuppliesError(err?.response?.data?.error || err?.message || "Supplies unavailable");
      // Keep prior supplies on refresh failure; clear only on hard miss.
      setSupplies((prev) => (refresh && prev?.available ? prev : null));
    } finally {
      if (seq === supplySeq.current) setSuppliesLoading(false);
    }
  }, []);

  const loadCore = useCallback(async (day, refresh = false) => {
    if (coreAbortRef.current) coreAbortRef.current.abort();
    const controller = new AbortController();
    coreAbortRef.current = controller;
    const seq = ++coreSeq.current;

    if (!refresh) setData(null);
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseWf(day, {
        refresh: refresh ? 1 : undefined,
        signal: controller.signal,
      });
      if (seq !== coreSeq.current || controller.signal.aborted) return;
      setData(res.data || null);
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      if (seq !== coreSeq.current) return;
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load Rinse WF");
    } finally {
      if (seq === coreSeq.current) setLoading(false);
    }
  }, []);

  const load = useCallback(async (day, refresh = false) => {
    // Core and supplies refresh independently; do not block core on supply.
    const corePromise = loadCore(day, refresh);
    const supplyPromise = loadSupplies(day, refresh);
    await Promise.allSettled([corePromise, supplyPromise]);
  }, [loadCore, loadSupplies]);

  useEffect(() => {
    load(dateEt, false);
    return () => {
      if (coreAbortRef.current) coreAbortRef.current.abort();
      if (supplyAbortRef.current) supplyAbortRef.current.abort();
    };
  }, [dateEt, load]);

  const refreshedLabel = useMemo(() => {
    if (!data?.generated_at_et) return "";
    return formatFriendlyEtWall(data.generated_at_et);
  }, [data?.generated_at_et]);

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

      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 1.5, mb: 1 }} spacing={1}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>Rinse WF</Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            {formatDayLabel(dateEt)}
            {refreshedLabel ? ` · refreshed ${refreshedLabel}` : ""}
          </Typography>
        </Box>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            inputProps={{ "aria-label": "Business date" }}
            sx={{ width: 150 }}
          />
          <IconButton
            aria-label="Refresh"
            onClick={() => load(dateEt, true)}
            disabled={loading && suppliesLoading}
            size="small"
          >
            {loading ? <CircularProgress size={18} /> : <RefreshIcon />}
          </IconButton>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

      {data ? (
        <ManagementRinseWfSection
          rinse={data.rinse || null}
          supplies={supplies}
          suppliesLoading={suppliesLoading}
          suppliesError={suppliesError}
          selectedDateEt={dateEt}
          onRefresh={() => load(dateEt, true)}
        />
      ) : loading ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={22} />
        </Box>
      ) : null}
    </Box>
  );
}
