import { useCallback, useEffect, useState } from "react";
import { Box, Chip, Grid, Paper, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { getFoldingLeaderboard } from "../api";
import {
  comparisonArrow,
  formatComparison,
  formatFoldingHours,
  formatLbs,
  formatPeriodRange,
  formatRate,
  isoDateInput,
  targetStatusChipColor,
} from "../utils/foldingFormat";

const REFRESH_MS = 45000;

const VW = {
  blue: "#0072CE",
  blueDeep: "#004C97",
  aqua: "#00C9B7",
  aquaLight: "#5CE1D6",
  white: "#FFFFFF",
  cream: "#F0FAFF",
  gold: "#FFB81C",
  textMuted: "rgba(255,255,255,0.72)",
};

const BG = `linear-gradient(145deg, ${VW.blueDeep} 0%, ${VW.blue} 38%, #0096D6 62%, ${VW.aqua} 100%)`;

function TrendPill({ label, comp, suffix = "" }) {
  const dir = comp?.direction || "flat";
  const color = dir === "up" ? VW.aquaLight : dir === "down" ? "#FCA5A5" : VW.textMuted;
  return (
    <Box
      sx={{
        px: 2,
        py: 1.25,
        borderRadius: 3,
        bgcolor: "rgba(255,255,255,0.12)",
        border: "1px solid rgba(255,255,255,0.22)",
        minWidth: 140,
      }}
    >
      <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.2, color: VW.textMuted, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 22, fontWeight: 900, color: VW.white, mt: 0.25 }}>
        {formatComparison(comp, { suffix })}
        <Box component="span" sx={{ ml: 0.75, fontSize: 28, color }}>
          {comparisonArrow(dir)}
        </Box>
      </Typography>
    </Box>
  );
}

function HeroKpi({ label, value, sub, accent = VW.white }) {
  return (
    <Paper
      elevation={8}
      sx={{
        p: 2.5,
        height: "100%",
        borderRadius: 4,
        background: `linear-gradient(160deg, rgba(255,255,255,0.95) 0%, rgba(240,250,255,0.88) 100%)`,
        border: `2px solid ${VW.aquaLight}`,
        boxShadow: "0 12px 40px rgba(0,76,151,0.35)",
      }}
    >
      <Typography sx={{ color: VW.blueDeep, fontSize: 13, fontWeight: 800, letterSpacing: 0.6, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ color: accent, fontSize: { xs: 36, md: 48 }, fontWeight: 900, lineHeight: 1.05, mt: 0.5 }}>
        {value}
      </Typography>
      {sub ? (
        <Typography sx={{ color: VW.blue, fontSize: 14, fontWeight: 700, mt: 0.75 }}>{sub}</Typography>
      ) : null}
    </Paper>
  );
}

