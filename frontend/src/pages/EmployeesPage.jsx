import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  OutlinedInput,
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
  createTaUser,
  getEmploymentCategories,
  getGeofences,
  getTaRoles,
  getTaUser,
  getTaUsers,
  putUserEmploymentCategories,
  putUserGeofences,
  updateTaUser,
} from "../api";
import { useAuth } from "../context/AuthContext";

function EmployeesPage() {
  const { hasPerm } = useAuth();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [geofences, setGeofences] = useState([]);
  const [cats, setCats] = useState([]);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(null);
  const [form, setForm] = useState({});

  const canView = hasPerm("users.view");
  const canEdit = hasPerm("users.edit");
  const canAdd = hasPerm("users.add");

  const load = useCallback(async () => {
    if (!canView) return;
    try {
      const [u, r, g, c] = await Promise.all([
        getTaUsers(),
        getTaRoles(),
        getGeofences(),
        getEmploymentCategories(),
      ]);
      setUsers(u.data || []);
      setRoles(r.data || []);
      setGeofences(g.data || []);
      setCats(c.data || []);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    }
  }, [canView]);

  useEffect(() => {
    const t = setTimeout(() => {
      load();
    }, 0);
    return () => clearTimeout(t);
  }, [load]);

  function openCreate() {
    setForm({
      first_name: "",
      last_name: "",
      email: "",
      password: "",
      role_id: roles[0]?.id || "",
      employee_id: "",
      mobile: "",
      active: true,
    });
    setDialog("create");
  }

  async function openEdit(u) {
    setError("");
    try {
      const res = await getTaUser(u.id);
      const d = res.data;
      const catRows =
        d.employment_assignments?.length > 0
          ? d.employment_assignments.map((a) => ({
              employment_category_id: a.employment_category_id,
              effective_from: String(a.effective_from).slice(0, 10),
              effective_to: a.effective_to ? String(a.effective_to).slice(0, 10) : "",
            }))
          : [
              {
                employment_category_id: cats[0]?.id || "",
                effective_from: new Date().toISOString().slice(0, 10),
                effective_to: "",
              },
            ];
      setForm({
        ...d,
        password: "",
        geofence_ids: d.geofence_ids || [],
        primary_geofence_id: d.primary_geofence_id || "",
        cat_rows: catRows,
      });
      setDialog("edit");
    } catch (e) {
      setError(e.response?.data?.error || "Could not load user");
    }
  }

  async function saveCreate() {
    try {
      await createTaUser({
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        password: form.password,
        role_id: form.role_id,
        employee_id: form.employee_id || null,
        mobile: form.mobile || null,
        active: form.active,
      });
      setDialog(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Create failed");
    }
  }

  async function saveEdit() {
    try {
      await updateTaUser(form.id, {
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        mobile: form.mobile,
        employee_id: form.employee_id,
        role_id: form.role_id,
        active: form.active,
        hire_date: form.hire_date || null,
        termination_date: form.termination_date || null,
        rehired: form.rehired,
        address: form.address,
        itin_ssn: form.itin_ssn,
        password: form.password || undefined,
      });
      if (form.geofence_ids?.length && form.primary_geofence_id) {
        await putUserGeofences(form.id, {
          geofence_ids: form.geofence_ids.map(Number),
          primary_geofence_id: Number(form.primary_geofence_id),
        });
      }
      if (form.cat_rows?.length) {
        await putUserEmploymentCategories(form.id, {
          assignments: form.cat_rows
            .filter((r) => r.employment_category_id)
            .map((r) => ({
              employment_category_id: Number(r.employment_category_id),
              effective_from: r.effective_from,
              effective_to: r.effective_to || null,
            })),
        });
      }
      setDialog(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Update failed");
    }
  }

  if (!canView) {
    return (
      <div className="page">
        <Alert severity="info">You do not have permission to view users.</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h4" className="page-title">
          Users
        </Typography>
        {canAdd ? (
          <Button variant="contained" onClick={openCreate}>
            Add user
          </Button>
        ) : null}
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Box className="table-wrapper">
        <Table size="small" className="orders-table">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Email</TableCell>
              <TableCell>Role</TableCell>
              <TableCell>Active</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id}>
                <TableCell>
                  {u.first_name} {u.last_name}
                </TableCell>
                <TableCell>{u.email}</TableCell>
                <TableCell>{u.role_name}</TableCell>
                <TableCell>{u.active ? "yes" : "no"}</TableCell>
                <TableCell>
                  {canEdit ? (
                    <Button size="small" onClick={() => openEdit(u)}>
                      Edit
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>

      <Dialog open={dialog === "create"} onClose={() => setDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>New user</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="First name" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} required />
            <TextField label="Last name" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} required />
            <TextField label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <TextField label="Password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            <TextField select label="Role" value={form.role_id || ""} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
              {roles.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField label="Employee ID" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} />
            <TextField label="Mobile" value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} />
            <FormControlLabel
              control={<Checkbox checked={!!form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />}
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveCreate}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={dialog === "edit"} onClose={() => setDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit user</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="First name" value={form.first_name || ""} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
            <TextField label="Last name" value={form.last_name || ""} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
            <TextField label="Email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <TextField
              label="New password (optional)"
              type="password"
              value={form.password || ""}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            <TextField select label="Role" value={form.role_id || ""} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
              {roles.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={<Checkbox checked={!!form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />}
              label="Active"
            />
            <Typography variant="subtitle2">Geofences (assign + one primary)</Typography>
            <FormControl fullWidth>
              <InputLabel id="gf-label">Geofences</InputLabel>
              <Select
                labelId="gf-label"
                multiple
                value={form.geofence_ids || []}
                onChange={(e) => setForm({ ...form, geofence_ids: e.target.value })}
                input={<OutlinedInput label="Geofences" />}
                renderValue={(selected) =>
                  selected
                    .map((id) => geofences.find((g) => g.id === id)?.name || id)
                    .join(", ")
                }
              >
                {geofences.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Primary geofence ID"
              value={form.primary_geofence_id || ""}
              onChange={(e) => setForm({ ...form, primary_geofence_id: e.target.value })}
              helperText="Must be one of the selected geofences"
            />
            <Typography variant="subtitle2">Employment category assignment</Typography>
            {(form.cat_rows || []).map((row, i) => (
              <Stack key={i} direction="row" spacing={1}>
                <TextField
                  select
                  label="Category"
                  value={row.employment_category_id}
                  onChange={(e) => {
                    const next = [...(form.cat_rows || [])];
                    next[i] = { ...next[i], employment_category_id: e.target.value };
                    setForm({ ...form, cat_rows: next });
                  }}
                  sx={{ minWidth: 180 }}
                >
                  {cats.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  type="date"
                  label="From"
                  InputLabelProps={{ shrink: true }}
                  value={row.effective_from || ""}
                  onChange={(e) => {
                    const next = [...(form.cat_rows || [])];
                    next[i] = { ...next[i], effective_from: e.target.value };
                    setForm({ ...form, cat_rows: next });
                  }}
                />
              </Stack>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

export default EmployeesPage;
