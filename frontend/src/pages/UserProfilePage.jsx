import { useCallback, useEffect, useMemo, useState } from "react";
import { useMatch, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowBack, Add, DeleteOutline } from "@mui/icons-material";
import {
  createTaUser,
  deleteTaUser,
  getAuthUser,
  getEmploymentCategories,
  getGeofences,
  getPlatformOrganizations,
  getPlatformUserProfile,
  getRoles,
  getTaRoles,
  getTaUser,
  putPlatformUserProfile,
  putUserEmploymentCategories,
  putUserEntityTags,
  putUserGeofences,
  updateTaUser,
  updateUser,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function emptyTagRow() {
  return { entity_type: "", entity_key: "", label: "" };
}

export default function UserProfilePage({ user: sessionUser }) {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { hasPerm } = useAuth();
  const platformMode = Boolean(useMatch("/platform/users/:userId"));

  const uid = Number(userId);
  const isAdmin = (sessionUser?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN");
  const canTaView = hasPerm("users.view");
  const canTaEdit = hasPerm("users.edit");
  const canTaAdd = hasPerm("users.add");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [removingPayroll, setRemovingPayroll] = useState(false);
  const [error, setError] = useState("");
  const [hasPayroll, setHasPayroll] = useState(false);

  const [orgOptions, setOrgOptions] = useState([]);
  const [organizationId, setOrganizationId] = useState("");

  const [wpUsername, setWpUsername] = useState("");
  const [wpDisplay, setWpDisplay] = useState("");
  const [wpActive, setWpActive] = useState(true);
  const [wpRoles, setWpRoles] = useState([]);
  const [wpPassword, setWpPassword] = useState("");

  const [washproRoleChoices, setWashproRoleChoices] = useState([]);
  const [taRoleChoices, setTaRoleChoices] = useState([]);
  const [geofences, setGeofences] = useState([]);
  const [cats, setCats] = useState([]);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [mobile, setMobile] = useState("");
  const [address, setAddress] = useState("");
  const [itinSsn, setItinSsn] = useState("");
  const [hireDate, setHireDate] = useState("");
  const [termDate, setTermDate] = useState("");
  const [rehired, setRehired] = useState(false);
  const [payrollActive, setPayrollActive] = useState(true);
  const [roleId, setRoleId] = useState("");
  const [payrollPassword, setPayrollPassword] = useState("");
  const [rehireParentId, setRehireParentId] = useState("");
  const [priorEmployeeId, setPriorEmployeeId] = useState("");

  const [geofenceIds, setGeofenceIds] = useState([]);
  const [primaryGeofenceId, setPrimaryGeofenceId] = useState("");
  const [catRows, setCatRows] = useState([
    { employment_category_id: "", effective_from: new Date().toISOString().slice(0, 10), effective_to: "" },
  ]);

  const [entityTags, setEntityTags] = useState([emptyTagRow()]);

  const canUse = useMemo(() => {
    if (platformMode) return true;
    return isAdmin;
  }, [platformMode, isAdmin]);

  const seedFromTa = useCallback((ta, auth) => {
    setHasPayroll(true);
    setFirstName(ta.first_name || "");
    setLastName(ta.last_name || "");
    setEmail(ta.email || "");
    setEmployeeId(ta.employee_id || "");
    setMobile(ta.mobile || "");
    setAddress(ta.address || "");
    setItinSsn(ta.itin_ssn || "");
    setHireDate(ta.hire_date ? String(ta.hire_date).slice(0, 10) : "");
    setTermDate(ta.termination_date ? String(ta.termination_date).slice(0, 10) : "");
    setRehired(!!ta.rehired);
    setPayrollActive(!!ta.active);
    setRoleId(ta.role_id != null ? String(ta.role_id) : "");
    setRehireParentId(
      ta.rehire_parent_user_id != null && ta.rehire_parent_user_id !== ""
        ? String(ta.rehire_parent_user_id)
        : ta.rehire_parent_id != null && ta.rehire_parent_id !== ""
          ? String(ta.rehire_parent_id)
          : "",
    );
    setPriorEmployeeId(ta.prior_employee_id || "");
    setGeofenceIds((ta.geofence_ids || []).map(Number));
    setPrimaryGeofenceId(
      ta.primary_geofence_id != null && ta.primary_geofence_id !== "" ? Number(ta.primary_geofence_id) : "",
    );
    const assigns = ta.employment_assignments || [];
    setCatRows(
      assigns.length > 0
        ? assigns.map((a) => ({
            employment_category_id: a.employment_category_id,
            effective_from: String(a.effective_from).slice(0, 10),
            effective_to: a.effective_to ? String(a.effective_to).slice(0, 10) : "",
          }))
        : [
            {
              employment_category_id: "",
              effective_from: new Date().toISOString().slice(0, 10),
              effective_to: "",
            },
          ],
    );
    const tags = ta.entity_tags || auth?.entity_tags || [];
    setEntityTags(tags.length ? tags.map((x) => ({ ...x })) : [emptyTagRow()]);
  }, [uid]);

  const load = useCallback(async () => {
    if (!userId || Number.isNaN(uid)) return;
    setLoading(true);
    setError("");
    try {
      if (platformMode) {
        const [profRes, orgRes] = await Promise.all([
          getPlatformUserProfile(uid),
          getPlatformOrganizations(),
        ]);
        const bundle = profRes.data;
        setOrgOptions(orgRes.data?.organizations || []);
        const w = bundle.washpro || {};
        setOrganizationId(String(w.organization_id ?? ""));
        setWpUsername(w.username || "");
        setWpDisplay(w.display_name || "");
        setWpActive(!!w.active);
        setWpRoles([...(w.roles || [])]);
        setWpPassword("");
        setWashproRoleChoices(
          (bundle.roles_catalog || []).map((r) => ({ code: r.code, name: r.name, id: r.id })),
        );
        setHasPayroll(false);
        return;
      }

      const authRes = await getAuthUser(uid);
      const auth = authRes.data;
      setWpUsername(auth.username || "");
      setWpDisplay(auth.display_name || "");
      setWpActive(!!auth.active);
      setWpRoles([...(auth.roles || [])]);
      setWpPassword("");

      const [rRes, gRes, cRes] = await Promise.all([getRoles(), getGeofences(), getEmploymentCategories()]);
      setWashproRoleChoices(rRes.data || []);
      setGeofences(gRes.data || []);
      setCats(cRes.data || []);

      let taRoles = [];
      try {
        const tr = await getTaRoles();
        taRoles = tr.data || [];
      } catch {
        taRoles = [];
      }
      setTaRoleChoices(taRoles);

      let ta = null;
      if (canTaView) {
        try {
          const taRes = await getTaUser(uid);
          ta = taRes.data;
        } catch (e) {
          if (e?.response?.status !== 404) throw e;
        }
      }

      if (ta) {
        seedFromTa(ta, auth);
      } else {
        setHasPayroll(false);
        const parts = String(auth.display_name || auth.username || "").trim().split(/\s+/);
        setFirstName(parts[0] || "");
        setLastName(parts.slice(1).join(" ") || "");
        setEmail("");
        setGeofenceIds((auth.geofence_ids || []).map(Number));
        setPrimaryGeofenceId(
          auth.primary_geofence_id != null && auth.primary_geofence_id !== ""
            ? Number(auth.primary_geofence_id)
            : "",
        );
        const assigns = auth.employment_assignments || [];
        setCatRows(
          assigns.length > 0
            ? assigns.map((a) => ({
                employment_category_id: a.employment_category_id,
                effective_from: String(a.effective_from).slice(0, 10),
                effective_to: a.effective_to ? String(a.effective_to).slice(0, 10) : "",
              }))
            : [
                {
                  employment_category_id: cRes.data?.[0]?.id || "",
                  effective_from: new Date().toISOString().slice(0, 10),
                  effective_to: "",
                },
              ],
        );
        const tags = auth.entity_tags || [];
        setEntityTags(tags.length ? tags.map((x) => ({ ...x })) : [emptyTagRow()]);
      }
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, [userId, uid, platformMode, canTaView, seedFromTa]);

  useEffect(() => {
    if (!canUse) return;
    load();
  }, [canUse, load]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      const tagsPayload = (entityTags || [])
        .filter((x) => String(x.entity_type || "").trim() && String(x.entity_key || "").trim())
        .map((x) => ({
          entity_type: String(x.entity_type).trim(),
          entity_key: String(x.entity_key).trim(),
          label: String(x.label || "").trim() || null,
        }));

      if (platformMode) {
        const oid = organizationId === "" ? undefined : Number(organizationId);
        const washpro = {
          username: wpUsername.trim(),
          display_name: wpDisplay.trim(),
          active: wpActive,
          roles: wpRoles,
        };
        if (wpPassword.trim()) washpro.password = wpPassword.trim();
        await putPlatformUserProfile(uid, { organization_id: oid, washpro });
        await load();
        return;
      }

      if (!isAdmin) {
        setError(t("people.onlyAdmin"));
        return;
      }
      await updateUser(uid, {
        username: wpUsername.trim(),
        display_name: wpDisplay.trim(),
        active: wpActive,
        roles: wpRoles,
        password: wpPassword.trim() || undefined,
      });

      if (hasPayroll && canTaEdit) {
        await updateTaUser(uid, {
          first_name: firstName,
          last_name: lastName,
          email: email.trim(),
          mobile: mobile || null,
          employee_id: employeeId || null,
          address: address || null,
          itin_ssn: itinSsn || null,
          hire_date: hireDate || null,
          termination_date: termDate || null,
          rehired,
          active: payrollActive,
          role_id: roleId ? Number(roleId) : undefined,
          password: payrollPassword.trim() || undefined,
          rehire_parent_id: rehireParentId === "" ? null : Number(rehireParentId),
          prior_employee_id: priorEmployeeId || null,
        });
      } else if (!hasPayroll && canTaAdd) {
        const wantsProfile =
          firstName.trim() &&
          lastName.trim() &&
          email.trim() &&
          payrollPassword.trim() &&
          roleId;
        if (wantsProfile) {
          await createTaUser({
            washpro_user_id: uid,
            first_name: firstName.trim(),
            last_name: lastName.trim(),
            email: email.trim().toLowerCase(),
            password: payrollPassword.trim(),
            role_id: Number(roleId),
            employee_id: employeeId || null,
            mobile: mobile || null,
            address: address || null,
            itin_ssn: itinSsn || null,
            hire_date: hireDate || null,
            termination_date: termDate || null,
            rehired,
            active: payrollActive,
            rehire_parent_user_id: rehireParentId === "" ? null : Number(rehireParentId),
            prior_employee_id: priorEmployeeId || null,
          });
        }
      }

      if (canTaEdit) {
        await putUserGeofences(uid, {
          geofence_ids: geofenceIds.map(Number),
          primary_geofence_id:
            primaryGeofenceId !== "" && primaryGeofenceId != null ? Number(primaryGeofenceId) : null,
        });
        await putUserEmploymentCategories(uid, {
          assignments: catRows
            .filter((r) => r.employment_category_id)
            .map((r) => ({
              employment_category_id: Number(r.employment_category_id),
              effective_from: r.effective_from,
              effective_to: r.effective_to || null,
            })),
        });
        await putUserEntityTags(uid, { tags: tagsPayload });
      }

      await load();
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function removePayrollProfile() {
    if (!hasPayroll || !canTaEdit || platformMode) return;
    if (!window.confirm(t("profile.confirmRemovePayroll"))) return;
    setRemovingPayroll(true);
    setError("");
    try {
      await deleteTaUser(uid);
      await load();
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Remove failed");
    } finally {
      setRemovingPayroll(false);
    }
  }

  if (!canUse) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("people.onlyAdmin")}</Alert>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography>{t("profile.loading")}</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 920, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <IconButton size="small" onClick={() => navigate(platformMode ? "/platform" : "/employees")}>
          <ArrowBack />
        </IconButton>
        <Typography sx={{ fontSize: 26, fontWeight: 700 }}>
          {platformMode ? t("profile.platformTitle") : t("profile.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          #{uid}
        </Typography>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Stack spacing={2}>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            {t("profile.sectionLogin")}
          </Typography>
          <Stack spacing={1.5}>
            {platformMode ? (
              <FormControl fullWidth size="small">
                <InputLabel id="org-pick">{t("profile.organization")}</InputLabel>
                <Select
                  labelId="org-pick"
                  label={t("profile.organization")}
                  value={organizationId}
                  onChange={(e) => setOrganizationId(e.target.value)}
                >
                  {(orgOptions || []).map((o) => (
                    <MenuItem key={o.id} value={String(o.id)}>
                      {o.display_name || o.slug} (#{o.id})
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            ) : null}
            <TextField
              label={t("people.colUsername")}
              value={wpUsername}
              onChange={(e) => setWpUsername(e.target.value)}
              size="small"
              required
            />
            <TextField
              label={t("people.colDisplay")}
              value={wpDisplay}
              onChange={(e) => setWpDisplay(e.target.value)}
              size="small"
            />
            <TextField
              label={t("profile.newPasswordOptional")}
              type="password"
              value={wpPassword}
              onChange={(e) => setWpPassword(e.target.value)}
              size="small"
            />
            <FormControl fullWidth size="small">
              <InputLabel id="roles-pick">{t("people.colRoles")}</InputLabel>
              <Select
                labelId="roles-pick"
                multiple
                label={t("people.colRoles")}
                value={wpRoles}
                onChange={(e) => setWpRoles(typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value)}
                input={<OutlinedInput label={t("people.colRoles")} />}
                renderValue={(sel) => sel.join(", ")}
              >
                {washproRoleChoices.map((r) => (
                  <MenuItem key={r.code} value={r.code}>
                    {r.code}{r.name && r.name !== r.code ? ` — ${r.name}` : ""}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControlLabel
              control={<Checkbox checked={wpActive} onChange={(e) => setWpActive(e.target.checked)} />}
              label={t("common.active")}
            />
          </Stack>
        </Paper>

        {platformMode ? (
          <Alert severity="info" variant="outlined">
            {t("profile.platformLoginOnly")}
          </Alert>
        ) : null}

        {!platformMode ? (
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            {t("profile.sectionPayroll")}
          </Typography>
          {!hasPayroll && !platformMode ? (
            <Alert severity="info" sx={{ mb: 1 }}>
              {t("profile.noPayrollYet")}
            </Alert>
          ) : null}
          <Stack spacing={1.5}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("profile.firstName")}
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                size="small"
                fullWidth
              />
              <TextField
                label={t("profile.lastName")}
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                size="small"
                fullWidth
              />
            </Stack>
            <TextField
              label={t("people.colEmail")}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              size="small"
              fullWidth
            />
            <TextField
              label={t("profile.payrollPasswordHint")}
              type="password"
              value={payrollPassword}
              onChange={(e) => setPayrollPassword(e.target.value)}
              size="small"
              helperText={hasPayroll ? t("profile.payrollPasswordEdit") : t("profile.payrollPasswordCreate")}
            />
            <TextField
              select
              label={t("people.colRole")}
              value={roleId}
              onChange={(e) => setRoleId(e.target.value)}
              size="small"
            >
              <MenuItem value="">—</MenuItem>
              {taRoleChoices.map((r) => (
                <MenuItem key={r.id} value={String(r.id)}>
                  {r.name || r.code}
                </MenuItem>
              ))}
            </TextField>
            <TextField label="Employee ID" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} size="small" />
            <TextField label="Mobile" value={mobile} onChange={(e) => setMobile(e.target.value)} size="small" />
            <TextField
              label="Address"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              size="small"
              multiline
              minRows={2}
            />
            <TextField label="ITIN / SSN" value={itinSsn} onChange={(e) => setItinSsn(e.target.value)} size="small" />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("profile.hireDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={hireDate}
                onChange={(e) => setHireDate(e.target.value)}
                size="small"
                fullWidth
              />
              <TextField
                label={t("profile.termDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={termDate}
                onChange={(e) => setTermDate(e.target.value)}
                size="small"
                fullWidth
              />
            </Stack>
            <TextField
              label={t("people.rehireFrom")}
              value={rehireParentId}
              onChange={(e) => setRehireParentId(e.target.value)}
              size="small"
              helperText={t("profile.rehireParentHint")}
            />
            <TextField
              label={t("people.priorEmpId")}
              value={priorEmployeeId}
              onChange={(e) => setPriorEmployeeId(e.target.value)}
              size="small"
            />
            <FormControlLabel
              control={<Checkbox checked={rehired} onChange={(e) => setRehired(e.target.checked)} />}
              label="Rehired"
            />
            <FormControlLabel
              control={<Checkbox checked={payrollActive} onChange={(e) => setPayrollActive(e.target.checked)} />}
              label={t("profile.payrollRecordActive")}
            />
            {hasPayroll && canTaEdit ? (
              <Button
                variant="outlined"
                color="inherit"
                startIcon={<DeleteOutline />}
                onClick={removePayrollProfile}
                disabled={removingPayroll}
                sx={{ alignSelf: "flex-start", borderColor: "divider", color: "text.secondary" }}
              >
                {removingPayroll ? t("common.saving") : t("profile.removePayrollProfile")}
              </Button>
            ) : null}
          </Stack>
        </Paper>
        ) : null}

        {canTaView && !platformMode ? (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
              {t("profile.sectionGeofences")}
            </Typography>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel id="gf-m">Geofences</InputLabel>
              <Select
                labelId="gf-m"
                multiple
                value={geofenceIds}
                onChange={(e) => {
                  const raw = e.target.value;
                  const next = (typeof raw === "string" ? raw.split(",") : raw).map(Number);
                  setGeofenceIds(next);
                  if (primaryGeofenceId !== "" && primaryGeofenceId != null && !next.includes(Number(primaryGeofenceId))) {
                    setPrimaryGeofenceId("");
                  }
                }}
                input={<OutlinedInput label="Geofences" />}
                renderValue={(selected) =>
                  selected.map((id) => geofences.find((g) => Number(g.id) === Number(id))?.name || id).join(", ")
                }
              >
                {geofences.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel id="pgf">Primary geofence</InputLabel>
              <Select
                labelId="pgf"
                label="Primary geofence"
                value={primaryGeofenceId === "" || primaryGeofenceId == null ? "" : String(primaryGeofenceId)}
                onChange={(e) =>
                  setPrimaryGeofenceId(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <MenuItem value="">
                  <em>—</em>
                </MenuItem>
                {geofenceIds.map((id) => {
                  const g = geofences.find((x) => Number(x.id) === Number(id));
                  return g ? (
                    <MenuItem key={g.id} value={String(g.id)}>
                      {g.name}
                    </MenuItem>
                  ) : null;
                })}
              </Select>
            </FormControl>
          </Paper>
        ) : null}

        {canTaView && !platformMode ? (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
              {t("profile.sectionEmployment")}
            </Typography>
            {(catRows || []).map((row, i) => (
              <Stack key={i} direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
                <TextField
                  select
                  label="Category"
                  value={row.employment_category_id}
                  onChange={(e) => {
                    const next = [...catRows];
                    next[i] = { ...next[i], employment_category_id: e.target.value };
                    setCatRows(next);
                  }}
                  size="small"
                  sx={{ minWidth: 200 }}
                >
                  <MenuItem value="">—</MenuItem>
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
                    const next = [...catRows];
                    next[i] = { ...next[i], effective_from: e.target.value };
                    setCatRows(next);
                  }}
                  size="small"
                />
                <TextField
                  type="date"
                  label="To"
                  InputLabelProps={{ shrink: true }}
                  value={row.effective_to || ""}
                  onChange={(e) => {
                    const next = [...catRows];
                    next[i] = { ...next[i], effective_to: e.target.value };
                    setCatRows(next);
                  }}
                  size="small"
                />
              </Stack>
            ))}
          </Paper>
        ) : null}

        {canTaView && !platformMode ? (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {t("profile.sectionEntities")}
              </Typography>
              <Button size="small" startIcon={<Add />} onClick={() => setEntityTags([...entityTags, emptyTagRow()])}>
                {t("profile.addEntityTag")}
              </Button>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t("profile.entityTagsHelp")}
            </Typography>
            {entityTags.map((row, i) => (
              <Stack key={i} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1 }}>
                <TextField
                  label={t("profile.entityType")}
                  value={row.entity_type || ""}
                  onChange={(e) => {
                    const next = [...entityTags];
                    next[i] = { ...next[i], entity_type: e.target.value };
                    setEntityTags(next);
                  }}
                  size="small"
                  sx={{ flex: 1 }}
                />
                <TextField
                  label={t("profile.entityKey")}
                  value={row.entity_key || ""}
                  onChange={(e) => {
                    const next = [...entityTags];
                    next[i] = { ...next[i], entity_key: e.target.value };
                    setEntityTags(next);
                  }}
                  size="small"
                  sx={{ flex: 1 }}
                />
                <TextField
                  label={t("profile.entityLabel")}
                  value={row.label || ""}
                  onChange={(e) => {
                    const next = [...entityTags];
                    next[i] = { ...next[i], label: e.target.value };
                    setEntityTags(next);
                  }}
                  size="small"
                  sx={{ flex: 1 }}
                />
                <IconButton
                  aria-label="remove"
                  onClick={() => setEntityTags(entityTags.filter((_, j) => j !== i))}
                  disabled={entityTags.length <= 1}
                >
                  <DeleteOutline />
                </IconButton>
              </Stack>
            ))}
          </Paper>
        ) : null}

        <Divider />
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button variant="outlined" onClick={() => navigate(platformMode ? "/platform" : "/employees")}>
            {t("common.cancel")}
          </Button>
          <Button variant="contained" onClick={save} disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}
