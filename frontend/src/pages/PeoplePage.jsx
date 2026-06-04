import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MoreVert } from "@mui/icons-material";
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
  IconButton,
  InputLabel,
  Menu,
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
  getPayrollScheduleWorkers,
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
import SchedulingReadinessChip from "../components/worker/SchedulingReadinessChip";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function formatEmploymentStatusCell(ta, wpActive, t) {
  if (ta && ta.termination_date && String(ta.termination_date).trim() !== "") {
    return t("people.status.TERMINATED");
  }
  const code = (ta && ta.employment_status_code && String(ta.employment_status_code).trim()) || "";
  if (code) {
    const key = `people.status.${code.toUpperCase()}`;
    const lbl = t(key);
    return lbl === key ? code : lbl;
  }
  return wpActive ? t("people.status.ACTIVE") : t("people.status.INACTIVE");
}

/** Multi-select Washpro roles (CHECKOUT + UPLOAD can both be enabled). */
function WashproRolesMultiSelect({ label, value, onChange, roles }) {
  const selected = (value || []).map((c) => String(c || "").trim().toUpperCase()).filter(Boolean);
  const choices = (roles || []).map((r) => ({
    ...r,
    code: String(r.code || "").trim().toUpperCase(),
  }));

  return (
    <FormControl fullWidth>
      <InputLabel id="wp-roles-pick">{label}</InputLabel>
      <Select
        labelId="wp-roles-pick"
        multiple
        label={label}
        value={selected}
        onChange={(e) => {
          const raw = e.target.value;
          const next = (typeof raw === "string" ? raw.split(",") : raw)
            .map((c) => String(c || "").trim().toUpperCase())
            .filter(Boolean);
          onChange(next);
        }}
        input={<OutlinedInput label={label} />}
        renderValue={(sel) => sel.join(", ")}
      >
        {choices.map((r) => (
          <MenuItem key={r.code} value={r.code}>
            <Checkbox checked={selected.includes(r.code)} size="small" sx={{ py: 0, mr: 1 }} />
            {r.code}
            {r.name && r.name !== r.code ? ` — ${r.name}` : ""}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

function PeoplePage({ user }) {
  const navigate = useNavigate();
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
  const [rowMenuAnchor, setRowMenuAnchor] = useState(null);
  const [rowMenuCtx, setRowMenuCtx] = useState(null);

  const [filterStatus, setFilterStatus] = useState("all");
  const [filterCategoryId, setFilterCategoryId] = useState("");
  const [filterRole, setFilterRole] = useState("");
  const [filterDept, setFilterDept] = useState("");
  const [filterSchedule, setFilterSchedule] = useState("all");
  const [scheduleWorkers, setScheduleWorkers] = useState([]);

  const loadWashpro = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setError("");
      const [uRes, rRes] = await Promise.all([getUsers(), getRoles()]);
      setWpUsers(Array.isArray(uRes.data) ? uRes.data : []);
      setWpRoles(Array.isArray(rRes.data) ? rRes.data : []);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || t("people.errLoadAccounts"));
    }
  }, [isAdmin, t]);

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

  useEffect(() => {
    if (!canTaView) return;
    getPayrollScheduleWorkers()
      .then((res) => setScheduleWorkers(res.data?.items || []))
      .catch(() => setScheduleWorkers([]));
  }, [canTaView, taUsers.length]);

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

  /** Unified payroll: profiles use Washpro users.id as PK (payroll_profiles.user_id). */
  const payrollUnified = useMemo(() => {
    if (!canTaView) return false;
    if (!taUsers.length) return true;
    return taUsers.every(
      (t) => t.user_id != null && String(t.user_id) === String(t.id)
    );
  }, [canTaView, taUsers]);

  const taByWashproId = useMemo(() => {
    const m = new Map();
    for (const t of taUsers) {
      const wp = t.washpro_user_id ?? t.user_id ?? t.id;
      if (wp == null || wp === "") continue;
      m.set(Number(wp), t);
    }
    return m;
  }, [taUsers]);

  const formatTaCategory = (ta) => {
    const rows = ta?.employment_assignments;
    if (!Array.isArray(rows) || !rows.length) return "—";
    const top = rows[0];
    return top.category_name || top.category_code || "—";
  };

  const washproById = useMemo(() => {
    const m = new Map();
    for (const u of wpUsers) m.set(u.id, u);
    return m;
  }, [wpUsers]);

  const deptCodes = useMemo(() => {
    const s = new Set();
    for (const t of taUsers) {
      if (t.dept_code) s.add(String(t.dept_code));
    }
    return Array.from(s).sort();
  }, [taUsers]);

  const workerByUserId = useMemo(() => {
    const m = new Map();
    for (const w of scheduleWorkers) {
      if (w.user_id != null) m.set(Number(w.user_id), w);
    }
    return m;
  }, [scheduleWorkers]);

  const unifiedFiltered = useMemo(() => {
    return wpFiltered.filter((u) => {
      const ta = taByWashproId.get(u.id);
      const sw = workerByUserId.get(u.id);
      if (filterStatus === "active" && !u.active) return false;
      if (filterStatus === "inactive" && u.active) return false;
      if (filterCategoryId) {
        const rows = ta?.employment_assignments;
        const top =
          Array.isArray(rows) && rows[0] ? String(rows[0].employment_category_id || "") : "";
        if (top !== filterCategoryId) return false;
      }
      if (filterRole.trim()) {
        const blob = [ta?.role_name, ...(u.roles || [])].join(" ").toLowerCase();
        if (!blob.includes(filterRole.trim().toLowerCase())) return false;
      }
      if (filterDept && String(ta?.dept_code || "") !== filterDept) return false;
      if (filterSchedule !== "all" && sw) {
        const gaps = sw.profile_gaps || [];
        const cat = String(sw.worker_category || "").toLowerCase();
        const skills = sw.role_skills || [];
        const roleNames = skills.map((s) => String(s.role_name || "").toLowerCase());
        if (filterSchedule === "ready" && !sw.readiness?.ready) return false;
        if (filterSchedule === "missing_setup" && sw.readiness?.ready) return false;
        if (filterSchedule === "rate_missing" && !gaps.includes("Missing hourly rate")) return false;
        if (filterSchedule === "w2" && cat !== "w2") return false;
        if (filterSchedule === "1099" && !cat.includes("1099") && cat !== "contractor_1099") return false;
        if (filterSchedule === "temp" && cat !== "temp") return false;
        if (filterSchedule === "rinse" && !sw.can_work_rinse) return false;
        if (filterSchedule === "dropoff" && !sw.can_work_drop_off) return false;
        if (filterSchedule === "folder" && !roleNames.some((n) => n.includes("folder"))) return false;
        if (filterSchedule === "operator" && !roleNames.some((n) => n.includes("operator"))) return false;
        if (filterSchedule === "ot_missing" && sw.overtime_threshold == null) return false;
        if (filterSchedule === "active_only" && sw.active === false) return false;
        if (filterSchedule === "inactive_sched" && sw.active !== false) return false;
      }
      if (filterSchedule === "active_only" && !u.active) return false;
      if (filterSchedule === "inactive_sched" && u.active) return false;
      return true;
    });
  }, [wpFiltered, taByWashproId, workerByUserId, filterStatus, filterCategoryId, filterRole, filterDept, filterSchedule]);

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
      roles: [...(u.roles || [])]
        .map((c) => String(c || "").trim().toUpperCase())
        .filter(Boolean),
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

  function openTaCreate(linkedWp = null) {
    const wp = linkedWp || null;
    const parts = (wp?.display_name || wp?.username || "").trim().split(/\s+/);
    const fn = parts[0] || "";
    const ln = parts.slice(1).join(" ") || "";
    setTaForm({
      washpro_user_id: wp ? wp.id : "",
      first_name: fn,
      last_name: ln,
      email: wp ? `${String(wp.username).toLowerCase()}.${wp.id}@washpro.local` : "",
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
        geofence_ids: (d.geofence_ids || []).map(Number),
        primary_geofence_id:
          d.primary_geofence_id != null && d.primary_geofence_id !== ""
            ? Number(d.primary_geofence_id)
            : "",
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
      if (payrollUnified) {
        if (!taForm.washpro_user_id) {
          setError(t("people.payrollRequiresLogin"));
          return;
        }
        await createTaUser({
          washpro_user_id: Number(taForm.washpro_user_id),
          first_name: taForm.first_name,
          last_name: taForm.last_name,
          email: taForm.email,
          password: taForm.password,
          role_id: taForm.role_id ? Number(taForm.role_id) : undefined,
          employee_id: taForm.employee_id || null,
          mobile: taForm.mobile || null,
          address: taForm.address || null,
          itin_ssn: taForm.itin_ssn || null,
          hire_date: taForm.hire_date || null,
          termination_date: taForm.termination_date || null,
          rehired: !!taForm.rehired,
          active: taForm.active,
          rehire_parent_user_id: taForm.rehire_parent_id
            ? Number(taForm.rehire_parent_id)
            : null,
          prior_employee_id: taForm.prior_employee_id || null,
        });
      } else {
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
      }
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
      await putUserGeofences(taForm.id, {
        geofence_ids: (taForm.geofence_ids || []).map(Number),
        primary_geofence_id:
          taForm.primary_geofence_id !== "" && taForm.primary_geofence_id != null
            ? Number(taForm.primary_geofence_id)
            : null,
      });
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
        <Typography variant="h5" component="h1">
          {t("people.title")}
        </Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {payrollUnified && canTaView ? t("people.unifiedHelp") : t("people.intro")}
      </Typography>

      {user?.organization_name || user?.organization_slug || user?.organization_id != null ? (
        <Paper variant="outlined" sx={{ p: 1, mb: 1.5 }}>
          <Typography variant="caption" color="text.secondary" display="block">
            {t("people.tenantContext")}
          </Typography>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {user.organization_name || "—"}
            {user.organization_slug ? (
              <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                /login/{user.organization_slug}
              </Typography>
            ) : null}
          </Typography>
          {user.organization_id != null ? (
            <Typography variant="caption" color="text.secondary" display="block">
              organization_id {user.organization_id}
            </Typography>
          ) : null}
        </Paper>
      ) : null}

      <Stack direction={{ xs: "column", lg: "row" }} spacing={1} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <TextField
          size="small"
          label={t("common.search")}
          placeholder={t("people.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 220, flex: "1 1 200px" }}
        />
        {canTaView && payrollUnified ? (
          <>
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>{t("people.filterStatus")}</InputLabel>
              <Select
                label={t("people.filterStatus")}
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
              >
                <MenuItem value="all">{t("people.all")}</MenuItem>
                <MenuItem value="active">{t("common.yes")}</MenuItem>
                <MenuItem value="inactive">{t("common.no")}</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>{t("people.filterCategory")}</InputLabel>
              <Select
                label={t("people.filterCategory")}
                value={filterCategoryId}
                onChange={(e) => setFilterCategoryId(e.target.value)}
              >
                <MenuItem value="">{t("people.all")}</MenuItem>
                {cats.map((c) => (
                  <MenuItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label={t("people.filterRole")}
              value={filterRole}
              onChange={(e) => setFilterRole(e.target.value)}
              sx={{ minWidth: 120 }}
            />
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>{t("people.filterDepartment")}</InputLabel>
              <Select
                label={t("people.filterDepartment")}
                value={filterDept}
                onChange={(e) => setFilterDept(e.target.value)}
              >
                <MenuItem value="">{t("people.all")}</MenuItem>
                {deptCodes.map((d) => (
                  <MenuItem key={d} value={d}>
                    {d}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Scheduling</InputLabel>
              <Select label="Scheduling" value={filterSchedule} onChange={(e) => setFilterSchedule(e.target.value)}>
                <MenuItem value="all">All workers</MenuItem>
                <MenuItem value="ready">Ready for scheduling</MenuItem>
                <MenuItem value="missing_setup">Missing setup</MenuItem>
                <MenuItem value="rate_missing">Rate missing</MenuItem>
                <MenuItem value="w2">W-2</MenuItem>
                <MenuItem value="1099">1099</MenuItem>
                <MenuItem value="temp">Temp</MenuItem>
                <MenuItem value="rinse">Rinse-capable</MenuItem>
                <MenuItem value="dropoff">Drop Off-capable</MenuItem>
                <MenuItem value="folder">Folder skill</MenuItem>
                <MenuItem value="operator">Operator skill</MenuItem>
                <MenuItem value="ot_missing">OT rule missing</MenuItem>
                <MenuItem value="active_only">Active only</MenuItem>
                <MenuItem value="inactive_sched">Inactive (scheduling)</MenuItem>
              </Select>
            </FormControl>
          </>
        ) : null}
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {canTaView && payrollUnified ? (
        <>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            sx={{ mb: 1 }}
            flexWrap="wrap"
            useFlexGap
          >
            <Typography variant="subtitle1">{t("people.unifiedSection")}</Typography>
            <Button variant="contained" onClick={openWpCreate}>
              {t("people.addPerson")}
            </Button>
          </Stack>
          <Paper variant="outlined" sx={{ p: 1, mb: 2 }}>
            <Box className="table-wrapper">
              <Table size="small" className="orders-table">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("people.colEmployeeId")}</TableCell>
                    <TableCell>{t("people.colUsername")}</TableCell>
                    <TableCell>{t("profile.firstName")}</TableCell>
                    <TableCell>{t("profile.lastName")}</TableCell>
                    <TableCell>{t("people.colEmail")}</TableCell>
                    <TableCell>{t("people.colRole")}</TableCell>
                    <TableCell>Scheduling</TableCell>
                    <TableCell>{t("people.colStatus")}</TableCell>
                    <TableCell align="right" sx={{ width: 48 }}>
                      {t("people.colActions")}
                    </TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {unifiedFiltered.map((u) => {
                    const ta = taByWashproId.get(u.id);
                    return (
                      <TableRow key={u.id}>
                        <TableCell>{ta?.employee_id || "—"}</TableCell>
                        <TableCell>{u.username || "—"}</TableCell>
                        <TableCell>{ta?.first_name || "—"}</TableCell>
                        <TableCell>{ta?.last_name || "—"}</TableCell>
                        <TableCell>{ta?.email || "—"}</TableCell>
                        <TableCell>
                          <Typography variant="body2" color="text.secondary">
                            {ta?.role_name || (u.roles || []).join(", ") || "—"}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <SchedulingReadinessChip worker={workerByUserId.get(u.id)} />
                        </TableCell>
                        <TableCell>{formatEmploymentStatusCell(ta, u.active, t)}</TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            aria-label={t("people.colActions")}
                            onClick={(e) => {
                              setRowMenuAnchor(e.currentTarget);
                              setRowMenuCtx({ wpUser: u, ta, unified: true });
                            }}
                          >
                            <MoreVert fontSize="small" />
                          </IconButton>
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
        <>
          <Typography variant="h6" sx={{ mb: 1 }}>
            {t("people.washproSection")}
          </Typography>
          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
            <Button variant="contained" onClick={openWpCreate}>
              {t("people.addPerson")}
            </Button>
          </Stack>
          <Paper variant="outlined" sx={{ p: 1, mb: 2 }}>
            <Box className="table-wrapper">
              <Table size="small" className="orders-table">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("people.colUsername")}</TableCell>
                    <TableCell>{t("people.colDisplay")}</TableCell>
                    <TableCell>{t("people.colRoles")}</TableCell>
                    <TableCell>{t("people.colPayrollLink")}</TableCell>
                    <TableCell>{t("people.colStatus")}</TableCell>
                    <TableCell align="right" sx={{ width: 48 }}>
                      {t("people.colActions")}
                    </TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {wpFiltered.map((u) => {
                    const ta = taByWashproId.get(u.id);
                    return (
                      <TableRow key={u.id}>
                        <TableCell>{u.username || "—"}</TableCell>
                        <TableCell>{u.display_name || "—"}</TableCell>
                        <TableCell>
                          <Typography variant="body2" color="text.secondary">
                            {(u.roles || []).join(", ") || "—"}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          {ta ? (
                            <>
                              {ta.first_name} {ta.last_name}
                              <Typography variant="caption" display="block" color="text.secondary">
                                #{ta.id}
                              </Typography>
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>{formatEmploymentStatusCell(ta, u.active, t)}</TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            aria-label={t("people.colActions")}
                            onClick={(e) => {
                              setRowMenuAnchor(e.currentTarget);
                              setRowMenuCtx({ wpUser: u, ta, unified: false });
                            }}
                          >
                            <MoreVert fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          </Paper>
        </>
      )}

      {canTaView && !payrollUnified ? (
        <>
          <Typography variant="h6" sx={{ mb: 1 }}>
            {t("people.taSection")}
          </Typography>
          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
            {canTaAdd ? (
              <Button variant="outlined" onClick={() => openTaCreate()}>
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
                    <TableCell>{t("people.colStatus")}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {taFiltered.map((u) => {
                    const wpLoginId = u.washpro_user_id || u.user_id || u.id;
                    const wp = washproById.get(wpLoginId);
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
                              {wp.display_name && String(wp.display_name).trim() !== String(wp.username || "").trim() ? (
                                <Typography variant="caption" display="block" color="text.secondary">
                                  {wp.display_name}
                                </Typography>
                              ) : null}
                              <Typography variant="caption" display="block" color="text.secondary">
                                WP #{wp.id}
                              </Typography>
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>{formatEmploymentStatusCell(u, wp?.active ?? true, t)}</TableCell>
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
      ) : null}

      {!canTaView ? (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t("people.needView")}
        </Alert>
      ) : null}

      <Menu
        anchorEl={rowMenuAnchor}
        open={Boolean(rowMenuAnchor && rowMenuCtx)}
        onClose={() => {
          setRowMenuAnchor(null);
          setRowMenuCtx(null);
        }}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <MenuItem
          onClick={() => {
            const wu = rowMenuCtx?.wpUser;
            setRowMenuAnchor(null);
            setRowMenuCtx(null);
            if (wu?.id != null) navigate(`/employees/${wu.id}`);
          }}
        >
          {t("people.actionView")}
        </MenuItem>
        <MenuItem
          onClick={() => {
            const wu = rowMenuCtx?.wpUser;
            setRowMenuAnchor(null);
            setRowMenuCtx(null);
            if (wu?.id != null) navigate(`/employees/${wu.id}`);
          }}
        >
          {t("people.actionEdit")}
        </MenuItem>
        <MenuItem
          sx={{ color: "error.main" }}
          onClick={() => {
            const wu = rowMenuCtx?.wpUser;
            setRowMenuAnchor(null);
            setRowMenuCtx(null);
            if (wu?.id != null) setDeleteWpId(wu.id);
          }}
        >
          {t("common.delete")}
        </MenuItem>
      </Menu>

      <Dialog open={wpDialog === "create"} onClose={() => setWpDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{t("people.dialogNewLaundryOpsLogin")}</DialogTitle>
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
            <WashproRolesMultiSelect
              label="Roles"
              value={wpForm.roles || []}
              onChange={(roles) => setWpForm((p) => ({ ...p, roles }))}
              roles={wpRoles}
            />
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
        <DialogTitle>{t("people.dialogEditLaundryOpsLogin")}</DialogTitle>
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
            <WashproRolesMultiSelect
              label="Roles"
              value={wpForm.roles || []}
              onChange={(roles) => setWpForm((p) => ({ ...p, roles }))}
              roles={wpRoles}
            />
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
        <DialogTitle>{t("people.dialogDeleteLaundryOpsLogin")}</DialogTitle>
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
            {payrollUnified ? (
              <FormControl fullWidth required>
                <InputLabel id="wp-link">{t("people.linkWashproLogin")}</InputLabel>
                <Select
                  labelId="wp-link"
                  label={t("people.linkWashproLogin")}
                  value={
                    taForm.washpro_user_id === "" || taForm.washpro_user_id == null
                      ? ""
                      : String(taForm.washpro_user_id)
                  }
                  onChange={(e) => {
                    const v = e.target.value;
                    const wp = wpUsers.find((w) => String(w.id) === String(v));
                    const prts = (wp?.display_name || wp?.username || "").trim().split(/\s+/);
                    setTaForm((f) => ({
                      ...f,
                      washpro_user_id: v === "" ? "" : Number(v),
                      first_name: prts[0] || f.first_name,
                      last_name: prts.slice(1).join(" ") || f.last_name,
                      email: wp
                        ? `${String(wp.username).toLowerCase()}.${wp.id}@washpro.local`
                        : f.email,
                    }));
                  }}
                >
                  <MenuItem value="">—</MenuItem>
                  {wpUsers
                    .filter((w) => !taByWashproId.get(w.id))
                    .map((w) => (
                      <MenuItem key={w.id} value={String(w.id)}>
                        {w.username} — {w.display_name || w.username}
                      </MenuItem>
                    ))}
                </Select>
              </FormControl>
            ) : null}
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
          <Button
            variant="contained"
            onClick={saveTaCreate}
            disabled={
              !taForm.first_name ||
              !taForm.last_name ||
              !taForm.email ||
              !taForm.password ||
              !taForm.role_id ||
              (payrollUnified && !taForm.washpro_user_id)
            }
          >
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
                onChange={(e) => {
                  const raw = e.target.value;
                  const next = (typeof raw === "string" ? raw.split(",") : raw).map(Number);
                  setTaForm((prev) => ({
                    ...prev,
                    geofence_ids: next,
                    primary_geofence_id:
                      prev.primary_geofence_id !== "" &&
                      prev.primary_geofence_id != null &&
                      next.includes(Number(prev.primary_geofence_id))
                        ? prev.primary_geofence_id
                        : "",
                  }));
                }}
                input={<OutlinedInput label="Geofences" />}
                renderValue={(selected) =>
                  selected
                    .map((id) => geofences.find((g) => Number(g.id) === Number(id))?.name || id)
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
            <FormControl fullWidth>
              <InputLabel id="primary-gf-label">Primary geofence</InputLabel>
              <Select
                labelId="primary-gf-label"
                label="Primary geofence"
                value={
                  taForm.primary_geofence_id !== "" && taForm.primary_geofence_id != null
                    ? String(taForm.primary_geofence_id)
                    : ""
                }
                onChange={(e) =>
                  setTaForm({
                    ...taForm,
                    primary_geofence_id: e.target.value === "" ? "" : Number(e.target.value),
                  })
                }
              >
                <MenuItem value="">
                  <em>—</em>
                </MenuItem>
                {(taForm.geofence_ids || []).map((id) => {
                  const g = geofences.find((x) => Number(x.id) === Number(id));
                  return g ? (
                    <MenuItem key={g.id} value={String(g.id)}>
                      {g.name}
                    </MenuItem>
                  ) : null;
                })}
              </Select>
            </FormControl>
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
