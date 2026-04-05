import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  forceClockOut,
  getMonitorSessions,
  getPayrollCycles,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { formatEasternDateTime } from "../utils/datetimeFormat";

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

  const can = hasPerm("ta.monitor");

  const load = useCallback(async () => {
    if (!can) return;
    setError("");
    try {
      const params = {};
      if (cycleId) params.payroll_cycle_id = cycleId;
      if (userId) params.user_id = userId;
      const res = await getMonitorSessions(params);
      setRows(res.data || []);
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
    const t = setTimeout(() => {
      load();
    }, 0);
    return () => clearTimeout(t);
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

      <Box className="table-wrapper">
        <Table size="small" className="orders-table">
          <TableHead>
            <TableRow>
              {vis("monitor_col_id") ? <TableCell>{t("payroll.colId")}</TableCell> : null}
              {vis("monitor_col_user") ? <TableCell>{t("payroll.colUser")}</TableCell> : null}
              {vis("monitor_col_cycle") ? <TableCell>{t("payroll.colCycle")}</TableCell> : null}
              {vis("monitor_col_clock_in") ? <TableCell>{t("payroll.colClockIn")}</TableCell> : null}
              {vis("monitor_col_clock_out") ? <TableCell>{t("payroll.colClockOut")}</TableCell> : null}
              {vis("monitor_col_net") ? <TableCell>{t("payroll.colNetSec")}</TableCell> : null}
              {vis("monitor_col_status") ? <TableCell>{t("payroll.colStatus")}</TableCell> : null}
              {vis("monitor_col_geofence") ? <TableCell>{t("payroll.colGeofence")}</TableCell> : null}
              {vis("monitor_col_actions") ? <TableCell /> : null}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                {vis("monitor_col_id") ? <TableCell>{r.id}</TableCell> : null}
                {vis("monitor_col_user") ? (
                <TableCell>
                  {r.first_name} {r.last_name}
                  <Typography variant="caption" display="block" color="text.secondary">
                    {r.email}
                  </Typography>
                </TableCell>
                ) : null}
                {vis("monitor_col_cycle") ? <TableCell>{r.cycle_ref}</TableCell> : null}
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
                {vis("monitor_col_net") ? <TableCell>{r.net_work_seconds ?? "—"}</TableCell> : null}
                {vis("monitor_col_status") ? <TableCell>{r.status}</TableCell> : null}
                {vis("monitor_col_geofence") ? <TableCell>{r.geofence_name}</TableCell> : null}
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
            ))}
          </TableBody>
        </Table>
      </Box>

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
