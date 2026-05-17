import { useCallback, useEffect, useState } from "react";
import {
  Box,
  Chip,
  Grid,
  Paper,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { getFoldingLeaderboard } from "../api";
import { formatLbs, formatRate, isoDateInput, targetStatusChipColor } from "../utils/foldingFormat";

const REFRESH_MS = 45000;

const BG_GRADIENT =
  "linear-gradient(135deg, #0f172a 0%, #1e3a5f 35%, #312e81 70%, #4c1d95 100%)";

function TvStat({ label, value, accent = "#38bdf8" }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2.5,
        textAlign: "center",
        bgcolor: "rgba(255,255,255,0.08)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 3,
      }}
    >
      <Typography sx={{ color: "rgba(255,255,255,0.65)", fontSize: 14, fontWeight: 600 }}>
        {label}
      </Typography>
      <Typography sx={{ color: accent, fontSize: 36, fontWeight: 800, lineHeight: 1.1 }}>
        {value}
      </Typography>
    </Paper>
  );
}

function RinseFoldingTvPage() {
  const [period, setPeriod] = useState("today");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      const res = await getFoldingLeaderboard({ period, date: isoDateInput() });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load leaderboard");
    }
  }, [period]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const users = data?.users || [];
  const top = users[0];
  const team = data?.team || {};
  const bench = data?.benchmarks || {};
  const winner = data?.prior_period_winner;
  const updated = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      })
    : "—";

  const periodLabel =
    period === "week" && data?.period_start && data?.period_end
      ? `${data.period_start} – ${data.period_end}`
      : data?.period_start || isoDateInput();

  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: BG_GRADIENT,
        color: "#fff",
        p: { xs: 2, md: 4 },
        boxSizing: "border-box",
      }}
    >
      <Stack
        direction={{ xs: "column", md: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", md: "center" }}
        spacing={2}
        mb={4}
      >
        <Box>
          <Typography
            sx={{
              fontSize: { xs: 28, md: 42 },
              fontWeight: 900,
              letterSpacing: -0.5,
              background: "linear-gradient(90deg, #fbbf24, #f472b6, #38bdf8)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            VeeWash Folding Leaderboard
          </Typography>
          <Typography sx={{ color: "rgba(255,255,255,0.75)", fontSize: 18, mt: 0.5 }}>
            {periodLabel} · Updated {updated}
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          value={period}
          onChange={(_, v) => v && setPeriod(v)}
          sx={{
            "& .MuiToggleButton-root": {
              color: "#fff",
              borderColor: "rgba(255,255,255,0.3)",
              fontWeight: 700,
              px: 3,
              "&.Mui-selected": {
                bgcolor: "rgba(251, 191, 36, 0.25)",
                color: "#fbbf24",
              },
            },
          }}
        >
          <ToggleButton value="today">Today</ToggleButton>
          <ToggleButton value="week">This week</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {error ? (
        <Typography color="#fca5a5" sx={{ mb: 2 }}>
          {error}
        </Typography>
      ) : null}

      {top ? (
        <Paper
          sx={{
            mb: 4,
            p: { xs: 3, md: 4 },
            borderRadius: 4,
            background: "linear-gradient(120deg, rgba(251,191,36,0.35), rgba(244,114,182,0.25))",
            border: "2px solid rgba(251,191,36,0.5)",
          }}
        >
          <Stack direction={{ xs: "column", md: "row" }} alignItems="center" spacing={3}>
            <Typography sx={{ fontSize: { xs: 64, md: 96 }, fontWeight: 900, lineHeight: 1 }}>
              #1
            </Typography>
            <Box flex={1}>
              <Typography sx={{ fontSize: { xs: 32, md: 48 }, fontWeight: 800 }}>
                {top.user_name}
              </Typography>
              <Stack direction="row" spacing={2} flexWrap="wrap" sx={{ mt: 1 }}>
                <Chip
                  label={`${formatRate(top.lbs_per_hour)} lbs/hr`}
                  sx={{ bgcolor: "#fbbf24", color: "#0f172a", fontWeight: 800, fontSize: 16 }}
                />
                <Chip
                  label={`${formatRate(top.bags_per_hour)} bags/hr`}
                  sx={{ bgcolor: "#38bdf8", color: "#0f172a", fontWeight: 800, fontSize: 16 }}
                />
                <Chip
                  label={`${top.bag_count} bags · ${formatLbs(top.total_lbs)} lbs`}
                  sx={{ bgcolor: "rgba(255,255,255,0.2)", color: "#fff", fontWeight: 700 }}
                />
              </Stack>
            </Box>
          </Stack>
        </Paper>
      ) : (
        <Paper sx={{ mb: 4, p: 4, bgcolor: "rgba(255,255,255,0.08)", borderRadius: 3 }}>
          <Typography sx={{ fontSize: 24, fontWeight: 700, textAlign: "center" }}>
            No performance data yet — run recompute from the admin dashboard.
          </Typography>
        </Paper>
      )}

      <Grid container spacing={2} sx={{ mb: 4 }}>
        <Grid item xs={6} md={3}>
          <TvStat label="Team bags" value={team.bag_count ?? 0} accent="#fbbf24" />
        </Grid>
        <Grid item xs={6} md={3}>
          <TvStat label="Team lbs" value={formatLbs(team.total_lbs)} accent="#f472b6" />
        </Grid>
        <Grid item xs={6} md={3}>
          <TvStat label="Avg bags/hr" value={formatRate(team.bags_per_hour)} accent="#38bdf8" />
        </Grid>
        <Grid item xs={6} md={3}>
          <TvStat label="Avg lbs/hr" value={formatRate(team.lbs_per_hour)} accent="#a78bfa" />
        </Grid>
      </Grid>

      <Paper
        sx={{
          bgcolor: "rgba(15,23,42,0.6)",
          borderRadius: 3,
          overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.1)",
          mb: 4,
        }}
      >
        <Box sx={{ px: 2, py: 1.5, bgcolor: "rgba(255,255,255,0.06)" }}>
          <Grid container spacing={1} sx={{ fontWeight: 700, fontSize: 14, color: "rgba(255,255,255,0.7)" }}>
            <Grid item xs={1}>#</Grid>
            <Grid item xs={4}>Staff</Grid>
            <Grid item xs={1} textAlign="right">Bags</Grid>
            <Grid item xs={2} textAlign="right">Lbs</Grid>
            <Grid item xs={2} textAlign="right">Bags/hr</Grid>
            <Grid item xs={2} textAlign="right">Lbs/hr</Grid>
          </Grid>
        </Box>
        {users.map((u, i) => (
          <Box
            key={u.user_name}
            sx={{
              px: 2,
              py: 1.5,
              borderTop: "1px solid rgba(255,255,255,0.06)",
              bgcolor: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.03)",
            }}
          >
            <Grid container spacing={1} alignItems="center">
              <Grid item xs={1}>
                <Typography fontWeight={800} fontSize={22}>
                  {u.rank}
                </Typography>
              </Grid>
              <Grid item xs={4}>
                <Typography fontWeight={700} fontSize={{ xs: 16, md: 22 }}>
                  {u.user_name}
                </Typography>
              </Grid>
              <Grid item xs={1} textAlign="right">
                <Typography fontSize={18}>{u.bag_count}</Typography>
              </Grid>
              <Grid item xs={2} textAlign="right">
                <Typography fontSize={18}>{formatLbs(u.total_lbs)}</Typography>
              </Grid>
              <Grid item xs={2} textAlign="right">
                <Typography fontSize={18} fontWeight={600}>
                  {formatRate(u.bags_per_hour)}
                </Typography>
              </Grid>
              <Grid item xs={2} textAlign="right">
                <Stack direction="row" spacing={1} justifyContent="flex-end" alignItems="center">
                  <Typography fontSize={18} fontWeight={700} color="#fbbf24">
                    {formatRate(u.lbs_per_hour)}
                  </Typography>
                  <Chip
                    size="small"
                    label={u.target_status}
                    color={targetStatusChipColor(u.target_status)}
                    sx={{ display: { xs: "none", md: "flex" } }}
                  />
                </Stack>
              </Grid>
            </Grid>
          </Box>
        ))}
        {!users.length ? (
          <Box sx={{ p: 4, textAlign: "center" }}>
            <Typography color="rgba(255,255,255,0.6)">No ranked staff for this period.</Typography>
          </Box>
        ) : null}
      </Paper>

      <Paper
        sx={{
          p: 3,
          borderRadius: 3,
          bgcolor: "rgba(255,255,255,0.08)",
          border: "1px dashed rgba(255,255,255,0.2)",
        }}
      >
        <Typography sx={{ fontSize: 14, fontWeight: 700, color: "rgba(255,255,255,0.6)", mb: 1 }}>
          LAST WEEK WINNER
        </Typography>
        {winner?.available ? (
          <Typography sx={{ fontSize: { xs: 22, md: 28 }, fontWeight: 800 }}>
            {winner.user_name} — {formatRate(winner.lbs_per_hour)} lbs/hr ·{" "}
            {formatRate(winner.bags_per_hour)} bags/hr · {winner.bag_count} bags
          </Typography>
        ) : (
          <Typography sx={{ fontSize: 22, fontWeight: 600, color: "rgba(255,255,255,0.55)" }}>
            {winner?.message || "Not enough data yet."}
          </Typography>
        )}
        <Typography variant="caption" sx={{ color: "rgba(255,255,255,0.45)", mt: 1, display: "block" }}>
          Targets: {formatRate(bench.bags_per_hour_target)} bags/hr · {formatRate(bench.lbs_per_hour_target)}{" "}
          lbs/hr
        </Typography>
      </Paper>
    </Box>
  );
}

export default RinseFoldingTvPage;
