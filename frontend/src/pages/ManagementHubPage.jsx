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

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtLbs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} lb`;
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function fmtHours(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)} hrs`;
}

function fmtOz(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} oz`;
}

function Section({ title, accent, children }) {
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: accent || VEEWASH_DASHBOARD.snapshotBorder,
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
        <Typography sx={{ fontSize: 28, fontWeight: 800, lineHeight: 1.1, letterSpacing: -0.4 }}>
          {leftValue}
        </Typography>
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{leftLabel}</Typography>
      </Box>
      <Box>
        <Typography sx={{ fontSize: 28, fontWeight: 800, lineHeight: 1.1, letterSpacing: -0.4 }}>
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

  const wf = data?.wf || {};
  const hd = data?.hd || {};
  const labor = data?.labor || {};
  const revenue = data?.other_revenue || {};
  const review = data?.review || {};
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
            {refreshedLabel ? `Refreshed ${refreshedLabel}` : " "}
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

      <Box
        sx={{
          display: "grid",
          gap: 1.25,
          gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
        }}
      >
        <Box sx={{ gridColumn: { sm: "1 / -1" } }}>
          <Section title="Rinse — Wash & Fold" accent={VEEWASH_DASHBOARD.wfBorder}>
            <HeroPair
              leftLabel="Bags"
              leftValue={fmtInt(wf.bags)}
              rightLabel="Processed"
              rightValue={fmtLbs(wf.lbs_processed)}
            />
            <Typography sx={{ fontSize: 15, fontWeight: 700, mb: 1 }}>
              {fmtInt(wf.completed)} complete
            </Typography>
            <MetricRow
              items={[
                { label: "Specialty", value: fmtInt(wf.specialty) },
                { label: "Rejects", value: `${fmtInt(wf.rejects)} · ${fmtPct(wf.reject_pct)}` },
                { label: "Split", value: fmtPct(wf.split_pct) },
              ]}
            />
          </Section>
        </Box>

        <Section title="Rinse — Hang Dry" accent={VEEWASH_DASHBOARD.hdBorder}>
          <HeroPair
            leftLabel="Completed orders"
            leftValue={fmtInt(hd.completed_orders)}
            rightLabel="Items"
            rightValue={fmtInt(hd.items)}
          />
          <MetricRow
            items={[
              { label: "Revenue", value: fmtMoney(hd.revenue) },
              { label: "Open / in process", value: fmtInt(hd.open_in_process) },
            ]}
          />
        </Section>

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

        <Section title="Review">
          {review.split_available ? (
            <MetricRow
              items={[
                { label: "Specialty items", value: fmtInt(review.specialty_items) },
                { label: "Missing from portal", value: fmtInt(review.missing_from_portal) },
              ]}
            />
          ) : (
            <MetricRow items={[{ label: "Review required", value: fmtInt(review.review_required) }]} />
          )}
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
      </Box>
    </Box>
  );
}
