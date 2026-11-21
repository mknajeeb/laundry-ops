import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { getScanChronology } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { addDaysYmd, businessTodayYmd } from "../utils/businessTime";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  ACTIVITY_TYPES,
  SCAN_STAGES,
  chronologyMetrics,
  formatDurationSeconds,
  loadScanView,
  recordedSessionContext,
  saveScanView,
  scanDetailLines,
  scanEmployee,
  scanMachine,
  scanRows,
  scanTime,
  serviceTypesParam,
  userActivityRows,
} from "./pinScanModel";

function dayLabel(ymd, today, t) {
  if (ymd === today) return t("pinMgmt.today");
  if (ymd === addDaysYmd(today, -1)) return t("pinMgmt.yesterday");
  return ymd;
}

function MetricGrid({ metrics, t }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
      {metrics.map((metric) => (
        <Box
          key={metric.labelKey}
          sx={{
            p: 1.25,
            borderRadius: 2,
            border: `1px solid ${OPS_MOBILE.border}`,
            bgcolor: OPS_MOBILE.surface,
            minWidth: 0,
          }}
        >
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            {t(metric.labelKey)}
          </Typography>
          <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2 }}>
            {metric.value ?? "—"}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function RecordCard({ title, subtitle, meta, lines, open, onToggle, t }) {
  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: OPS_MOBILE.surface,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography fontWeight={800} sx={{ wordBreak: "break-word" }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
          {meta ? (
            <Typography variant="body2" sx={{ mt: 0.25 }}>
              {meta}
            </Typography>
          ) : null}
        </Box>
        <Button size="small" onClick={onToggle} sx={{ minHeight: 40, flexShrink: 0 }}>
          {open ? t("pinMgmt.collapse") : t("pinMgmt.expand")}
        </Button>
      </Stack>
      {open ? (
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          {lines.map((line) => (
            <Typography key={line.labelKey} variant="body2">
              <Box component="span" sx={{ color: OPS_MOBILE.muted }}>
                {t(line.labelKey)}:{" "}
              </Box>
              {String(line.value).startsWith("pinMgmt.") ? t(line.value) : line.value}
            </Typography>
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}

export default function PinScanChronologyFlow({ onBack, onLock, preview = null }) {
  const { t } = useI18n();
  const today = businessTodayYmd();
  const saved = useMemo(() => (preview ? null : loadScanView()), [preview]);
  const [stage, setStage] = useState(
    SCAN_STAGES.some((item) => item.id === saved?.stage) ? saved.stage : "weighing",
  );
  const [date, setDate] = useState(saved?.date && saved.date <= today ? saved.date : today);
  const [wf, setWf] = useState(saved?.wf !== false);
  const [hd, setHd] = useState(saved?.hd !== false);
  const [employee, setEmployee] = useState(saved?.employee || "");
  const [bag, setBag] = useState(saved?.bag || "");
  const [activity, setActivity] = useState(saved?.activity || "all");
  const [appliedEmployee, setAppliedEmployee] = useState(employee);
  const [appliedBag, setAppliedBag] = useState(bag);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!preview);
  const [error, setError] = useState("");
  const [openKey, setOpenKey] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setAppliedEmployee(employee.trim());
      setAppliedBag(bag.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [employee, bag]);

  useEffect(() => {
    if (preview) return;
    saveScanView({ stage, date, wf, hd, employee, bag, activity });
  }, [preview, stage, date, wf, hd, employee, bag, activity]);

  useEffect(() => {
    if (preview) {
      const next = preview[stage] || null;
      setData(next);
      setLoading(false);
      setError("");
      return undefined;
    }
    const types = serviceTypesParam(wf, hd);
    if (types === "none") {
      setData(null);
      setLoading(false);
      setError("");
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = { date_et: date, stage };
    if (types) params.service_types = types;
    if (appliedEmployee) params.employee = appliedEmployee;
    if (appliedBag) params.bag_id = appliedBag;
    if (stage === "user_activity" && activity !== "all") params.activity_type = activity;
    getScanChronology(params, { signal: controller.signal })
      .then((res) => {
        setData(res.data || null);
        setLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted || err?.code === "ERR_CANCELED" || err?.name === "CanceledError") {
          return;
        }
        setData(null);
        setError(err?.response?.data?.error || err?.message || t("pinMgmt.loadFailed"));
        setLoading(false);
      });
    return () => controller.abort();
  }, [preview, stage, date, wf, hd, appliedEmployee, appliedBag, activity, t]);

  const metrics = useMemo(() => chronologyMetrics(stage, data), [stage, data]);
  const rows = useMemo(() => scanRows(data), [data]);
  const activities = useMemo(
    () => (stage === "user_activity" ? userActivityRows(data) : []),
    [stage, data],
  );
  const sessionContext = useMemo(() => recordedSessionContext(data), [data]);

  const renderScan = (row, index, section) => {
    const key = `${section}-${row.bag_id || "bag"}-${scanTime(row, stage) || index}`;
    const when = formatFriendlyEtWall(scanTime(row, stage));
    const machine = scanMachine(row, stage);
    return (
      <RecordCard
        key={key}
        title={row.bag_id || t("pinMgmt.scanRecord")}
        subtitle={scanEmployee(row) || t("pinMgmt.noEmployee")}
        meta={[when !== "—" ? when : "", machine].filter(Boolean).join(" · ")}
        lines={scanDetailLines(row, stage).map((line) =>
          line.labelKey === "pinMgmt.start" || line.labelKey === "pinMgmt.end"
            ? { ...line, value: formatFriendlyEtWall(line.value) }
            : line,
        )}
        open={openKey === key}
        onToggle={() => setOpenKey(openKey === key ? "" : key)}
        t={t}
      />
    );
  };

  const serviceOff = !preview && serviceTypesParam(wf, hd) === "none";

  return (
    <OpsMobileShell>
      <OpsTopBar title={t("pinMgmt.scan")} onBack={onBack} onLock={onLock} />
      <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", pb: 2 }}>
        <Stack spacing={1.25} sx={{ pt: 1 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <IconButton
              aria-label={t("pinMgmt.previousDay")}
              onClick={() => setDate(addDaysYmd(date, -1))}
              sx={{ minWidth: 44, minHeight: 44 }}
            >
              <ChevronLeftIcon />
            </IconButton>
            <Box sx={{ textAlign: "center" }}>
              <Typography fontWeight={800}>{dayLabel(date, today, t)}</Typography>
              <Typography variant="caption" color="text.secondary">
                {date} ET
              </Typography>
            </Box>
            <IconButton
              aria-label={t("pinMgmt.nextDay")}
              disabled={date >= today}
              onClick={() => setDate(addDaysYmd(date, 1))}
              sx={{ minWidth: 44, minHeight: 44 }}
            >
              <ChevronRightIcon />
            </IconButton>
          </Stack>
          <Stack direction="row" spacing={1}>
            <Button variant={date === today ? "contained" : "outlined"} onClick={() => setDate(today)} sx={{ minHeight: 40 }}>
              {t("pinMgmt.today")}
            </Button>
            <Button
              variant={date === addDaysYmd(today, -1) ? "contained" : "outlined"}
              onClick={() => setDate(addDaysYmd(today, -1))}
              sx={{ minHeight: 40 }}
            >
              {t("pinMgmt.yesterday")}
            </Button>
          </Stack>
          <TextField
            type="date"
            size="small"
            value={date}
            inputProps={{ max: today, "aria-label": t("pinMgmt.pickDate") }}
            onChange={(event) => {
              const next = event.target.value;
              if (next && next <= today) setDate(next);
            }}
          />
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>
            {SCAN_STAGES.map((item) => (
              <Button
                key={item.id}
                size="small"
                variant={stage === item.id ? "contained" : "outlined"}
                onClick={() => {
                  setStage(item.id);
                  setOpenKey("");
                }}
                sx={{ minHeight: 40 }}
              >
                {t(item.labelKey)}
              </Button>
            ))}
          </Box>
          <Stack direction="row" spacing={1}>
            <Button variant={wf ? "contained" : "outlined"} onClick={() => setWf((value) => !value)} sx={{ minHeight: 40 }}>
              {t("pinMgmt.wf")}
            </Button>
            <Button variant={hd ? "contained" : "outlined"} onClick={() => setHd((value) => !value)} sx={{ minHeight: 40 }}>
              {t("pinMgmt.hd")}
            </Button>
          </Stack>
          <TextField
            size="small"
            label={t("pinMgmt.employee")}
            value={employee}
            onChange={(event) => setEmployee(event.target.value)}
          />
          <TextField
            size="small"
            label={t("pinMgmt.bag")}
            value={bag}
            onChange={(event) => setBag(event.target.value)}
          />
          {stage === "user_activity" ? (
            <TextField
              select
              size="small"
              label={t("pinMgmt.activity")}
              value={activity}
              onChange={(event) => setActivity(event.target.value)}
              SelectProps={{ native: true }}
            >
              {ACTIVITY_TYPES.map((item) => (
                <option key={item.id} value={item.id}>
                  {t(item.labelKey)}
                </option>
              ))}
            </TextField>
          ) : null}

          {serviceOff ? <Alert severity="info">{t("pinMgmt.selectService")}</Alert> : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
          {loading ? (
            <Stack alignItems="center" sx={{ py: 4 }}>
              <CircularProgress size={28} />
              <Typography variant="body2" sx={{ mt: 1 }}>
                {t("pinMgmt.loading")}
              </Typography>
            </Stack>
          ) : null}

          {!loading && !error && !serviceOff ? (
            <>
              <MetricGrid metrics={metrics} t={t} />
              {sessionContext ? (
                <Alert severity="info">
                  {t("pinMgmt.sessionContext", {
                    count: sessionContext.sessions,
                    hours: sessionContext.hours,
                  })}
                </Alert>
              ) : null}
              {stage === "user_activity" ? (
                activities.length ? (
                  activities.map((row, index) => {
                    const key = `activity-${row.employee}-${row.time_et}-${index}`;
                    return (
                      <RecordCard
                        key={key}
                        title={row.employee || t("pinMgmt.noEmployee")}
                        subtitle={row.activity_label || row.activity_type || t("pinMgmt.activity")}
                        meta={[
                          formatFriendlyEtWall(row.time_et),
                          row.bag_id,
                          row.machine_or_rack,
                        ]
                          .filter((part) => part && part !== "—")
                          .join(" · ")}
                        lines={[
                          row.duration_seconds != null
                            ? { labelKey: "pinMgmt.duration", value: formatDurationSeconds(row.duration_seconds) }
                            : null,
                          row.source ? { labelKey: "pinMgmt.source", value: row.source } : null,
                        ].filter(Boolean)}
                        open={openKey === key}
                        onToggle={() => setOpenKey(openKey === key ? "" : key)}
                        t={t}
                      />
                    );
                  })
                ) : (
                  <Alert severity="info">{t("pinMgmt.empty")}</Alert>
                )
              ) : (
                rows.length ? (
                  rows.map((row, index) => renderScan(row, index, "scan"))
                ) : (
                  <Alert severity="info">{t("pinMgmt.empty")}</Alert>
                )
              )}
            </>
          ) : null}
        </Stack>
      </Box>
    </OpsMobileShell>
  );
}