function RankCard({ user, rank, isTop }) {
  return (
    <Paper
      elevation={isTop ? 12 : 4}
      sx={{
        p: { xs: 2, md: 2.5 },
        borderRadius: 4,
        background: isTop
          ? `linear-gradient(135deg, ${VW.gold} 0%, #FFE08A 45%, rgba(255,255,255,0.95) 100%)`
          : "rgba(255,255,255,0.92)",
        border: isTop ? `3px solid ${VW.gold}` : "2px solid rgba(255,255,255,0.5)",
        boxShadow: isTop ? "0 16px 48px rgba(0,0,0,0.25)" : "0 8px 24px rgba(0,76,151,0.2)",
        transform: isTop ? "scale(1.02)" : "none",
      }}
    >
      <Stack direction="row" spacing={2} alignItems="center">
        <Box
          sx={{
            width: 56,
            height: 56,
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 900,
            fontSize: 26,
            color: isTop ? VW.blueDeep : VW.white,
            bgcolor: isTop ? VW.white : VW.blue,
            border: `3px solid ${isTop ? VW.gold : VW.aqua}`,
          }}
        >
          {rank}
        </Box>
        <Box flex={1} minWidth={0}>
          <Typography
            sx={{
              fontSize: { xs: 20, md: 24 },
              fontWeight: 900,
              color: VW.blueDeep,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {user.user_name}
          </Typography>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
            <Typography sx={{ fontSize: 16, fontWeight: 800, color: VW.blue }}>
              {formatRate(user.lbs_per_hour)} lbs/hr
            </Typography>
            <Typography sx={{ fontSize: 16, fontWeight: 700, color: VW.blueDeep }}>
              {formatRate(user.bags_per_hour)} bags/hr
            </Typography>
            <Typography sx={{ fontSize: 15, color: "rgba(0,76,151,0.75)" }}>
              {user.bag_count} bags · {formatLbs(user.total_lbs)} lbs
            </Typography>
          </Stack>
          {user.issue_free_percent != null ? (
            <Typography sx={{ fontSize: 14, fontWeight: 700, color: VW.aqua, mt: 0.5 }}>
              Quality {formatRate(user.issue_free_percent, 1)}%
              {user.comparison?.issue_free_percent?.available
                ? ` ${comparisonArrow(user.comparison.issue_free_percent.direction)} vs prior`
                : ""}
            </Typography>
          ) : null}
        </Box>
        <Chip
          label={user.target_status}
          color={targetStatusChipColor(user.target_status)}
          sx={{ fontWeight: 800, fontSize: 13, height: 36, display: { xs: "none", sm: "flex" } }}
        />
      </Stack>
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
    "Team";

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
  const periodTitle = period === "month" ? "This Month" : "This Week";
  const vsTitle = period === "month" ? "vs Last Month" : "vs Last Week";

  return (
    <Box
      sx={{
        minHeight: "100vh",
        background: BG,
        color: VW.white,
        p: { xs: 2, md: 4 },
        boxSizing: "border-box",
      }}
    >
      <Stack direction={{ xs: "column", lg: "row" }} justifyContent="space-between" alignItems="flex-start" mb={3} gap={2}>
        <Box>
          <Typography
            sx={{
              fontSize: { xs: 32, md: 52 },
              fontWeight: 900,
              letterSpacing: -1,
              textShadow: "0 4px 24px rgba(0,0,0,0.25)",
              lineHeight: 1.05,
            }}
          >
            {orgLabel}
          </Typography>
          <Typography sx={{ fontSize: { xs: 22, md: 32 }, fontWeight: 800, color: VW.aquaLight, mt: 0.25 }}>
            Folding Performance
          </Typography>
          <Typography sx={{ color: VW.textMuted, fontSize: 18, mt: 1, fontWeight: 600 }}>
            {periodTitle} · {formatPeriodRange(data?.period_start, data?.period_end)}
          </Typography>
          <Typography sx={{ color: "rgba(255,255,255,0.5)", fontSize: 14, mt: 0.5 }}>
            Updated {updated} · {data?.data_source_note || "Live scoreboard"}
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          value={period}
          onChange={(_, v) => v && setPeriod(v)}
          sx={{
            bgcolor: "rgba(255,255,255,0.15)",
            borderRadius: 3,
            p: 0.5,
            "& .MuiToggleButton-root": {
              color: VW.white,
              border: "none",
              fontWeight: 800,
              fontSize: 16,
              px: 4,
              py: 1.25,
              borderRadius: "12px !important",
              "&.Mui-selected": {
                bgcolor: VW.white,
                color: VW.blueDeep,
                boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
              },
            },
          }}
        >
          <ToggleButton value="week">Week</ToggleButton>
          <ToggleButton value="month">Month</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {error ? (
        <Paper sx={{ p: 2, mb: 2, bgcolor: "rgba(254,226,226,0.95)", color: "#991B1B", borderRadius: 3 }}>
          {error}
        </Paper>
      ) : null}

      {empty ? (
        <Paper
          sx={{
            p: 6,
            textAlign: "center",
            borderRadius: 4,
            background: "rgba(255,255,255,0.92)",
            border: `3px dashed ${VW.aqua}`,
            boxShadow: "0 12px 40px rgba(0,76,151,0.25)",
          }}
        >
          <Typography sx={{ fontSize: 36, fontWeight: 900, color: VW.blueDeep }}>
            Waiting for confirmed folding data
          </Typography>
          <Typography sx={{ color: VW.blue, fontSize: 20, mt: 2, maxWidth: 560, mx: "auto", fontWeight: 600 }}>
            No completed bags in this {period === "month" ? "month" : "week"} yet. Performance updates after you confirm an upload batch.
          </Typography>
          <Typography sx={{ color: "rgba(0,76,151,0.55)", fontSize: 16, mt: 2 }}>
            Targets: {formatRate(bench.bags_per_hour_target)} bags/hr · {formatRate(bench.lbs_per_hour_target)} lbs/hr · {formatRate(bench.issue_free_percent_target, 0)}% quality
          </Typography>
        </Paper>
      ) : (
        <>
          <Grid container spacing={2} mb={3}>
            <Grid item xs={6} md={2}>
              <HeroKpi label="Bags Folded" value={team.bag_count ?? 0} accent={VW.blueDeep} />
            </Grid>
            <Grid item xs={6} md={2}>
              <HeroKpi label="Total Lbs" value={formatLbs(team.total_lbs)} accent={VW.blue} />
            </Grid>
            <Grid item xs={6} md={2}>
              <HeroKpi label="Folding Hours" value={formatFoldingHours(team.total_folding_seconds)} accent={VW.blueDeep} />
            </Grid>
            <Grid item xs={6} md={2}>
              <HeroKpi
                label="Bags / Hour"
                value={formatRate(team.bags_per_hour)}
                sub={`Target ${formatRate(bench.bags_per_hour_target)}`}
                accent={VW.aqua}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <HeroKpi
                label="Lbs / Hour"
                value={formatRate(team.lbs_per_hour)}
                sub={`Target ${formatRate(bench.lbs_per_hour_target)}`}
                accent={VW.blue}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <HeroKpi
                label="Quality"
                value={team.issue_free_percent != null ? `${formatRate(team.issue_free_percent, 1)}%` : "—"}
                sub={
                  team.issue_count != null
                    ? `${team.issue_count} issues · target ${formatRate(bench.issue_free_percent_target, 0)}%`
                    : `Target ${formatRate(bench.issue_free_percent_target, 0)}%`
                }
                accent={VW.blueDeep}
              />
            </Grid>
          </Grid>

          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap mb={3}>
            <TrendPill label={`Bags ${vsTitle}`} comp={comp.bag_count} />
            <TrendPill label={`Lbs/hr ${vsTitle}`} comp={comp.lbs_per_hour} />
            <TrendPill label={`Bags/hr ${vsTitle}`} comp={comp.bags_per_hour} />
            <TrendPill label={`Quality ${vsTitle}`} comp={comp.issue_free_percent} suffix="%" />
          </Stack>

          {top ? (
            <Box mb={3}>
              <Typography sx={{ fontSize: 14, fontWeight: 800, letterSpacing: 2, color: VW.gold, mb: 1.5, textTransform: "uppercase" }}>
                Top Performer
              </Typography>
              <RankCard user={top} rank={top.rank} isTop />
            </Box>
          ) : null}

          <Typography sx={{ fontSize: 14, fontWeight: 800, letterSpacing: 2, color: VW.textMuted, mb: 1.5, textTransform: "uppercase" }}>
            Leaderboard
          </Typography>
          <Grid container spacing={2}>
            {users.slice(top ? 1 : 0).map((u) => (
              <Grid item xs={12} md={6} key={u.user_name}>
                <RankCard user={u} rank={u.rank} isTop={false} />
              </Grid>
            ))}
          </Grid>
        </>
      )}
    </Box>
  );
}

export default RinseFoldingTvPage;
