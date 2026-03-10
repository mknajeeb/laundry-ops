import { useEffect, useMemo, useState } from "react";
import { Alert, Box, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { getDashboard } from "../api";
import { useNavigate } from "react-router-dom";

function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadStats() {
      try {
        setLoading(true);
        setError("");
        const res = await getDashboard();
        setStats(res.data || {});
      } catch (err) {
        console.error(err);
        setError("Could not load dashboard stats.");
      } finally {
        setLoading(false);
      }
    }

    loadStats();
  }, []);

  const safe = stats || {};

  const batchDateLabel = useMemo(() => {
    if (!safe.batch_date) return "No batch date";

    const dt = new Date(safe.batch_date);
    const dateLabel = Number.isNaN(dt.getTime())
      ? String(safe.batch_date).split(" ")[0]
      : dt.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });

    const dayLabel = safe.batch_day || (Number.isNaN(dt.getTime()) ? "" : dt.toLocaleDateString(undefined, { weekday: "long" }));

    return dayLabel ? `${dayLabel}, ${dateLabel}` : dateLabel;
  }, [safe.batch_date, safe.batch_day]);

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
      <Typography sx={{ color: "#6b7280", mt: 0.3 }}>Batch: {batchDateLabel}</Typography>

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
        <Stack spacing={1.2} sx={{ mt: 1.5 }}>
          <Paper
            onClick={() => navigate("/orders")}
            sx={{ p: 1.4, borderRadius: 2, borderTop: "4px solid #0ea5e9", cursor: "pointer" }}
          >
            <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 700 }}>All Orders</Typography>
            <Typography sx={{ fontSize: 36, fontWeight: 900, lineHeight: 1.1 }}>{safe.total_orders ?? 0}</Typography>
          </Paper>

          <Paper
            onClick={() => navigate("/orders?service=WF")}
            sx={{ p: 1.4, borderRadius: 2, borderTop: "4px solid #f59e0b", cursor: "pointer" }}
          >
            <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 700 }}>WF</Typography>
            <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>{safe.wf_total ?? 0}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 0.8 }}>
              <ChipStat
                label="Rush"
                value={safe.wf_rush ?? 0}
                tone="#ef4444"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate("/orders?service=WF&rush=RUSH");
                }}
              />
              <ChipStat
                label="Non-Rush"
                value={safe.wf_non_rush ?? 0}
                tone="#16a34a"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate("/orders?service=WF&rush=NON-RUSH");
                }}
              />
            </Stack>
          </Paper>

          <Paper
            onClick={() => navigate("/orders?service=HD")}
            sx={{ p: 1.4, borderRadius: 2, borderTop: "4px solid #a855f7", cursor: "pointer" }}
          >
            <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 700 }}>HD</Typography>
            <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>{safe.hd_total ?? 0}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 0.8 }}>
              <ChipStat
                label="Rush"
                value={safe.hd_rush ?? 0}
                tone="#ef4444"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate("/orders?service=HD&rush=RUSH");
                }}
              />
              <ChipStat
                label="Non-Rush"
                value={safe.hd_non_rush ?? 0}
                tone="#16a34a"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate("/orders?service=HD&rush=NON-RUSH");
                }}
              />
            </Stack>
          </Paper>
        </Stack>
      )}
    </Box>
  );
}

function ChipStat({ label, value, tone, onClick }) {
  return (
    <Box
      onClick={onClick}
      sx={{
        flex: 1,
        background: "#f9fafb",
        border: "1px solid #e5e7eb",
        borderRadius: 1.5,
        p: 0.8,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 700 }}>{label}</Typography>
      <Typography sx={{ fontSize: 20, fontWeight: 900, color: tone, lineHeight: 1.1 }}>{value}</Typography>
    </Box>
  );
}

export default Dashboard;
