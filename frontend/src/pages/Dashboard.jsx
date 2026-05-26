import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Grid,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { getCurrentUploadBatch, getDashboard, getOperationsDashboardSummary } from "../api";
import { useLocation, useNavigate } from "react-router-dom";

function parseAsLocalDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return null;
  return new Date(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate());
}

function toDateParam(value) {
  if (!value) return "";
  const d = parseAsLocalDate(value);
  if (!d || Number.isNaN(d.getTime())) return String(value).slice(0, 10);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function StatCard({ label, value, color, onClick, sub }) {
  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: 1.1,
        borderRadius: 1.5,
        border: "1px solid #e5e7eb",
        borderTop: `3px solid ${color}`,
        cursor: onClick ? "pointer" : "default",
        minHeight: 72,
        "&:hover": onClick ? { bgcolor: "#f8fafc" } : undefined,
      }}
    >
      <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#6b7280", textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 26, fontWeight: 900, lineHeight: 1.1, color: "#111827" }}>{value ?? 0}</Typography>
      {sub ? (
        <Typography sx={{ fontSize: 10, color: "#9ca3af", mt: 0.3 }}>{sub}</Typography>
      ) : null}
    </Paper>
  );
}

function Dashboard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [stats, setStats] = useState(null);
  const [opsSummary, setOpsSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeBatch, setActiveBatch] = useState(null);

  const reloadDashboard = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const [dashRes, batchRes] = await Promise.all([getDashboard(), getCurrentUploadBatch()]);
      const batch = batchRes?.data || null;
      setStats(dashRes.data || {});
      setActiveBatch(batch);

      const dateParam = toDateParam(batch?.batch_date || dashRes.data?.batch_date);
      const summaryParams = { date: dateParam };
      if (batch?.id) summaryParams.batch_id = batch.id;
      try {
        const sumRes = await getOperationsDashboardSummary(summaryParams);
        setOpsSummary(sumRes.data || null);
      } catch {
        setOpsSummary(null);
      }
    } catch (err) {
      console.error(err);
      setError("Could not load dashboard stats.");
      try {
        const batchRes = await getCurrentUploadBatch();
        setActiveBatch(batchRes?.data || null);
      } catch {
        setActiveBatch(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (location.pathname !== "/dashboard") return;
    reloadDashboard();
  }, [location.pathname, reloadDashboard]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible" && location.pathname === "/dashboard") {
        reloadDashboard();
      }
    };
    const onBatch = () => {
      if (location.pathname === "/dashboard") reloadDashboard();
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("washpro-upload-batch-changed", onBatch);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("washpro-upload-batch-changed", onBatch);
    };
  }, [location.pathname, reloadDashboard]);

  const safe = stats || {};
  const sum = opsSummary || {};

  const batchDateIso = useMemo(
    () => toDateParam(sum.date || activeBatch?.batch_date || safe.batch_date),
    [sum.date, activeBatch?.batch_date, safe.batch_date]
  );

  const batchDateLabel = useMemo(() => {
    const raw = sum.date || activeBatch?.batch_date || safe.batch_date;
    if (!raw) return "No batch date";
    const dt = parseAsLocalDate(raw) || new Date(raw);
    const dateLabel = Number.isNaN(dt.getTime())
      ? String(raw).split(" ")[0]
      : dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    const dayLabel =
      safe.batch_day ||
      (Number.isNaN(dt.getTime()) ? "" : dt.toLocaleDateString(undefined, { weekday: "long" }));
    return dayLabel ? `${dayLabel}, ${dateLabel}` : dateLabel;
  }, [sum.date, activeBatch?.batch_date, safe.batch_date, safe.batch_day]);

  const asOfLabel = activeBatch?.id
    ? `Batch #${activeBatch.id} · ${batchDateLabel}`
    : `As of ${batchDateLabel}`;

  const drillOrderSearch = (extra = {}) => {
    const params = new URLSearchParams();
    if (batchDateIso) {
      params.set("date_clean_from", batchDateIso);
      params.set("date_clean_to", batchDateIso);
    }
    Object.entries(extra).forEach(([k, v]) => {
      if (v != null && v !== "") params.set(k, v);
    });
    navigate(`/rinse/order-search?${params.toString()}`);
  };

  return (
    <Box
      sx={{
        minHeight: "100%",
        px: { xs: 1.2, md: 2.2 },
        py: 1.2,
        background: "radial-gradient(circle at top left, #e0f2fe 0%, #f8fafc 35%, #f8fafc 100%)",
      }}
    >
      <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>Operations Dashboard</Typography>
      <Typography sx={{ color: "#6b7280", mt: 0.3 }}>{asOfLabel}</Typography>
      {activeBatch && (
        <Box sx={{ mt: 0.7 }}>
          <Alert
            severity={String(activeBatch.state || "").toUpperCase() === "CONFIRMED" ? "success" : "warning"}
          >
            Batch #{activeBatch.id} • {String(activeBatch.batch_date || "").slice(0, 10)} •{" "}
            {String(activeBatch.state || "DRAFT").toUpperCase()}
          </Alert>
        </Box>
      )}

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.2}>
          <CircularProgress />
          <Typography color="text.secondary">Loading metrics...</Typography>
        </Stack>
      ) : error ? (
        <Alert severity="error" sx={{ mt: 1.5 }}>
          {error}
        </Alert>
      ) : (
        <Stack spacing={1.5} sx={{ mt: 1.5 }}>
          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#374151" }}>Order status (registry)</Typography>
          <Grid container spacing={1}>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                label="Total orders"
                value={sum.total_orders ?? safe.total_orders}
                color="#0ea5e9"
                onClick={() => drillOrderSearch({})}
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                label="Rush"
                value={sum.rush_total}
                color="#ef4444"
                onClick={() => drillOrderSearch({ rush_type: "RUSH" })}
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                label="Non-Rush"
                value={sum.non_rush_total}
                color="#16a34a"
                onClick={() => drillOrderSearch({ rush_type: "NON-RUSH" })}
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                label="Completed"
                value={sum.completed_total}
                color="#059669"
                onClick={() => drillOrderSearch({ lifecycle_filter: "completed" })}
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                label="Remaining"
                value={sum.remaining_total}
                color="#f59e0b"
                onClick={() => drillOrderSearch({ lifecycle_filter: "incomplete" })}
              />
            </Grid>
          </Grid>

          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#374151" }}>Rush / Non-Rush breakdown</Typography>
          <Grid container spacing={1}>
            <Grid item xs={6} sm={3}>
              <StatCard
                label="Rush completed"
                value={sum.rush_completed}
                color="#dc2626"
                onClick={() => drillOrderSearch({ rush_type: "RUSH", lifecycle_filter: "completed" })}
              />
            </Grid>
            <Grid item xs={6} sm={3}>
              <StatCard
                label="Rush remaining"
                value={sum.rush_remaining}
                color="#f87171"
                onClick={() => drillOrderSearch({ rush_type: "RUSH", lifecycle_filter: "incomplete" })}
              />
            </Grid>
            <Grid item xs={6} sm={3}>
              <StatCard
                label="Non-Rush completed"
                value={sum.non_rush_completed}
                color="#15803d"
                onClick={() => drillOrderSearch({ rush_type: "NON-RUSH", lifecycle_filter: "completed" })}
              />
            </Grid>
            <Grid item xs={6} sm={3}>
              <StatCard
                label="Non-Rush remaining"
                value={sum.non_rush_remaining}
                color="#4ade80"
                onClick={() => drillOrderSearch({ rush_type: "NON-RUSH", lifecycle_filter: "incomplete" })}
              />
            </Grid>
          </Grid>

          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#374151" }}>Service & ops</Typography>
          <Grid container spacing={1}>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="WF total"
                value={sum.wf_total ?? safe.wf_total}
                color="#f59e0b"
                onClick={() => navigate("/orders?service=WF")}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="WF completed"
                value={sum.wf_completed}
                color="#d97706"
                onClick={() => drillOrderSearch({ service_type: "WF", lifecycle_filter: "completed" })}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="WF remaining"
                value={sum.wf_remaining}
                color="#fbbf24"
                onClick={() => drillOrderSearch({ service_type: "WF", lifecycle_filter: "incomplete" })}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="HD total"
                value={sum.hd_total ?? safe.hd_total}
                color="#a855f7"
                onClick={() => navigate("/orders?service=HD")}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="HD completed"
                value={sum.hd_completed}
                color="#9333ea"
                onClick={() => drillOrderSearch({ service_type: "HD", lifecycle_filter: "completed" })}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="HD remaining"
                value={sum.hd_remaining}
                color="#c084fc"
                onClick={() => drillOrderSearch({ service_type: "HD", lifecycle_filter: "incomplete" })}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="Checkout active"
                value={sum.checkout_active ?? safe.total_orders}
                color="#0284c7"
                onClick={() => drillOrderSearch({ lifecycle_filter: "in_checkout" })}
              />
            </Grid>
            <Grid item xs={6} sm={3} md={2}>
              <StatCard
                label="Folding exceptions"
                value={sum.folding_exceptions}
                color="#ea580c"
                onClick={() => navigate("/rinse/folding-exceptions")}
              />
            </Grid>
          </Grid>
        </Stack>
      )}
    </Box>
  );
}

export default Dashboard;
