import { useCallback, useEffect, useState } from "react";
import { Box, Chip, Grid, Paper, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { getFoldingLeaderboard } from "../api";
import {
  formatComparison,
  formatFoldingHours,
  formatLbs,
  formatPeriodRange,
  formatRate,
  isoDateInput,
  targetStatusChipColor,
} from "../utils/foldingFormat";

const REFRESH_MS = 45000;
const BG = "linear-gradient(160deg, #0b1220 0%, #111827 45%, #1a1f35 100%)";

function KpiCard({ label, value, sub, accent = "#38bdf8" }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2.5,
        height: "100%",
        bgcolor: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 2,
      }}
    >
      <Typography sx={{ color: "rgba(255,255,255,0.55)", fontSize: 13, fontWeight: 600, mb: 0.5 }}>
        {label}
      </Typography>
      <Typography sx={{ color: accent, fontSize: 34, fontWeight: 800, lineHeight: 1.1 }}>{value}</Typography>
      {sub ? (
        <Typography sx={{ color: "rgba(255,255,255,0.45)", fontSize: 12, mt: 0.5 }}>{sub}</Typography>
      ) : null}
    </Paper>
  );
}

function CompareStrip({ title, team, comparison, bench }) {
  const prev = team?.available === false;
  return (
    <Paper sx={{ p: 2, bgcolor: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 2 }}>
      <Typography sx={{ color: "rgba(255,255,255,0.6)", fontSize: 12, fontWeight: 700, mb: 1 }}>
        {title}
      </Typography>
      {prev ? (
        <Typography sx={{ color: "rgba(255,255,255,0.45)", fontSize: 14 }}>Not enough data yet</Typography>
      ) : (
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          <Chip label={`Bags ${formatComparison(comparison?.bag_count)}`} sx={{ bgcolor: "rgba(255,255,255,0.08)", color: "#fff" }} />
          <Chip label={`Lbs/hr ${formatComparison(comparison?.lbs_per_hour)}`} sx={{ bgcolor: "rgba(255,255,255,0.08)", color: "#fff" }} />
          <Chip label={`Quality ${formatComparison(comparison?.issue_free_percent, { suffix: "%" })}`} sx={{ bgcolor: "rgba(255,255,255,0.08)", color: "#fff" }} />
        </Stack>
      )}
      {bench?.issue_free_percent_target != null ? (
        <Typography sx={{ color: "rgba(255,255,255,0.35)", fontSize: 11, mt: 1 }}>
          Target quality {formatRate(bench.issue_free_percent_target, 0)}%
        </Typography>
      ) : null}
    </Paper>
  );
}

