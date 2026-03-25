import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  OutlinedInput,
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
  createTaUser,
  createUser,
  deleteUser,
  getEmploymentCategories,
  getGeofences,
  getRoles,
  getTaRoles,
  getTaUser,
  getTaUsers,
  getUsers,
  putUserEmploymentCategories,
  putUserGeofences,
  updateTaUser,
  updateUser,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function PeoplePage({ user }) {
  const { hasPerm } = useAuth();
  const { t } = useI18n();
  const isAdmin = (user?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN");
  const canTaView = hasPerm("users.view");
  const canTaEdit = hasPerm("users.edit");
  const canTaAdd = hasPerm("users.add");

  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [wpUsers, setWpUsers] = useState([]);
  const [wpRoles, setWpRoles] = useState([]);
  const [taUsers, setTaUsers] = useState([]);
  const [taRoles, setTaRoles] = useState([]);
  const [geofences, setGeofences] = useState([]);
  const [cats, setCats] = useState([]);

  const [wpDialog, setWpDialog] = useState(null);
  const [wpForm, setWpForm] = useState({});
  const [wpSaving, setWpSaving] = useState(false);
  const [deleteWpId, setDeleteWpId] = useState(null);

  const [taDialog, setTaDialog] = useState(null);
  const [taForm, setTaForm] = useState({});

  const loadWashpro = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setError("");
      const [uRes, rRes] = await Promise.all([getUsers(), getRoles()]);
      setWpUsers(Array.isArray(uRes.data) ? uRes.data : []);
      setWpRoles(Array.isArray(rRes.data) ? rRes.data : []);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || "Failed to load Washpro users.");
    }
  }, [isAdmin]);

  const loadTa = useCallback(async () => {
    if (!canTaView) return;
    try {
      const [u, r, g, c] = await Promise.all([
        getTaUsers(),
        getTaRoles(),
        getGeofences(),
        getEmploymentCategories(),
      ]);
      setTaUsers(u.data || []);
      setTaRoles(r.data || []);
      setGeofences(g.data || []);
      setCats(c.data || []);
    } catch (e) {
      setError(e.response?.data?.error || "Failed to load payroll profiles.");
    }
  }, [canTaView]);

  const loadAll = useCallback(async () => {
    await loadWashpro();
    await loadTa();
  }, [loadWashpro, loadTa]);

  useEffect(() => {
    if (isAdmin) loadWashpro();
  }, [isAdmin, loadWashpro]);

  useEffect(() => {
    if (canTaView) loadTa();
  }, [canTaView, loadTa]);

  const q = search.trim().toLowerCase();
  const wpFiltered = useMemo(() => {
    if (!q) return wpUsers;
    return wpUsers.filter((u) => {
      const roles = (u.roles || []).join(" ").toLowerCase();
      const dn = String(u.display_name || "").toLowerCase();
      const un = String(u.username || "").toLowerCase();
      return un.includes(q) || dn.includes(q) || roles.includes(q);
    });
  }, [wpUsers, q]);

  const taFiltered = useMemo(() => {
    if (!q) return taUsers;
    return taUsers.filter((u) => {
      const blob = [
        u.first_name,
        u.last_name,
        u.email,
        u.employee_id,
        u.role_name,
        String(u.washpro_user_id || ""),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [taUsers, q]);

  const taByWashproId = useMemo(() => {
    const m = new Map();
    for (const t of taUsers) {
      if (t.washpro_user_id) m.set(t.washpro_user_id, t);
    }
    return m;
  }, [taUsers]);

  const washproById = useMemo(() => {
    const m = new Map();
    for (const u of wpUsers) m.set(u.id, u);
    return m;
  }, [wpUsers]);

  function openWpCreate() {
    setWpForm({
      username: "",
      password: "",
      display_name: "",
      active: true,
      roles: wpRoles[0]?.code ? [wpRoles[0].code] : [],
    });
    setWpDialog("create");
  }

  function openWpEdit(u) {
    setWpForm({
      id: u.id,
      username: u.username,
      display_name: u.display_name || "",
      active: !!u.active,
      roles: [...(u.roles || [])],
      password: "",
    });
    setWpDialog("edit");
  }

  async function saveWpCreate() {
    try {
      setWpSaving(true);
      setError("");
      await createUser(wpForm);
      setWpDialog(null);
      await loadWashpro();
    } catch (e) {
      setError(e?.response?.data?.error || "Create failed.");
    } finally {
      setWpSaving(false);
    }
  }

  async function saveWpEdit() {
    try {
      setWpSaving(true);
      setError("");
      await updateUser(wpForm.id, {
        username: wpForm.username,
        display_name: wpForm.display_name,
        active: wpForm.active,
        roles: wpForm.roles || [],
        password: wpForm.password || undefined,
      });
      setWpDialog(null);
      await loadWashpro();
    } catch (e) {
      setError(e?.response?.data?.error || "Update failed.");
    } finally {
      setWpSaving(false);
    }
  }

  async function confirmDeleteWp() {
    if (!deleteWpId) return;
    try {
      setError("");
      await deleteUser(deleteWpId);
      setDeleteWpId(null);
      await loadAll();
    } catch (e) {
      setError(e?.response?.data?.error || "Delete failed.");
    }
  }

  function openTaCreate() {
    setTaForm({
      first_name: "",
      last_name: "",
      email: "",
      password: "",
      role_id: taRoles[0]?.id || "",
      employee_id: "",
      mobile: "",
      address: "",
      itin_ssn: "",
      hire_date: "",
      termination_date: "",
      rehired: false,
      active: true,
      rehire_parent_id: "",
      prior_employee_id: "",
    });
    setTaDialog("create");
  }

  function suggestNewEmployeeId() {
    const parentId = taForm.rehire_parent_id;
    const parent = parentId ? taUsers.find((x) => x.id === Number(parentId)) : null;
    const base = (parent?.employee_id || taForm.employee_id || "EMP").replace(/-R\d+$/, "");
    setTaForm((f) => ({ ...f, employee_id: `${base}-R${String(Date.now()).slice(-4)}` }));
  }

  async function openTaEdit(u) {
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
      setTaForm({
        ...d,
        password: "",
        geofence_ids: d.geofence_ids || [],
        primary_geofence_id: d.primary_geofence_id || "",
        cat_rows: catRows,
        rehire_parent_id: d.rehire_parent_id != null ? String(d.rehire_parent_id) : "",
        prior_employee_id: d.prior_employee_id || "",
      });
      setTaDialog("edit");
    } catch (e) {
      setError(e.response?.data?.error || "Could not load payroll profile.");
    }
  }

  async function saveTaCreate() {
    try {
      await createTaUser({
        first_name: taForm.first_name,
        last_name: taForm.last_name,
        email: taForm.email,
        password: taForm.password,
        role_id: taForm.role_id,
        employee_id: taForm.employee_id || null,
        mobile: taForm.mobile || null,
        address: taForm.address || null,
        itin_ssn: taForm.itin_ssn || null,
        hire_date: taForm.hire_date || null,
        termination_date: taForm.termination_date || null,
        rehired: !!taForm.rehired,
        active: taForm.active,
        rehire_parent_id: taForm.rehire_parent_id ? Number(taForm.rehire_parent_id) : null,
        prior_employee_id: taForm.prior_employee_id || null,
      });
      setTaDialog(null);
      await loadTa();
    } catch (e) {
      setError(e.response?.data?.error || "Create failed.");
    }
  }

  async function saveTaEdit() {
    try {
      await updateTaUser(taForm.id, {
        first_name: taForm.first_name,
        last_name: taForm.last_name,
        email: taForm.email,
        mobile: taForm.mobile,
        employee_id: taForm.employee_id,
        role_id: taForm.role_id,
        active: taForm.active,
        hire_date: taForm.hire_date || null,
        termination_date: taForm.termination_date || null,
        rehired: taForm.rehired,
        address: taForm.address,
        itin_ssn: taForm.itin_ssn,
        password: taForm.password || undefined,
        rehire_parent_id:
          taForm.rehire_parent_id === "" || taForm.rehire_parent_id == null
            ? null
            : Number(taForm.rehire_parent_id),
        prior_employee_id: taForm.prior_employee_id || null,
      });
      if (taForm.geofence_ids?.length && taForm.primary_geofence_id) {
        await putUserGeofences(taForm.id, {
          geofence_ids: taForm.geofence_ids.map(Number),
          primary_geofence_id: Number(taForm.primary_geofence_id),
        });
      }
      if (taForm.cat_rows?.length) {
        await putUserEmploymentCategories(taForm.id, {
          assignments: taForm.cat_rows
            .filter((r) => r.employment_category_id)
            .map((r) => ({
              employment_category_id: Number(r.employment_category_id),
              effective_from: r.effective_from,
              effective_to: r.effective_to || null,
            })),
        });
      }
      setTaDialog(null);
      await loadTa();
    } catch (e) {
      setError(e.response?.data?.error || "Update failed.");
    }
  }

  if (!isAdmin) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("people.onlyAdmin")}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", p: { xs: 1.2, md: 2 } }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 28 }}>{t("people.title")}</Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {t("people.intro")}
      </Typography>

      <TextField
        fullWidth
        size="small"
        label={t("common.search")}
        placeholder={t("people.searchPlaceholder")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ mb: 2, maxWidth: 480 }}
      />

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Typography variant="h6" sx={{ mb: 1 }}>
        {t("people.washproSection")}
      </Typography>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
        <Button variant="contained" onClick={openWpCreate}>
          {t("people.addLogin")}
        </Button>
      </Stack>
      <Paper sx={{ p: 1.5, borderRadius: 2, mb: 3 }}>
        <Box className="table-wrapper">
          <Table size="small" className="orders-table">
            <TableHead>
              <TableRow>
                <TableCell>{t("people.colUsername")}</TableCell>
                <TableCell>{t("people.colDisplay")}</TableCell>
                <TableCell>{t("people.colRoles")}</TableCell>
                <TableCell>{t("people.colPayrollLink")}</TableCell>
                <TableCell>{t("common.active")}</TableCell>
                <TableCell align="right">{t("people.colActions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {wpFiltered.map((u) => {
                const ta = taByWashproId.get(u.id);
                return (
                  <TableRow key={u.id}>
                    <TableCell>{u.username}</TableCell>
                    <TableCell>{u.display_name || "—"}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        {(u.roles || []).map((r) => (
                          <Chip key={r} label={r} size="small" />
                        ))}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      {ta ? (
                        <>
                          {ta.first_name} {ta.last_name}
                          <Typography variant="caption" display="block" color="text.secondary">
                            TA #{ta.id}
                          </Typography>
                        </>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>{u.active ? t("common.yes") : t("common.no")}</TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => openWpEdit(u)}>
                        {t("common.edit")}
                      </Button>
                      <Button size="small" color="error" onClick={() => setDeleteWpId(u.id)}>
                        {t("common.delete")}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Box>
      </Paper>

      {canTaView ? (
        <>
          <Typography variant="h6" sx={{ mb: 1 }}>
            {t("people.taSection")}
          </Typography>
          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
            {canTaAdd ? (
              <Button variant="outlined" onClick={openTaCreate}>
                {t("people.addProfile")}
              </Button>
            ) : null}
          </Stack>
          <Paper sx={{ p: 1.5, borderRadius: 2 }}>
            <Box className="table-wrapper">
              <Table size="small" className="orders-table">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("people.colName")}</TableCell>
                    <TableCell>{t("people.colEmail")}</TableCell>
                    <TableCell>{t("people.colRole")}</TableCell>
                    <TableCell>{t("people.colWashproLogin")}</TableCell>
                    <TableCell>{t("common.active")}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {taFiltered.map((u) => {
                    const wp = u.washpro_user_id ? washproById.get(u.washpro_user_id) : null;
                    return (
                      <TableRow key={u.id}>
                        <TableCell>
                          {u.first_name} {u.last_name}
                        </TableCell>
                        <TableCell>{u.email}</TableCell>
                        <TableCell>{u.role_name}</TableCell>
                        <TableCell>
                          {wp ? (
                            <>
                              {wp.username}
                              <Typography variant="caption" display="block" color="text.secondary">
                                WP #{wp.id}
                              </Typography>
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>{u.active ? t("common.yes") : t("common.no")}</TableCell>
                        <TableCell>
                          {canTaEdit ? (
                            <Button size="small" onClick={() => openTaEdit(u)}>
                              {t("common.edit")}
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          </Paper>
        </>
      ) : (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t("people.needView")}
        </Alert>
      )}

      <Dialog open={wpDialog === "create"} onClose={() => setWpDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>New Washpro login</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField
              label="Username"
              value={wpForm.username || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, username: e.target.value }))}
              required
            />
            <TextField
              label="Display name"
              value={wpForm.display_name || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, display_name: e.target.value }))}
            />
            <TextField
              label="Password"
              type="password"
              value={wpForm.password || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, password: e.target.value }))}
              required
            />
            <TextField
              select
              label="Roles"
              SelectProps={{ multiple: true }}
              value={wpForm.roles || []}
              onChange={(e) => setWpForm((p) => ({ ...p, roles: e.target.value }))}
            >
              {wpRoles.map((r) => (
                <MenuItem key={r.code} value={r.code}>
                  {r.code}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setWpDialog(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={saveWpCreate}
            disabled={
              wpSaving || !wpForm.username || !wpForm.password || !(wpForm.roles || []).length
            }
          >
            {wpSaving ? "Saving…" : "Create"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={wpDialog === "edit"} onClose={() => setWpDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Washpro login</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField
              label="Username"
              value={wpForm.username || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, username: e.target.value }))}
              required
            />
            <TextField
              label="Display name"
              value={wpForm.display_name || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, display_name: e.target.value }))}
            />
            <TextField
              label="New password (optional)"
              type="password"
              value={wpForm.password || ""}
              onChange={(e) => setWpForm((p) => ({ ...p, password: e.target.value }))}
            />
            <TextField
              select
              label="Roles"
              SelectProps={{ multiple: true }}
              value={wpForm.roles || []}
              onChange={(e) => setWpForm((p) => ({ ...p, roles: e.target.value }))}
            >
              {wpRoles.map((r) => (
                <MenuItem key={r.code} value={r.code}>
                  {r.code}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Checkbox
                  checked={!!wpForm.active}
                  onChange={(e) => setWpForm((p) => ({ ...p, active: e.target.checked }))}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setWpDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveWpEdit} disabled={wpSaving || !wpForm.username}>
            {wpSaving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleteWpId} onClose={() => setDeleteWpId(null)}>
        <DialogTitle>Delete Washpro login?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            This removes the login and unlinks any payroll profile. Sessions for that user end.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteWpId(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDeleteWp}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={taDialog === "create"} onClose={() => setTaDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>New payroll profile</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="First name"
              value={taForm.first_name}
              onChange={(e) => setTaForm({ ...taForm, first_name: e.target.value })}
              required
            />
            <TextField
              label="Last name"
              value={taForm.last_name}
              onChange={(e) => setTaForm({ ...taForm, last_name: e.target.value })}
              required
            />
            <TextField
              label="Email"
              type="email"
              value={taForm.email}
              onChange={(e) => setTaForm({ ...taForm, email: e.target.value })}
              required
            />
            <TextField
              label="Password"
              type="password"
              value={taForm.password}
              onChange={(e) => setTaForm({ ...taForm, password: e.target.value })}
              required
            />
            <TextField
              select
              label="Role"
              value={taForm.role_id || ""}
              onChange={(e) => setTaForm({ ...taForm, role_id: e.target.value })}
            >
              {taRoles.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Employee ID"
              value={taForm.employee_id}
              onChange={(e) => setTaForm({ ...taForm, employee_id: e.target.value })}
            />
            <TextField
              label="Mobile"
              value={taForm.mobile}
              onChange={(e) => setTaForm({ ...taForm, mobile: e.target.value })}
            />
            <TextField
              label="Full address"
              value={taForm.address || ""}
              onChange={(e) => setTaForm({ ...taForm, address: e.target.value })}
              multiline
              minRows={2}
            />
            <TextField
              label="ITIN or SSN (restricted access)"
              value={taForm.itin_ssn || ""}
              onChange={(e) => setTaForm({ ...taForm, itin_ssn: e.target.value })}
            />
            <TextField
              label="Hire date"
              type="date"
              InputLabelProps={{ shrink: true }}
              value={taForm.hire_date ? String(taForm.hire_date).slice(0, 10) : ""}
              onChange={(e) => setTaForm({ ...taForm, hire_date: e.target.value })}
            />
            <TextField
              label="Termination date"
              type="date"
              InputLabelProps={{ shrink: true }}
              value={taForm.termination_date ? String(taForm.termination_date).slice(0, 10) : ""}
              onChange={(e) => setTaForm({ ...taForm, termination_date: e.target.value })}
            />
            <FormControl fullWidth>
              <InputLabel id="rhp-create">{t("people.rehireFrom")}</InputLabel>
              <Select
                labelId="rhp-create"
                label={t("people.rehireFrom")}
                value={taForm.rehire_parent_id || ""}
                onChange={(e) => setTaForm({ ...taForm, rehire_parent_id: e.target.value })}
              >
                <MenuItem value="">—</MenuItem>
                {taUsers.map((row) => (
                  <MenuItem key={row.id} value={String(row.id)}>
                    {row.first_name} {row.last_name} ({row.employee_id || `TA#${row.id}`})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label={t("people.priorEmpId")}
              value={taForm.prior_employee_id || ""}
              onChange={(e) => setTaForm({ ...taForm, prior_employee_id: e.target.value })}
            />
            <Button variant="outlined" size="small" onClick={suggestNewEmployeeId} sx={{ alignSelf: "flex-start" }}>
              {t("people.suggestId")}
            </Button>
            <FormControlLabel
              control={
                <Checkbox checked={!!taForm.rehired} onChange={(e) => setTaForm({ ...taForm, rehired: e.target.checked })} />
              }
              label="Rehired"
            />
            <FormControlLabel
              control={
                <Checkbox checked={!!taForm.active} onChange={(e) => setTaForm({ ...taForm, active: e.target.checked })} />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTaDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveTaCreate}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={taDialog === "edit"} onClose={() => setTaDialog(null)} maxWidth="md" fullWidth>
        <DialogTitle>Edit payroll profile</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="First name"
              value={taForm.first_name || ""}
              onChange={(e) => setTaForm({ ...taForm, first_name: e.target.value })}
            />
            <TextField
              label="Last name"
              value={taForm.last_name || ""}
              onChange={(e) => setTaForm({ ...taForm, last_name: e.target.value })}
            />
            <TextField
              label="Email"
              value={taForm.email || ""}
              onChange={(e) => setTaForm({ ...taForm, email: e.target.value })}
            />
            <TextField
              label="Employee ID"
              value={taForm.employee_id || ""}
              onChange={(e) => setTaForm({ ...taForm, employee_id: e.target.value })}
            />
            <TextField
              label="Mobile"
              value={taForm.mobile || ""}
              onChange={(e) => setTaForm({ ...taForm, mobile: e.target.value })}
            />
            <TextField
              label="Full address"
              value={taForm.address || ""}
              onChange={(e) => setTaForm({ ...taForm, address: e.target.value })}
              multiline
              minRows={2}
            />
            <TextField
              label="ITIN or SSN (restricted access)"
              value={taForm.itin_ssn || ""}
              onChange={(e) => setTaForm({ ...taForm, itin_ssn: e.target.value })}
            />
            <TextField
              label="Hire date"
              type="date"
              InputLabelProps={{ shrink: true }}
              value={taForm.hire_date ? String(taForm.hire_date).slice(0, 10) : ""}
              onChange={(e) => setTaForm({ ...taForm, hire_date: e.target.value })}
            />
            <TextField
              label="Termination date"
              type="date"
              InputLabelProps={{ shrink: true }}
              value={taForm.termination_date ? String(taForm.termination_date).slice(0, 10) : ""}
              onChange={(e) => setTaForm({ ...taForm, termination_date: e.target.value })}
            />
            <FormControlLabel
              control={
                <Checkbox checked={!!taForm.rehired} onChange={(e) => setTaForm({ ...taForm, rehired: e.target.checked })} />
              }
              label="Rehired"
            />
            <TextField
              label="New password (optional)"
              type="password"
              value={taForm.password || ""}
              onChange={(e) => setTaForm({ ...taForm, password: e.target.value })}
            />
            <TextField
              select
              label="Role"
              value={taForm.role_id || ""}
              onChange={(e) => setTaForm({ ...taForm, role_id: e.target.value })}
            >
              {taRoles.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Checkbox checked={!!taForm.active} onChange={(e) => setTaForm({ ...taForm, active: e.target.checked })} />
              }
              label="Active"
            />
            {(taForm.rehire_parent || (taForm.rehire_successors || []).length > 0) && (
              <Alert severity="info">
                <Typography variant="subtitle2">{t("people.rehireChain")}</Typography>
                {taForm.rehire_parent ? (
                  <Typography variant="body2">
                    {t("people.parent")}: #{taForm.rehire_parent.id} {taForm.rehire_parent.first_name}{" "}
                    {taForm.rehire_parent.last_name} ({taForm.rehire_parent.employee_id || "—"})
                  </Typography>
                ) : null}
                {(taForm.rehire_successors || []).length > 0 ? (
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {t("people.successors")}:{" "}
                    {(taForm.rehire_successors || [])
                      .map((s) => `#${s.id} ${s.first_name} ${s.last_name}`)
                      .join("; ")}
                  </Typography>
                ) : null}
              </Alert>
            )}
            <FormControl fullWidth>
              <InputLabel id="rhp-edit">{t("people.rehireFrom")}</InputLabel>
              <Select
                labelId="rhp-edit"
                label={t("people.rehireFrom")}
                value={taForm.rehire_parent_id || ""}
                onChange={(e) => setTaForm({ ...taForm, rehire_parent_id: e.target.value })}
              >
                <MenuItem value="">—</MenuItem>
                {taUsers
                  .filter((row) => row.id !== taForm.id)
                  .map((row) => (
                    <MenuItem key={row.id} value={String(row.id)}>
                      {row.first_name} {row.last_name} ({row.employee_id || `TA#${row.id}`})
                    </MenuItem>
                  ))}
              </Select>
            </FormControl>
            <TextField
              label={t("people.priorEmpId")}
              value={taForm.prior_employee_id || ""}
              onChange={(e) => setTaForm({ ...taForm, prior_employee_id: e.target.value })}
            />
            <Button variant="outlined" size="small" onClick={suggestNewEmployeeId} sx={{ alignSelf: "flex-start" }}>
              {t("people.suggestId")}
            </Button>
            <Typography variant="subtitle2">Geofences (assign + one primary)</Typography>
            <FormControl fullWidth>
              <InputLabel id="gf-label">Geofences</InputLabel>
              <Select
                labelId="gf-label"
                multiple
                value={taForm.geofence_ids || []}
                onChange={(e) => setTaForm({ ...taForm, geofence_ids: e.target.value })}
                input={<OutlinedInput label="Geofences" />}
                renderValue={(selected) =>
                  selected.map((id) => geofences.find((g) => g.id === id)?.name || id).join(", ")
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
              value={taForm.primary_geofence_id || ""}
              onChange={(e) => setTaForm({ ...taForm, primary_geofence_id: e.target.value })}
              helperText="Must be one of the selected geofences"
            />
            <Typography variant="subtitle2">Employment category assignment</Typography>
            {(taForm.cat_rows || []).map((row, i) => (
              <Stack key={i} direction="row" spacing={1}>
                <TextField
                  select
                  label="Category"
                  value={row.employment_category_id}
                  onChange={(e) => {
                    const next = [...(taForm.cat_rows || [])];
                    next[i] = { ...next[i], employment_category_id: e.target.value };
                    setTaForm({ ...taForm, cat_rows: next });
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
                    const next = [...(taForm.cat_rows || [])];
                    next[i] = { ...next[i], effective_from: e.target.value };
                    setTaForm({ ...taForm, cat_rows: next });
                  }}
                />
              </Stack>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTaDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveTaEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default PeoplePage;
