import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
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

function PayrollMonitorPage() {
  const { hasPerm } = useAuth();
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
      <div className="page">
        <Alert severity="info">Payroll monitor requires the Payroll / Supervisor role.</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      <Typography variant="h4" className="page-title" sx={{ mb: 2 }}>
        Payroll monitor
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }} alignItems="center">
        <TextField
          select
          label="Payroll cycle"
          value={cycleId}
          onChange={(e) => setCycleId(e.target.value)}
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">All</MenuItem>
          {cycles.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.cycle_ref} ({c.week_start_date})
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="User ID filter"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          sx={{ width: 140 }}
        />
        <Button variant="contained" onClick={load}>
          Apply
        </Button>
      </Stack>

      <Box className="table-wrapper">
        <Table size="small" className="orders-table">
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell>User</TableCell>
              <TableCell>Cycle</TableCell>
              <TableCell>Clock in</TableCell>
              <TableCell>Clock out</TableCell>
              <TableCell>Net sec</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Geofence</TableCell>
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
                      Force out
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>

      <Dialog open={!!forceOpen} onClose={() => setForceOpen(null)}>
        <DialogTitle>Force clock-out</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            multiline
            minRows={2}
            label="Remarks (required)"
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForceOpen(null)}>Cancel</Button>
          <Button variant="contained" onClick={doForce} disabled={!remarks.trim()}>
            Confirm
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

export default PayrollMonitorPage;