function RinseFoldingTvPage({ user }) {
  const [period, setPeriod] = useState("week");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const orgLabel =
    user?.organization_name ||
    (user?.organization_slug ? String(user.organization_slug).replace(/-/g, " ") : "") ||
    "Folding";

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
  const comp = data?.team_comparison || {};
  const updated = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : "—";
  const empty = (team.bag_count || 0) === 0;

  return (
    <Box sx={{ minHeight: "100vh", background: BG, color: "#fff", p: { xs: 2, md: 4 } }}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems="flex-start" mb={3} gap={2}>
        <Box>
          <Typography sx={{ fontSize: { xs: 28, md: 40 }, fontWeight: 900, letterSpacing: -0.5 }}>
            {orgLabel} Folding Performance
          </Typography>
          <Typography sx={{ color: "rgba(255,255,255,0.65)", fontSize: 16, mt: 0.5 }}>
            {formatPeriodRange(data?.period_start, data?.period_end)}
          </Typography>
          <Typography sx={{ color: "rgba(255,255,255,0.45)", fontSize: 13, mt: 0.5 }}>
            Updated {updated} · {data?.data_source_note || "Updated after nightly upload"}
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          value={period}
          onChange={(_, v) => v && setPeriod(v)}
          sx={{
            "& .MuiToggleButton-root": {
              color: "#fff",
              borderColor: "rgba(255,255,255,0.2)",
              fontWeight: 700,
              px: 3,
              "&.Mui-selected": { bgcolor: "rgba(56,189,248,0.2)", color: "#38bdf8" },
            },
          }}
        >
          <ToggleButton value="week">This Week</ToggleButton>
          <ToggleButton value="month">This Month</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {error ? <Typography color="#fca5a5" mb={2}>{error}</Typography> : null}

      {empty ? (
        <Paper sx={{ p: 5, textAlign: "center", bgcolor: "rgba(255,255,255,0.04)", borderRadius: 2 }}>
          <Typography sx={{ fontSize: 22, fontWeight: 700 }}>
            No completed folding performance for this {period === "month" ? "month" : "week"} yet.
          </Typography>
          <Typography sx={{ color: "rgba(255,255,255,0.55)", mt: 1 }}>
            Data updates after nightly upload.
          </Typography>
        </Paper>
      ) : (
        <>
          <Grid container spacing={2} mb={2}>
            <Grid item xs={6} md={2}><KpiCard label="Bags" value={team.bag_count ?? 0} accent="#fbbf24" /></Grid>
            <Grid item xs={6} md={2}><KpiCard label="Lbs" value={formatLbs(team.total_lbs)} accent="#f472b6" /></Grid>
            <Grid item xs={6} md={2}><KpiCard label="Hours" value={formatFoldingHours(team.total_folding_seconds)} accent="#a78bfa" /></Grid>
            <Grid item xs={6} md={2}>
              <KpiCard label="Bags/hr" value={formatRate(team.bags_per_hour)} sub={formatComparison(comp.bags_per_hour)} accent="#38bdf8" />
            </Grid>
            <Grid item xs={6} md={2}>
              <KpiCard label="Lbs/hr" value={formatRate(team.lbs_per_hour)} sub={formatComparison(comp.lbs_per_hour)} accent="#34d399" />
            </Grid>
            <Grid item xs={6} md={2}>
              <KpiCard
                label="Quality"
                value={team.issue_free_percent != null ? `${formatRate(team.issue_free_percent, 1)}%` : "—"}
                sub={formatComparison(comp.issue_free_percent, { suffix: "%" })}
                accent="#fde68a"
              />
            </Grid>
          </Grid>

          <Grid container spacing={2} mb={3}>
            <Grid item xs={12} md={6}>
              <CompareStrip
                title={period === "month" ? "MONTH VS LAST MONTH" : "WEEK VS LAST WEEK"}
                team={data?.previous_team}
                comparison={comp}
                bench={bench}
              />
            </Grid>
            {top ? (
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 2.5, bgcolor: "rgba(251,191,36,0.12)", border: "1px solid rgba(251,191,36,0.35)", borderRadius: 2, height: "100%" }}>
                  <Typography sx={{ fontSize: 12, fontWeight: 700, color: "rgba(255,255,255,0.55)" }}>TOP PERFORMER</Typography>
                  <Typography sx={{ fontSize: 28, fontWeight: 800, mt: 0.5 }}>#{top.rank} {top.user_name}</Typography>
                  <Stack direction="row" spacing={1} mt={1} flexWrap="wrap" useFlexGap>
                    <Chip label={`${formatRate(top.lbs_per_hour)} lbs/hr`} sx={{ bgcolor: "#fbbf24", color: "#111", fontWeight: 800 }} />
                    <Chip label={`${formatRate(top.bags_per_hour)} bags/hr`} sx={{ bgcolor: "#38bdf8", color: "#111", fontWeight: 800 }} />
                  </Stack>
                </Paper>
              </Grid>
            ) : null}
          </Grid>

          <Grid container spacing={1.5}>
            {users.map((u) => (
              <Grid item xs={12} md={6} key={u.user_name}>
                <Paper sx={{ p: 2, bgcolor: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 2 }}>
                  <Stack direction="row" alignItems="center" spacing={2}>
                    <Typography sx={{ fontSize: 32, fontWeight: 900, minWidth: 48 }}>{u.rank}</Typography>
                    <Box flex={1}>
                      <Typography sx={{ fontSize: 20, fontWeight: 700 }}>{u.user_name}</Typography>
                      <Stack direction="row" spacing={2} flexWrap="wrap" mt={0.5}>
                        <Typography sx={{ fontSize: 14, color: "rgba(255,255,255,0.7)" }}>{u.bag_count} bags · {formatLbs(u.total_lbs)} lbs</Typography>
                        <Typography sx={{ fontSize: 14, color: "#fbbf24", fontWeight: 700 }}>{formatRate(u.lbs_per_hour)} lbs/hr</Typography>
                        <Typography sx={{ fontSize: 14, color: "rgba(255,255,255,0.7)" }}>{formatRate(u.bags_per_hour)} bags/hr</Typography>
                        {u.issue_free_percent != null ? (
                          <Typography sx={{ fontSize: 14, color: "rgba(255,255,255,0.7)" }}>{formatRate(u.issue_free_percent, 1)}% quality</Typography>
                        ) : null}
                      </Stack>
                    </Box>
                    <Chip size="small" label={u.target_status} color={targetStatusChipColor(u.target_status)} />
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        </>
      )}
    </Box>
  );
}

export default RinseFoldingTvPage;
