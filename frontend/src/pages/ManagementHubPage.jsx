import { useCallback, useEffect, useMemo, useState } from "react";
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
import { getManagementToday } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import ManagementTodayRinseSection from "../components/management/ManagementTodayRinseSection";
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

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtHours(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)} hrs`;
}

function fmtOz(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} oz`;
}

function Section({ title, children }) {
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: "#fff",
      }}
    >
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          color: "#64748b",
          mb: 1,
        }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function HeroPair({ leftLabel, leftValue, rightLabel, rightValue }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, mb: 1 }}>
      <Box>
        <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1, letterSpacing: -0.3 }}>
          {leftValue}
        </Typography>
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{leftLabel}</Typography>
      </Box>
      <Box>
        <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1, letterSpacing: -0.3 }}>
          {rightValue}
        </Typography>
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{rightLabel}</Typography>
      </Box>
    </Box>
  );
}

function MetricRow({ items }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, minmax(0, 1fr))`,
        gap: 0.75,
      }}
    >
      {items.map((item) => (
        <Box key={item.label}>
          <Typography sx={{ fontSize: 16, fontWeight: 800, lineHeight: 1.2 }}>{item.value}</Typography>
          <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>{item.label}</Typography>
        </Box>
      ))}
    </Box>
  );
}

export default function ManagementHubPage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (day, refresh = false) => {
    if (!refresh) setData(null);
    setLoading(true);
    setError("");
    try {
      const res = await getManagementToday(day, { refresh: refresh ? 1 : undefined });
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load Today");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(dateEt, false);
  }, [dateEt, load]);

  const refreshedLabel = useMemo(() => {
    if (!data?.generated_at_et) return "";
    return formatFriendlyEtWall(data.generated_at_et);
  }, [data?.generated_at_et]);

  const labor = data?.labor || {};
  const revenue = data?.other_revenue || {};
  const supplies = data?.supplies || {};

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
      <ManagementHubNav activeId="today" />

      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 1.5, mb: 1 }} spacing={1}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>Today</Typography>
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
            disabled={loading}
            size="small"
          >
            {loading ? <CircularProgress size={18} /> : <RefreshIcon />}
          </IconButton>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

      <Box sx={{ display: "grid", gap: 1.25 }}>
        {data ? (
          <ManagementTodayRinseSection
            rinse={data.rinse || null}
            lbsProcessed={data?.wf?.lbs_processed}
            selectedDateEt={dateEt}
            onRefresh={() => load(dateEt, true)}
          />
        ) : loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}>
            <CircularProgress size={22} />
          </Box>
        ) : null}

        {data ? (
          <>
        <Section title="Labor">
          <HeroPair
            leftLabel="Hours"
            leftValue={fmtHours(labor.total_hours)}
            rightLabel="Labor $"
            rightValue={fmtMoney(labor.total_dollars)}
          />
          <MetricRow
            items={[
              { label: "WF", value: fmtHours(labor.rinse_wf_hours) },
              { label: "HD", value: fmtHours(labor.rinse_hd_hours) },
              { label: "Drop Off", value: fmtHours(labor.drop_off_hours) },
              { label: "DHS", value: fmtHours(labor.dhs_hours) },
            ]}
          />
        </Section>

        <Section title="Other revenue">
          <MetricRow
            items={[
              { label: "Self Service", value: fmtMoney(revenue.self_service) },
              { label: "Drop Off", value: fmtMoney(revenue.drop_off) },
              { label: "DHS", value: fmtMoney(revenue.dhs) },
            ]}
          />
        </Section>

        <Section title="Supplies">
          <MetricRow
            items={[
              { label: "Tide", value: fmtOz(supplies.Tide?.ounces) },
              { label: "Downy", value: fmtOz(supplies.Downy?.ounces) },
              { label: "Oxi", value: fmtOz(supplies.OxiClean?.ounces) },
              { label: "All Free", value: fmtOz(supplies["All Free & Clear"]?.ounces) },
            ]}
          />
        </Section>
          </>
        ) : null}
      </Box>
    </Box>
  );
}
