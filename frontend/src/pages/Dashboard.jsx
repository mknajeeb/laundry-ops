import { useEffect, useMemo, useState } from "react";
import { Alert, Box, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { getDashboard } from "../api";

function Dashboard() {
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

  const cards = useMemo(() => {
    const safe = stats || {};

    return [
      { label: "Total", value: safe.total_orders ?? 0, tone: "#0ea5e9" },
      { label: "WF", value: safe.wf_total ?? 0, tone: "#f59e0b" },
      { label: "HD", value: safe.hd_total ?? 0, tone: "#a855f7" },
      { label: "WF Rush", value: safe.wf_rush ?? 0, tone: "#ef4444" },
      { label: "WF Non-Rush", value: safe.wf_non_rush ?? 0, tone: "#16a34a" },
      { label: "HD Rush", value: safe.hd_rush ?? 0, tone: "#fb7185" },
      { label: "HD Non-Rush", value: safe.hd_non_rush ?? 0, tone: "#22c55e" },
    ];
  }, [stats]);

  return (
    <Box
      sx={{
        minHeight: "100vh",
        px: { xs: 1.2, md: 2.4 },
        py: 1.5,
        background: "radial-gradient(circle at top left, #e0f2fe 0%, #f8fafc 36%, #f8fafc 100%)",
      }}
    >
      <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>Operations Dashboard</Typography>
      <Typography sx={{ color: "#6b7280", mt: 0.4 }}>Today snapshot</Typography>

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
        <Box
          sx={{
            mt: 1.5,
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", md: "repeat(4, minmax(0, 1fr))" },
            gap: 1,
          }}
        >
          {cards.map((card) => (
            <Paper
              key={card.label}
              sx={{
                p: 1.4,
                borderRadius: 2,
                borderTop: `4px solid ${card.tone}`,
              }}
            >
              <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 700 }}>{card.label}</Typography>
              <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1.1, mt: 0.5 }}>
                {card.value}
              </Typography>
            </Paper>
          ))}
        </Box>
      )}
    </Box>
  );
}

export default Dashboard;
