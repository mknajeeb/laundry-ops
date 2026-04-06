import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  forceClockOut,
  getMonitorSessions,
  getPayrollCycles,
  patchSessionPayrollLine,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { formatEasternDateTime } from "../utils/datetimeFormat";

function formatDurationSec(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return "—";
  const s = Math.max(0, Math.floor(Number(sec)));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m ${r}s`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

/** Paid net: decimal minutes (2 dp) + minutes with fractional seconds (2 dp). */
function formatNetPaid(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return "—";
  const s = Number(sec);
  const minDec = (s / 60).toFixed(2);
  const wholeMin = Math.floor(s / 60);
  const secRem = s - wholeMin * 60;
  return `${minDec} min · ${wholeMin}m ${secRem.toFixed(2)}s`;
}

function dollarsFromCents(c) {
  if (c == null || Number.isNaN(Number(c))) return "0.00";
  return (Number(c) / 100).toFixed(2);
}

function centsFromDollarString(s) {
  const n = Number.parseFloat(String(s).replace(/,/g, ""));
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 100);
}

function reviewStateLabel(st, t) {
  const s = String(st || "");
  if (s === "open") return t("payroll.reviewCollecting");
  if (s === "pending_approval") return t("payroll.reviewSentApproval");
  if (s === "approved") return t("payroll.reviewComplete");
  return s || "—";
}

function reviewStateColor(st) {
  const s = String(st || "");
  if (s === "open") return "info";
  if (s === "pending_approval") return "warning";
  if (s === "approved") return "success";
  return "info";
}

function PayrollMonitorPage({ embedded = false, columnVisibility = {} }) {
  const { hasPerm } = useAuth();
  const { t } = useI18n();
  const vis = (k) => columnVisibility[k] !== false;
  const [rows, setRows] = useState([]);
  const [cycles, setCycles] = useState([]);
  const [cycleId, setCycleId] = useState("");
  const [userId, setUserId] = useState("");
  const [error, setError] = useState("");
  const [forceOpen, setForceOpen] = useState(null);
  const [remarks, setRemarks] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [adjDraft, setAdjDraft] = useState({});

  const can = hasPerm("ta.monitor");
  const canEditLine = hasPerm("ta.settings");

  const colCount = useMemo(() => {
    const keys = [
      "monitor_col_id",
      "monitor_col_user",
      "monitor_col_cycle",
      "monitor_col_clock_in",
      "monitor_col_clock_out",
      "monitor_col_gross",
      "monitor_col_breaks",
      "monitor_col_net",
      "monitor_col_status",
      "monitor_col_geofence",
      "monitor_col_geofence_out",
      "monitor_col_bags",
      "monitor_col_period_adj",
      "monitor_col_actions",
    ];
    return keys.reduce((n, k) => (vis(k) ? n + 1 : n), 0) || 1;
  }, [vis]);

  const load = useCallback(async () => {
    if (!can) return;
    setError("");
    try {
      const params = {};
      if (cycleId) params.payroll_cycle_id = cycleId;
      if (userId) params.user_id = userId;
      const res = await getMonitorSessions(params);
      const data = res.data || [];
      setRows(data);
      const next = {};
      data.forEach((r) => {
        next[r.id] = {
          bonus: dollarsFromCents(r.period_bonus_cents),
          deduction: dollarsFromCents(r.period_deduction_cents),
          remarks: r.period_adjustment_remarks || "",
        };
      });
      setAdjDraft(next);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    }
  }, [can, cycleId, userId]);

  useEffect(() => {
    if (!can) return;
    getPayrollCycles()
      .then((r) => setCycles(r.data || []))
      .catch(() => {});
  }, [can]);

  useEffect(() => {
    const timer = setTimeout(() => {
      load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function doForce() {
    if (!remarks.trim()) return;
    try {
      await forceClockOut(forceOpen.id, remarks.trim());
      setForceOpen(null);
      setRemarks("");
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Force clock-out failed");
    }
  }

  async function savePayrollLine(row, patch) {
    if (!canEditLine) return;
    try {
      await patchSessionPayrollLine(row.id, patch);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Save failed");
    }
  }

  function onBlurAdj(row, field) {
    const d = adjDraft[row.id];
    if (!d) return;
    if (field === "remarks") {
      const next = (d.remarks || "").trim();
      if (next === (row.period_adjustment_remarks || "").trim()) return;
      savePayrollLine(row, { period_adjustment_remarks: next });
      return;
    }
    const cents = centsFromDollarString(field === "bonus" ? d.bonus : d.deduction);
    const cur =
      field === "bonus" ? row.period_bonus_cents || 0 : row.period_deduction_cents || 0;
    if (cents === Number(cur)) return;
    savePayrollLine(row, {
      [field === "bonus" ? "period_bonus_cents" : "period_deduction_cents"]: cents,
    });
  }

  if (!can) {
    return (
      <Box className={embedded ? undefined : "page"} sx={embedded ? { py: 1 } : undefined}>
        <Alert severity="info">{t("payroll.needMonitor")}</Alert>
      </Box>
    );
  }

  return (
    <Box className={embedded ? undefined : "page"}>
      {!embedded ? (
        <Typography variant="h4" className="page-title" sx={{ mb: 2 }}>
          {t("payroll.title")}
        </Typography>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {cycles.length === 0 ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t("payroll.noCycles")}
        </Alert>
      ) : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }} alignItems="center">
        {vis("monitor_show_cycle_filter") ? (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="payroll-cycle-lbl">{t("payroll.cycle")}</InputLabel>
            <Select
              labelId="payroll-cycle-lbl"
              label={t("payroll.cycle")}
              value={cycleId === null || cycleId === undefined ? "" : String(cycleId)}
              onChange={(e) => setCycleId(e.target.value)}
              displayEmpty
              renderValue={(v) => {
                if (v === "") return t("payroll.all");
                const c = cycles.find((x) => String(x.id) === String(v));
                return c ? `${c.cycle_ref} (${c.week_start_date})` : String(v);
              }}
            >
              <MenuItem value="">
                <em>{t("payroll.all")}</em>
              </MenuItem>
              {cycles.map((c) => (
                <MenuItem key={c.id} value={String(c.id)}>
                  {c.cycle_ref} ({c.week_start_date})
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ) : null}
        {vis("monitor_show_user_filter") ? (
          <TextField
            label={t("payroll.userFilter")}
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            sx={{ width: 140 }}
          />
        ) : null}
        {vis("monitor_show_apply") ? (
          <Button variant="contained" onClick={load}>
            {t("payroll.apply")}
          </Button>
        ) : null}
      </Stack>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
        {t("payroll.monitorSortHint")}
      </Typography>
      <TableContainer
        component={Paper}
        elevation={0}
        className="table-wrapper"
        sx={{
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
          background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
        }}
      >
        <Table size="small" className="orders-table" stickyHeader>
          <TableHead>
            <TableRow>
              {vis("monitor_col_id") ? <TableCell>{t("payroll.colId")}</TableCell> : null}
              {vis("monitor_col_user") ? <TableCell>{t("payroll.colUser")}</TableCell> : null}
              {vis("monitor_col_cycle") ? <TableCell>{t("payroll.colCycle")}</TableCell> : null}
              {vis("monitor_col_clock_in") ? <TableCell>{t("payroll.colClockIn")}</TableCell> : null}
              {vis("monitor_col_clock_out") ? <TableCell>{t("payroll.colClockOut")}</TableCell> : null}
              {vis("monitor_col_gross") ? <TableCell>{t("payroll.colGross")}</TableCell> : null}
              {vis("monitor_col_breaks") ? <TableCell>{t("payroll.colBreaks")}</TableCell> : null}
              {vis("monitor_col_net") ? <TableCell>{t("payroll.colNetPaid")}</TableCell> : null}
              {vis("monitor_col_status") ? <TableCell>{t("payroll.colStatus")}</TableCell> : null}
              {vis("monitor_col_geofence") ? <TableCell>{t("payroll.colGeofence")}</TableCell> : null}
              {vis("monitor_col_geofence_out") ? (
                <TableCell>{t("payroll.colGeofenceOut")}</TableCell>
              ) : null}
              {vis("monitor_col_bags") ? <TableCell>{t("payroll.colBags")}</TableCell> : null}
              {vis("monitor_col_period_adj") ? (
                <TableCell>{t("payroll.colPeriodAdj")}</TableCell>
              ) : null}
              {vis("monitor_col_actions") ? <TableCell /> : null}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r, idx) => (
              <Fragment key={r.id}>
                <TableRow
                  sx={{
                    bgcolor: idx % 2 === 0 ? "rgba(248,250,252,0.9)" : "rgba(255,255,255,0.96)",
                    "&:hover": { bgcolor: "rgba(226,232,240,0.45)" },
                  }}
                >
                  {vis("monitor_col_id") ? <TableCell>{r.id}</TableCell> : null}
                  {vis("monitor_col_user") ? (
                    <TableCell>
                      {r.first_name} {r.last_name}
                      <Typography variant="caption" display="block" color="text.secondary">
                        {r.email}
                      </Typography>
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_cycle") ? (
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {r.cycle_ref}
                      </Typography>
                      {r.payroll_cycle_review_state ? (
                        <Chip
                          size="small"
                          sx={{ mt: 0.5, fontWeight: 600 }}
                          label={reviewStateLabel(r.payroll_cycle_review_state, t)}
                          color={reviewStateColor(r.payroll_cycle_review_state)}
                          variant="outlined"
                        />
                      ) : null}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_clock_in") ? (
                    <TableCell>
                      {r.clock_in_at ? formatEasternDateTime(r.clock_in_at) : ""}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_clock_out") ? (
                    <TableCell>
                      {r.clock_out_at ? formatEasternDateTime(r.clock_out_at) : "—"}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_gross") ? (
                    <TableCell sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                      {formatDurationSec(r.gross_seconds)}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_breaks") ? (
                    <TableCell sx={{ minWidth: 200 }}>
                      <Typography variant="body2" fontWeight={600} sx={{ fontVariantNumeric: "tabular-nums" }}>
                        Σ {formatDurationSec(r.total_break_seconds_computed)}
                      </Typography>
                      {(r.breaks || []).slice(0, 3).map((b) => (
                        <Typography key={b.id} variant="caption" display="block" color="text.secondary">
                          {b.break_start_at ? formatEasternDateTime(b.break_start_at) : "—"} →{" "}
                          {b.break_end_at ? formatEasternDateTime(b.break_end_at) : "…"}
                        </Typography>
                      ))}
                      {(r.breaks || []).length > 3 ? (
                        <Typography variant="caption" color="text.secondary" display="block">
                          +{r.breaks.length - 3} more
                        </Typography>
                      ) : null}
                      {(r.breaks || []).length > 0 ? (
                        <IconButton
                          size="small"
                          aria-label="expand breaks"
                          onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                        >
                          <ExpandMoreIcon
                            fontSize="small"
                            sx={{
                              transform: expandedId === r.id ? "rotate(180deg)" : "none",
                              transition: "transform 0.2s",
                            }}
                          />
                        </IconButton>
                      ) : null}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_net") ? (
                    <TableCell sx={{ minWidth: 168, fontVariantNumeric: "tabular-nums" }}>
                      {formatNetPaid(r.paid_net_seconds ?? r.net_work_seconds)}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_status") ? <TableCell>{r.status}</TableCell> : null}
                  {vis("monitor_col_geofence") ? <TableCell>{r.geofence_name}</TableCell> : null}
                  {vis("monitor_col_geofence_out") ? (
                    <TableCell sx={{ minWidth: 176 }}>
                      <Typography variant="body2" fontWeight={600}>
                        {formatDurationSec(r.geofence_outside?.total_seconds)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t("payroll.geoDeducted")}: {formatDurationSec(r.geofence_outside?.deducted_seconds)}
                      </Typography>
                      {r.geofence_outside?.first_exception_at ? (
                        <Typography variant="caption" display="block" color="text.secondary">
                          {formatEasternDateTime(r.geofence_outside.first_exception_at)} →{" "}
                          {r.geofence_outside.last_exception_at
                            ? formatEasternDateTime(r.geofence_outside.last_exception_at)
                            : "—"}
                        </Typography>
                      ) : (
                        <Typography variant="caption" display="block" color="text.secondary">
                          {t("payroll.geoAggregatedNote")}
                        </Typography>
                      )}
                      {canEditLine ? (
                        <FormControlLabel
                          control={
                            <Checkbox
                              size="small"
                              checked={!!r.geofence_outside?.deduction_excluded}
                              onChange={(e) =>
                                savePayrollLine(r, {
                                  geofence_outside_deduction_excluded: e.target.checked,
                                })
                              }
                            />
                          }
                          label={t("payroll.geoExcludeDeduct")}
                        />
                      ) : (
                        <Typography variant="caption" display="block">
                          {r.geofence_outside?.deduction_excluded
                            ? t("payroll.geoExcludedY")
                            : t("payroll.geoExcludedN")}
                        </Typography>
                      )}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_bags") ? (
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {r.personal_laundry_bags ?? 0}
                      </Typography>
                      <Typography variant="caption" display="block" color="text.secondary">
                        {t("payroll.bagDeduct")}: ${dollarsFromCents(r.laundry_bag_deduction_cents)}
                      </Typography>
                      {canEditLine ? (
                        <FormControlLabel
                          control={
                            <Checkbox
                              size="small"
                              checked={!!r.laundry_bag_deduction_excluded}
                              onChange={(e) =>
                                savePayrollLine(r, {
                                  laundry_bag_deduction_excluded: e.target.checked,
                                })
                              }
                            />
                          }
                          label={t("payroll.bagExcludeDeduct")}
                        />
                      ) : null}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_period_adj") ? (
                    <TableCell sx={{ minWidth: 220 }}>
                      {canEditLine ? (
                        <Stack spacing={1}>
                          <TextField
                            size="small"
                            label={t("payroll.periodBonus")}
                            value={adjDraft[r.id]?.bonus ?? ""}
                            onChange={(e) =>
                              setAdjDraft((p) => ({
                                ...p,
                                [r.id]: { ...p[r.id], bonus: e.target.value },
                              }))
                            }
                            onBlur={() => onBlurAdj(r, "bonus")}
                          />
                          <TextField
                            size="small"
                            label={t("payroll.periodDeduction")}
                            value={adjDraft[r.id]?.deduction ?? ""}
                            onChange={(e) =>
                              setAdjDraft((p) => ({
                                ...p,
                                [r.id]: { ...p[r.id], deduction: e.target.value },
                              }))
                            }
                            onBlur={() => onBlurAdj(r, "deduction")}
                          />
                          <TextField
                            size="small"
                            label={t("payroll.periodRemarks")}
                            multiline
                            minRows={2}
                            value={adjDraft[r.id]?.remarks ?? ""}
                            onChange={(e) =>
                              setAdjDraft((p) => ({
                                ...p,
                                [r.id]: { ...p[r.id], remarks: e.target.value },
                              }))
                            }
                            onBlur={() => onBlurAdj(r, "remarks")}
                          />
                        </Stack>
                      ) : (
                        <Stack spacing={0.5}>
                          <Typography variant="body2">
                            +${dollarsFromCents(r.period_bonus_cents)} / −$
                            {dollarsFromCents(r.period_deduction_cents)}
                          </Typography>
                          {r.period_adjustment_remarks ? (
                            <Typography variant="caption" color="text.secondary">
                              {r.period_adjustment_remarks}
                            </Typography>
                          ) : null}
                        </Stack>
                      )}
                    </TableCell>
                  ) : null}
                  {vis("monitor_col_actions") ? (
                    <TableCell>
                      {r.status === "active" && hasPerm("ta.override") ? (
                        <Button size="small" onClick={() => setForceOpen(r)}>
                          {t("payroll.forceOut")}
                        </Button>
                      ) : null}
                    </TableCell>
                  ) : null}
                </TableRow>
                {vis("monitor_col_breaks") ? (
                  <TableRow key={`${r.id}-brk`}>
                    <TableCell sx={{ py: 0, border: 0 }} colSpan={colCount}>
                      <Collapse in={expandedId === r.id} timeout="auto" unmountOnExit>
                        <Box sx={{ py: 1, pl: 2 }}>
                          <Typography variant="subtitle2" sx={{ mb: 1 }}>
                            {t("payroll.breakDetail")}
                          </Typography>
                          {(r.breaks || []).length === 0 ? (
                            <Typography variant="body2" color="text.secondary">
                              —
                            </Typography>
                          ) : (
                            (r.breaks || []).map((b) => (
                              <Typography key={b.id} variant="body2" display="block">
                                {b.break_start_at ? formatEasternDateTime(b.break_start_at) : "—"} →{" "}
                                {b.break_end_at ? formatEasternDateTime(b.break_end_at) : t("payroll.breakOpen")}{" "}
                                ({formatDurationSec(b.duration_seconds)})
                              </Typography>
                            ))
                          )}
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={!!forceOpen} onClose={() => setForceOpen(null)}>
        <DialogTitle>{t("payroll.forceTitle")}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            multiline
            minRows={2}
            label={t("payroll.forceRemarks")}
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForceOpen(null)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={doForce} disabled={!remarks.trim()}>
            {t("payroll.confirm")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default PayrollMonitorPage;
