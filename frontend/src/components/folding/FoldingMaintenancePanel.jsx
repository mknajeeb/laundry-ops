import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
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
  addFoldingExcludedUser,
  listFoldingExcludedUsers,
  listFoldingUsers,
  removeFoldingExcludedUser,
} from "../../api";
import FoldingExceptionRulesPanel from "./FoldingExceptionRulesPanel";

export default function FoldingMaintenancePanel({ onChanged }) {
  const [excluded, setExcluded] = useState([]);
  const [users, setUsers] = useState([]);
  const [pickUser, setPickUser] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [exRes, uRes] = await Promise.all([
        listFoldingExcludedUsers(),
        listFoldingUsers(),
      ]);
      setExcluded(exRes.data || []);
      setUsers(uRes.data?.users || []);
    } catch (e) {
      setMessage(e?.response?.data?.error || e?.message || "Failed to load excluded users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const addExcluded = async () => {
    if (!pickUser) return;
    try {
      await addFoldingExcludedUser({ user_name: pickUser, reason: reason || undefined });
      setPickUser("");
      setReason("");
      setMessage("");
      await load();
      onChanged?.();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Could not add excluded user");
    }
  };

  const removeExcluded = async (row) => {
    try {
      await removeFoldingExcludedUser({ id: row.id, user_name: row.user_name });
      await load();
      onChanged?.();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Could not remove excluded user");
    }
  };

  const available = users.filter(
    (u) => !excluded.some((e) => String(e.user_name || "").trim() === String(u).trim())
  );

  return (
    <>
      <FoldingExceptionRulesPanel onRecomputeApplied={onChanged} />
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Excluded users (leaderboard / TV scoring)
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" mb={2}>
        Excluded users are hidden from leaderboard and TV team scoring. They still appear in folding records and audit views.
      </Typography>
      {message ? <Alert severity="error" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert> : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap" mb={2}>
        <FormControl size="small" sx={{ minWidth: 220 }} disabled={loading}>
          <InputLabel>User from folding data</InputLabel>
          <Select label="User from folding data" value={pickUser} onChange={(e) => setPickUser(e.target.value)}>
            <MenuItem value=""><em>Select…</em></MenuItem>
            {available.map((u) => (
              <MenuItem key={u} value={u}>{u}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField size="small" label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ minWidth: 200 }} />
        <Button variant="contained" onClick={addExcluded} disabled={!pickUser || loading}>Add excluded</Button>
      </Stack>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>User</TableCell>
            <TableCell>Reason</TableCell>
            <TableCell>Added</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {excluded.length === 0 ? (
            <TableRow><TableCell colSpan={4} align="center">No excluded users.</TableCell></TableRow>
          ) : excluded.map((row) => (
            <TableRow key={row.id || row.user_name}>
              <TableCell>{row.user_name}</TableCell>
              <TableCell>{row.reason || "—"}</TableCell>
              <TableCell>{row.created_at ? String(row.created_at).slice(0, 10) : "—"}</TableCell>
              <TableCell align="right">
                <Button size="small" color="primary" onClick={() => removeExcluded(row)}>Remove</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
    </>
  );
}
