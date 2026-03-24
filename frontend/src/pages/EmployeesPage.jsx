import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
  MenuItem,
} from "@mui/material";
import { createUser, getRoles, getUsers } from "../api";

function EmployeesPage({ user }) {
  const isAdmin = (user?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN");
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    username: "",
    password: "",
    display_name: "",
    active: true,
    roles: [],
  });

  const load = async () => {
    try {
      setError("");
      const [uRes, rRes] = await Promise.all([getUsers(), getRoles()]);
      setUsers(Array.isArray(uRes.data) ? uRes.data : []);
      setRoles(Array.isArray(rRes.data) ? rRes.data : []);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || "Failed to load users.");
    }
  };

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin]);

  const create = async () => {
    try {
      setSaving(true);
      setError("");
      await createUser(form);
      setOpen(false);
      setForm({ username: "", password: "", display_name: "", active: true, roles: [] });
      await load();
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || "User create failed.");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">Only ADMIN can manage users.</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", p: { xs: 1.2, md: 2 } }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 28 }}>Users & Roles</Typography>
        <Button variant="contained" onClick={() => setOpen(true)}>Add User</Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}

      <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
        <Stack spacing={1}>
          {users.map((u) => (
            <Stack key={u.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
              <Box>
                <Typography>{u.display_name || u.username}</Typography>
                <Typography sx={{ color: "#64748b", fontSize: 13 }}>{u.username}</Typography>
              </Box>
              <Stack direction="row" spacing={0.6} sx={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
                {(u.roles || []).map((r) => <Chip key={`${u.id}-${r}`} label={r} size="small" />)}
                <Chip label={u.active ? "ACTIVE" : "INACTIVE"} size="small" color={u.active ? "success" : "default"} />
              </Stack>
            </Stack>
          ))}
        </Stack>
      </Paper>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create User</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField label="Username" value={form.username} onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))} />
            <TextField label="Display Name" value={form.display_name} onChange={(e) => setForm((p) => ({ ...p, display_name: e.target.value }))} />
            <TextField label="Password" type="password" value={form.password} onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))} />
            <TextField
              select
              label="Primary Role"
              value={form.roles[0] || ""}
              onChange={(e) => setForm((p) => ({ ...p, roles: [e.target.value] }))}
            >
              {roles.map((r) => (
                <MenuItem key={r.code} value={r.code}>{r.code}</MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={create} disabled={saving || !form.username || !form.password || !form.roles.length}>
            {saving ? "Saving..." : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default EmployeesPage;

