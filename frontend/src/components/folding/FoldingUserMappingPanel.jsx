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
  deleteFoldingUserMapping,
  getTaUsers,
  listFoldingUserMappings,
  listFoldingUsers,
  upsertFoldingUserMapping,
} from "../../api";

export default function FoldingUserMappingPanel() {
  const [mappings, setMappings] = useState([]);
  const [rinseUsers, setRinseUsers] = useState([]);
  const [taUsers, setTaUsers] = useState([]);
  const [rinseName, setRinseName] = useState("");
  const [userId, setUserId] = useState("");
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [mapRes, rinseRes, taRes] = await Promise.all([
        listFoldingUserMappings(),
        listFoldingUsers(),
        getTaUsers(),
      ]);
      setMappings(mapRes.data?.mappings || []);
      setRinseUsers(rinseRes.data?.users || []);
      setTaUsers(taRes.data || []);
    } catch (e) {
      setMessage(e?.response?.data?.error || e?.message || "Failed to load mappings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    if (!rinseName || !userId) return;
    try {
      await upsertFoldingUserMapping({
        rinse_user_name: rinseName,
        user_id: Number(userId),
        active: true,
        notes: notes || undefined,
      });
      setRinseName("");
      setUserId("");
      setNotes("");
      setMessage("");
      await load();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Could not save mapping");
    }
  };

  const remove = async (row) => {
    try {
      await deleteFoldingUserMapping(row.id);
      await load();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Could not delete mapping");
    }
  };

  const taLabel = (u) => {
    const name = u.display_name || u.username || u.email || `User #${u.id}`;
    return `${name} (#${u.id})`;
  };

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Rinse folder → clock user mapping
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" mb={2}>
        Maps Rinse assigned_user_name to internal users for clock-hour productivity (Mode C).
        Bag-wise and work-span modes do not require a mapping.
      </Typography>
      {message ? <Alert severity="error" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert> : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap" mb={2}>
        <FormControl size="small" sx={{ minWidth: 220 }} disabled={loading}>
          <InputLabel>Rinse user name</InputLabel>
          <Select label="Rinse user name" value={rinseName} onChange={(e) => setRinseName(e.target.value)}>
            <MenuItem value=""><em>Select…</em></MenuItem>
            {rinseUsers.map((u) => (
              <MenuItem key={u} value={u}>{u}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 260 }} disabled={loading}>
          <InputLabel>Clock / payroll user</InputLabel>
          <Select label="Clock / payroll user" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <MenuItem value=""><em>Select…</em></MenuItem>
            {taUsers.map((u) => (
              <MenuItem key={u.id} value={String(u.id)}>{taLabel(u)}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          size="small"
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          sx={{ minWidth: 160 }}
        />
        <Button variant="contained" onClick={save} disabled={!rinseName || !userId || loading}>
          Save mapping
        </Button>
      </Stack>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Rinse name</TableCell>
            <TableCell>User</TableCell>
            <TableCell>Active</TableCell>
            <TableCell>Notes</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {mappings.length === 0 ? (
            <TableRow><TableCell colSpan={5} align="center">No mappings yet.</TableCell></TableRow>
          ) : mappings.map((row) => (
            <TableRow key={row.id}>
              <TableCell>{row.rinse_user_name}</TableCell>
              <TableCell>{row.display_name || row.username || row.user_id}</TableCell>
              <TableCell>{row.active ? "Yes" : "No"}</TableCell>
              <TableCell>{row.notes || "—"}</TableCell>
              <TableCell align="right">
                <Button size="small" color="error" onClick={() => remove(row)}>Delete</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  );
}
