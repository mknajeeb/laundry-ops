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

function PayrollMonitorPage({ embedded = false }) {
  const { hasPerm } = useAuth();
  const { t } = useI18n();
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
        <TextField
          label={t("payroll.userFilter")}
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          sx={{ width: 140 }}
        />
        <Button variant="contained" onClick={load}>
          {t("payroll.apply")}
        </Button>
      </Stack>

      <Box className="table-wrapper">
        <Table size="small" className="orders-table">
          <TableHead>
            <TableRow>
              <TableCell>{t("payroll.colId")}</TableCell>
              <TableCell>{t("payroll.colUser")}</TableCell>
              <TableCell>{t("payroll.colCycle")}</TableCell>
              <TableCell>{t("payroll.colClockIn")}</TableCell>
              <TableCell>{t("payroll.colClockOut")}</TableCell>
              <TableCell>{t("payroll.colNetSec")}</TableCell>
              <TableCell>{t("payroll.colStatus")}</TableCell>
              <TableCell>{t("payroll.colGeofence")}</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell>
                  {r.first_name} {r.last_name}
                  <Typography variant="caption" display="block" color="text.secondary">
                    {r.email}
                  </Typography>
                </TableCell>
                <TableCell>{r.cycle_ref}</TableCell>
                <TableCell>{r.clock_in_at ? String(r.clock_in_at).slice(0, 19) : ""}</TableCell>
                <TableCell>{r.clock_out_at ? String(r.clock_out_at).slice(0, 19) : "—"}</TableCell>
                <TableCell>{r.net_work_seconds ?? "—"}</TableCell>
                <TableCell>{r.status}</TableCell>
                <TableCell>{r.geofence_name}</TableCell>
                <TableCell>
                  {r.status === "active" && hasPerm("ta.override") ? (
                    <Button size="small" onClick={() => setForceOpen(r)}>
                      {t("payroll.forceOut")}
                    </Button>
                  ) : null}
                </TableCell>
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
