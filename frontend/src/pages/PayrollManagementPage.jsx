import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  approvePayrollCycle,
  getClockPayrollUiSettings,
  getPayrollCycles,
  getPayrollPeriodSettings,
  putPayrollPeriodSettings,
  submitPayrollCycleForApproval,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import ClockPayrollUiSettingsPanel from "../components/ClockPayrollUiSettingsPanel";
import AttendanceSetupPage from "./AttendanceSetupPage";
import PayrollMonitorPage from "./PayrollMonitorPage";

const WEEKDAY_LABEL_KEYS = [
  "payroll.weekMon",
  "payroll.weekTue",
  "payroll.weekWed",
  "payroll.weekThu",
  "payroll.weekFri",
  "payroll.weekSat",
  "payroll.weekSun",
];

function PayrollPeriodPanel() {
  const { t } = useI18n();
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [refPrefix, setRefPrefix] = useState("PC");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const res = await getPayrollPeriodSettings();
      const d = res.data || {};
      setWeekStartsOn(Number(d.week_starts_on) || 0);
      setRefPrefix(String(d.ref_prefix || "PC").slice(0, 16));
    } catch (e) {
      setError(e.response?.data?.error || "Failed to load payroll period settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await putPayrollPeriodSettings({
        week_starts_on: weekStartsOn,
        ref_prefix: refPrefix.trim() || "PC",
      });
      await load();
    } catch (err) {
      setError(err.response?.data?.error || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <Typography color="text.secondary" sx={{ py: 2 }}>
        {t("payroll.periodLoading")}
      </Typography>
    );
  }

  async function doSubmitBatch(id) {
    setBatchBusy(id);
    setError("");
    try {
      await submitPayrollCycleForApproval(id);
      await loadCycles();
    } catch (e) {
      setError(e.response?.data?.error || "Submit failed");
    } finally {
      setBatchBusy(null);
    }
  }

  async function doApproveBatch(id) {
    setBatchBusy(id);
    setError("");
    try {
      await approvePayrollCycle(id);
      await loadCycles();
    } catch (e) {
      setError(e.response?.data?.error || "Approve failed");
    } finally {
      setBatchBusy(null);
    }
  }

  function reviewLabel(st) {
    const s = String(st || "approved");
    if (s === "open") return t("payroll.reviewCollecting");
    if (s === "pending_approval") return t("payroll.reviewSentApproval");
    return t("payroll.reviewComplete");
  }

  function reviewColor(st) {
    const s = String(st || "");
    if (s === "open") return "info";
    if (s === "pending_approval") return "warning";
    return "success";
  }

  return (
    <Stack spacing={3} sx={{ maxWidth: 960 }}>
      <Paper sx={{ p: 2, borderRadius: 2, maxWidth: 560 }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          {t("payroll.periodTitle")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t("payroll.periodBlurb")}
        </Typography>
        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
            {error}
          </Alert>
        ) : null}
        <Stack component="form" onSubmit={save} spacing={2}>
          <FormControl size="small" fullWidth>
            <InputLabel id="ws-label">{t("payroll.weekStartsOn")}</InputLabel>
            <Select
              labelId="ws-label"
              label={t("payroll.weekStartsOn")}
              value={weekStartsOn}
              onChange={(e) => setWeekStartsOn(Number(e.target.value))}
            >
              {WEEKDAY_LABEL_KEYS.map((key, i) => (
                <MenuItem key={key} value={i}>
                  {t(key)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            size="small"
            fullWidth
            label={t("payroll.refPrefix")}
            value={refPrefix}
            onChange={(e) => setRefPrefix(e.target.value)}
            helperText={t("payroll.refPrefixHelp")}
          />
          <Button type="submit" variant="contained" disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </Button>
        </Stack>
      </Paper>

      <Paper sx={{ p: 2, borderRadius: 2, width: "100%", overflow: "auto" }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          {t("payroll.periodBatchesTitle")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t("payroll.batchWorkflowHint")}
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("payroll.colCycle")}</TableCell>
              <TableCell>{t("payroll.weekRange")}</TableCell>
              <TableCell>{t("payroll.reviewState")}</TableCell>
              <TableCell align="right">{t("payroll.batchActions")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {cycles.map((c) => {
              const st = c.review_state;
              return (
                <TableRow key={c.id}>
                  <TableCell>{c.cycle_ref}</TableCell>
                  <TableCell>
                    {c.week_start_date} – {c.week_end_date}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={reviewLabel(st)}
                      color={reviewColor(st)}
                      variant={st === "pending_approval" ? "filled" : "outlined"}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      {st === "open" ? (
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={batchBusy === c.id}
                          onClick={() => doSubmitBatch(c.id)}
                        >
                          {t("payroll.submitBatch")}
                        </Button>
                      ) : null}
                      {st === "pending_approval" ? (
                        <Button
                          size="small"
                          variant="contained"
                          disabled={batchBusy === c.id}
                          onClick={() => doApproveBatch(c.id)}
                        >
                          {t("payroll.approveBatch")}
                        </Button>
                      ) : null}
                    </Stack>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}

function PayrollManagementPage() {
  const { hasPerm, loading: authLoading, user } = useAuth();
  const { t } = useI18n();
  const rolesUpper = useMemo(() => {
    const roles = user?.roles;
    if (Array.isArray(roles) && roles.length) {
      return roles.map((r) => String(r).toUpperCase());
    }
    /** Payroll `/api/ta/auth/me` often sends `role_code` but not `roles` until backend adds it. */
    if (user?.role_code) {
      return [String(user.role_code).toUpperCase()];
    }
    return [];
  }, [user?.roles, user?.role_code]);
  const isAdminRole = useMemo(() => rolesUpper.includes("ADMIN"), [rolesUpper]);
  const isOpsRole = useMemo(() => rolesUpper.includes("OPS"), [rolesUpper]);
  const canMonitor = hasPerm("ta.monitor") || isAdminRole || isOpsRole;
  const canMaint =
    hasPerm("ta.settings") || hasPerm("users.edit") || isAdminRole;
  const canPeriod = hasPerm("ta.settings") || isAdminRole;
  const canClockUi = hasPerm("ta.settings") || isAdminRole;
  const [payrollUi, setPayrollUi] = useState(null);

  useEffect(() => {
    getClockPayrollUiSettings()
      .then((res) => setPayrollUi(res.data?.payroll || null))
      .catch(() => setPayrollUi(null));
  }, []);

  const sections = useMemo(() => {
    const p = payrollUi || {};
    const out = [];
    if (canMonitor && p.tab_live !== false) {
      out.push({ key: "live", label: t("payroll.tabLive") });
    }
    if (canMaint && p.tab_maintenance !== false) {
      out.push({ key: "maint", label: t("payroll.tabMaintenance") });
    }
    if (canPeriod && p.tab_period !== false) {
      out.push({ key: "period", label: t("payroll.tabPeriod") });
    }
    if (canClockUi && p.tab_clock_ui !== false) {
      out.push({ key: "clockui", label: t("payroll.tabClockUi") });
    }
    return out;
  }, [canMonitor, canMaint, canPeriod, canClockUi, payrollUi, t]);

  const [tab, setTab] = useState(0);

  useEffect(() => {
    if (tab >= sections.length) setTab(Math.max(0, sections.length - 1));
  }, [sections.length, tab]);

  if (authLoading) {
    return (
      <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (!sections.length) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">{t("payroll.needMgmtAccess")}</Alert>
      </Box>
    );
  }

  const active = sections[tab] || sections[0];

  return (
    <Box
      sx={{
        minHeight: "100%",
        width: "100%",
        maxWidth: "100%",
        minWidth: 0,
        p: { xs: 1.2, md: 2 },
        boxSizing: "border-box",
      }}
    >
      <Typography sx={{ fontSize: 28, fontWeight: 700, mb: 1 }}>
        {t("payroll.mgmtTitle")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 720 }}>
        {t("payroll.mgmtBlurb")}
      </Typography>

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        sx={{
          borderBottom: 1,
          borderColor: "divider",
          mb: 0,
          "& .MuiTabScrollButton-root": { width: 28 },
        }}
      >
        {sections.map((s) => (
          <Tab key={s.key} label={s.label} />
        ))}
      </Tabs>

      <Box sx={{ pt: 2, width: "100%", minWidth: 0 }} role="tabpanel">
        {active?.key === "live" ? (
          <PayrollMonitorPage embedded columnVisibility={payrollUi || {}} />
        ) : null}
        {active?.key === "maint" ? <AttendanceSetupPage embedded /> : null}
        {active?.key === "period" ? <PayrollPeriodPanel /> : null}
        {active?.key === "clockui" ? <ClockPayrollUiSettingsPanel /> : null}
      </Box>
    </Box>
  );
}

export default PayrollManagementPage;
