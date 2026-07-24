import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link as MuiLink,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { getDailyOperationsCompareFinance, getDailyOperationsDay, getDailyOperationsMeta } from "../api";
import WfReviewPanel from "../components/dailyOps/WfReviewPanel";
import HdProductionPanel from "../components/dailyOps/HdProductionPanel";

function money(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function lbs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 })} lb`;
}

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

export default function DailyOperationsPage() {
  const [dateEt, setDateEt] = useState(todayEtIso());
  const [meta, setMeta] = useState(null);
  const [day, setDay] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [compare, setCompare] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);

  const load = useCallback(async (d) => {
    setLoading(true);
    setError("");
    setCompare(null);
    try {
      const [m, payload] = await Promise.all([
        getDailyOperationsMeta().then((r) => r.data),
        getDailyOperationsDay(d).then((r) => r.data),
      ]);
      setMeta(m);
      setDay(payload);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load Daily Operations");
      setDay(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCompare = useCallback(async () => {
    setCompareLoading(true);
    setError("");
    try {
      const payload = (await getDailyOperationsCompareFinance(dateEt)).data;
      setCompare(payload);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load Finance comparison");
      setCompare(null);
    } finally {
      setCompareLoading(false);
    }
  }, [dateEt]);

  useEffect(() => {
    load(dateEt);
  }, [dateEt, load]);

  const kpis = day?.kpis || {};
  const revenue = day?.revenue || {};
  const included = day?.drilldowns?.included_wf_bags || [];
  const missing = day?.drilldowns?.missing_post_weight_bags || [];

  const statusTone = useMemo(() => {
    if (!day?.available) return "default";
    if (revenue.pricing_incomplete) return "warning";
    return "success";
  }, [day, revenue.pricing_incomplete]);

  return (
    <Box className="page" sx={{ maxWidth: 960, mx: "auto", width: "100%", px: { xs: 1.5, sm: 2 }, pb: 4 }}>
      <Stack spacing={0.5} sx={{ mb: 2 }}>
        <Typography variant="h5" fontWeight={800} sx={{ fontSize: { xs: "1.35rem", sm: "1.5rem" } }}>
          Daily Operations
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Phase 1C — WF revenue, unified WF review, and HD production. Labor and close come later.
        </Typography>
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
          <TextField
            label="Operations date (ET)"
            type="date"
            size="small"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 190 }}
          />
          <Chip
            size="small"
            color={statusTone}
            label={day?.available ? `Status: ${day?.status || "OPEN"}` : day?.status || "UNAVAILABLE"}
          />
          <Button size="small" variant="outlined" onClick={() => load(dateEt)} disabled={loading}>
            Refresh
          </Button>
          {day?.available ? (
            <Button size="small" variant="contained" onClick={loadCompare} disabled={compareLoading || loading}>
              {compareLoading ? "Reconciling…" : "Finance pound reconciliation"}
            </Button>
          ) : null}
          {loading ? <CircularProgress size={20} /> : null}
        </Stack>
      </Paper>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}

      {day && !day.available ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {day.message || meta?.message || "Daily Operations tracking started July 23, 2026."}
        </Alert>
      ) : null}

      {day?.available ? (
        <>
          {revenue.pricing_incomplete ? (
            <Alert severity="warning" sx={{ mb: 2 }}>
              Pricing incomplete for this date — no effective WF rate schedule. Weight revenue is not calculated.
              Jul 23–31 do not use the Aug 1, 2026 schedule.
            </Alert>
          ) : null}

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" },
              gap: 1.5,
              mb: 2,
            }}
          >
            {[
              ["WF Completed Pounds", lbs(kpis.wf_completed_pounds)],
              ["WF Weight Revenue", money(kpis.wf_weight_revenue)],
              ["WF Work-Item Revenue", money(kpis.wf_workitem_revenue)],
              ["HD Revenue (Complete)", money(kpis.hd_revenue)],
              ["Total Revenue", money(kpis.total_revenue)],
              ["Missing POST Weights", String(kpis.missing_post_weights ?? 0)],
              ["Outstanding WF Reviews", String(kpis.outstanding_wf_workitem_reviews ?? 0)],
              ["HD Not Recorded", String(kpis.hd_not_recorded ?? 0)],
            ].map(([label, value]) => (
              <Paper key={label} variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="caption" color="text.secondary">
                  {label}
                </Typography>
                <Typography variant="h6" fontWeight={700} sx={{ mt: 0.25, fontSize: { xs: "1rem", sm: "1.15rem" } }}>
                  {value}
                </Typography>
              </Paper>
            ))}
          </Box>

          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
              Revenue — Wash & Fold
            </Typography>
            <Stack spacing={0.75}>
              <Row label="WF Completed Pounds" value={lbs(revenue.wf_completed_pounds)} />
              <Row label="MTD pounds before day" value={lbs(revenue.mtd_pounds_before)} />
              <Row label="Tier 1 pounds today" value={lbs(revenue.tier1_pounds_today)} />
              <Row label="Tier 2 pounds today" value={lbs(revenue.tier2_pounds_today)} />
              <Row label="Tier 1 revenue today" value={money(revenue.tier1_revenue_today)} />
              <Row label="Tier 2 revenue today" value={money(revenue.tier2_revenue_today)} />
              <Divider />
              <Row label="WF Weight Revenue" value={money(revenue.wf_weight_revenue)} />
              <Row label="WF Work-Item Revenue" value={money(revenue.wf_workitem_revenue)} />
              <Row label="HD Revenue (Complete)" value={money(revenue.hd_revenue)} />
              {revenue.partial_hd_revenue_entered ? (
                <Row
                  label="Partial HD Revenue Entered (excluded)"
                  value={money(revenue.partial_hd_revenue_entered)}
                />
              ) : null}
              <Divider />
              <Row label="Total Revenue" value={money(revenue.total_revenue)} strong />
              <Row label="MTD pounds after day" value={lbs(revenue.mtd_pounds_after)} />
            </Stack>

            {Array.isArray(revenue.applied_tiers) && revenue.applied_tiers.length > 0 ? (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
                  Tier breakdown
                </Typography>
                {revenue.applied_tiers.map((t) => (
                  <Typography key={`${t.tier_number}-${t.rate_per_lb}`} variant="body2" color="text.secondary">
                    Tier {t.tier_number}: {lbs(t.pounds_applied)} × ${Number(t.rate_per_lb).toFixed(2)} ={" "}
                    {money(t.tier_revenue)}
                  </Typography>
                ))}
              </Box>
            ) : null}

            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" fontWeight={700}>
                Pricing schedule
              </Typography>
              {revenue.pricing_schedule ? (
                <Typography variant="body2" color="text.secondary">
                  #{revenue.pricing_schedule.id} {revenue.pricing_schedule.name || ""} · effective{" "}
                  {revenue.pricing_schedule.effective_from}
                  {revenue.pricing_schedule.effective_to ? ` → ${revenue.pricing_schedule.effective_to}` : " → open"}
                </Typography>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No effective schedule for this date.
                </Typography>
              )}
            </Box>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
              Maintenance
            </Typography>
            <Stack spacing={0.5}>
              <MuiLink component={RouterLink} to="/performance/settings">
                Work-item maintenance (existing)
              </MuiLink>
              <MuiLink component={RouterLink} to="/finance/daily-revenue-cost">
                WF rate maintenance / Finance DRC (existing)
              </MuiLink>
              <MuiLink component={RouterLink} to="/performance">
                Shift Monitor (comparison)
              </MuiLink>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              Labor / HD / combined profitability: Coming in later phase
            </Typography>
          </Paper>

          <WfReviewPanel dateEt={dateEt} onSaved={() => load(dateEt)} />
          <HdProductionPanel dateEt={dateEt} onSaved={() => load(dateEt)} />

          <DrillTable title={`Included WF bags (${included.length})`} rows={included} missing={false} />
          <DrillTable title={`Missing POST weight (${missing.length})`} rows={missing} missing />

          {compare?.pound_reconciliation ? (
            <PoundReconciliationPanel reconciliation={compare.pound_reconciliation} />
          ) : null}
        </>
      ) : null}
    </Box>
  );
}

function PoundReconciliationPanel({ reconciliation: rec }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
        Finance → Daily Operations pound reconciliation
      </Typography>
      <Stack spacing={0.75} sx={{ mb: 1.5 }}>
        <Row label="Finance Suggested Pounds" value={lbs(rec.finance_suggested_pounds)} strong />
      </Stack>
      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
        Excluded
      </Typography>
      <Stack spacing={0.5} sx={{ mb: 1.5 }}>
        {(rec.excluded || []).map((row) => (
          <Row
            key={row.reason}
            label={`${row.label} (${row.bag_count})`}
            value={lbs(row.pounds)}
          />
        ))}
        <Divider />
        <Row label="Excluded total" value={lbs(rec.excluded_pounds_total)} strong />
      </Stack>
      <Stack spacing={0.75}>
        <Row
          label="Included from Finance (at Finance weights)"
          value={lbs(rec.included_from_finance?.finance_pounds)}
        />
        <Row
          label="Only in Daily Operations"
          value={lbs(rec.only_in_daily_operations?.pounds)}
        />
        <Divider />
        <Row label="Daily Operations Eligible Pounds" value={lbs(rec.daily_operations_eligible_pounds)} strong />
      </Stack>
      {!rec.identity?.finance_equals_included_plus_excluded ? (
        <Alert severity="error" sx={{ mt: 1.5 }}>
          Identity check failed: Finance pounds do not equal included + excluded.
        </Alert>
      ) : (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
          Identity OK — every Finance pound is included or excluded once. Each excluded bag has exactly one
          reason.
        </Typography>
      )}
      {(rec.excluded || [])
        .filter((r) => r.bag_count > 0)
        .map((r) => (
          <Box key={`bags-${r.reason}`} sx={{ mt: 2, overflowX: "auto" }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
              {r.label} — bags
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Bag</TableCell>
                  <TableCell align="right">Finance lb</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Completion</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(r.bags || []).slice(0, 200).map((b) => (
                  <TableRow key={b.bag_id}>
                    <TableCell>{b.bag_id}</TableCell>
                    <TableCell align="right">
                      {b.finance_weight_lbs == null ? "—" : Number(b.finance_weight_lbs).toFixed(2)}
                    </TableCell>
                    <TableCell>{b.service_type || "—"}</TableCell>
                    <TableCell>{b.canonical_completion_status || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        ))}
    </Paper>
  );
}

function Row({ label, value, strong }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={strong ? 700 : 500}>
        {value}
      </Typography>
    </Stack>
  );
}

function DrillTable({ title, rows, missing }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2, overflowX: "auto" }}>
      <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
        {title}
      </Typography>
      {!rows.length ? (
        <Typography variant="body2" color="text.secondary">
          None
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Bag</TableCell>
              <TableCell align="right">POST lb</TableCell>
              <TableCell>Source</TableCell>
              <TableCell>Completion</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.slice(0, 200).map((r) => (
              <TableRow key={r.bag_id} sx={missing ? { bgcolor: "action.hover" } : undefined}>
                <TableCell>{r.bag_id}</TableCell>
                <TableCell align="right">
                  {r.post_weight_lbs == null ? "—" : Number(r.post_weight_lbs).toFixed(2)}
                  {r.reviewable_zero ? " (zero)" : ""}
                </TableCell>
                <TableCell>{r.post_weight_source || "—"}</TableCell>
                <TableCell>{r.canonical_completion_status || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}
