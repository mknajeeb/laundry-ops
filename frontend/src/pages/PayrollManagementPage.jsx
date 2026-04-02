import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { getPayrollPeriodSettings, putPayrollPeriodSettings } from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
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

  return (
    <Paper sx={{ p: 2, borderRadius: 2, maxWidth: 560 }}>
      <Typography variant="subtitle1" sx={{ mb: 1 }}>
        {t("payroll.periodTitle")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb:2 }}>
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
  );
}

function PayrollManagementPage() {
  const { hasPerm, loading: authLoading } = useAuth();
  const { t } = useI18n();
  const canMonitor = hasPerm("ta.monitor");
  const canMaint = hasPerm("ta.settings") || hasPerm("users.edit");
  const canPeriod = hasPerm("ta.settings");

  const sections = useMemo(() => {
    const out = [];
    if (canMonitor) {
      out.push({ key: "live", label: t("payroll.tabLive") });
    }
    if (canMaint) {
      out.push({ key: "maint", label: t("payroll.tabMaintenance") });
    }
    if (canPeriod) {
      out.push({ key: "period", label: t("payroll.tabPeriod") });
    }
    return out;
  }, [canMonitor, canMaint, canPeriod, t]);

  const [tab, setTab] = useState(0);

  useEffect(() => {
    if (tab >= sections.length) setTab(Math.max(0, sections.length - 1));
  }, [sections.length, tab]);

  if (authLoading) {
    return null;
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
        {active?.key === "live" ? <PayrollMonitorPage embedded /> : null}
        {active?.key === "maint" ? <AttendanceSetupPage embedded /> : null}
        {active?.key === "period" ? <PayrollPeriodPanel /> : null}
      </Box>
    </Box>
  );
}

export default PayrollManagementPage;
