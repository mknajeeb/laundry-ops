import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  Paper,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Switch,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import {
  createPlatformOrganization,
  createPlatformRole,
  deletePlatformOrganization,
  deletePlatformRole,
  getPlatformEntitlements,
  getPlatformOrganizations,
  getPlatformPermissionMatrix,
  putPlatformEntitlements,
  putPlatformOrganization,
  putPlatformRolePermissions,
  searchPlatformUsers,
  uploadPlatformOrganizationLogo,
} from "../api";
import PermissionMatrixHierarchy from "../components/PermissionMatrixHierarchy";
import { TENANT_MODULES } from "../constants/tenantModules";
import { useI18n } from "../i18n/I18nContext";

function teamLoginHref(slug) {
  if (!slug) return "";
  return `${window.location.origin}/login/${encodeURIComponent(String(slug).toLowerCase())}`;
}

function groupPermKey(key) {
  const i = String(key).indexOf(".");
  return i === -1 ? "other" : key.slice(0, i);
}

function PlatformRolePackagesPanel() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [roleId, setRoleId] = useState("");
  const [selected, setSelected] = useState({});
  const [createOpen, setCreateOpen] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const res = await getPlatformPermissionMatrix();
      setData(res.data);
      const roles = res.data?.roles || [];
      setRoleId((prev) => {
        const prevStr = prev == null || prev === "" ? "" : String(prev);
        if (prevStr && roles.some((r) => String(r.id) === prevStr)) return prevStr;
        return roles[0] != null ? String(roles[0].id) : "";
      });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /** When API roles load, ensure roleId always matches a real role (fixes blank native Select). */
  useEffect(() => {
    const list = data?.roles || [];
    if (!list.length || data === null || loading) return;
    const rid = roleId === "" || roleId == null ? "" : String(roleId);
    if (list.some((r) => String(r.id) === rid)) return;
    setRoleId(String(list[0].id));
  }, [data, loading, roleId]);

  const keysForRole = useMemo(() => {
    if (!data || !roleId) return [];
    const m = data.role_permissions || {};
    return m[roleId] || m[String(roleId)] || [];
  }, [data, roleId]);

  useEffect(() => {
    const next = {};
    (data?.permissions || []).forEach((p) => {
      next[p.perm_key] = keysForRole.includes(p.perm_key);
    });
    setSelected(next);
  }, [data, keysForRole, roleId]);

  const groupedFlat = useMemo(() => {
    const g = {};
    (data?.permissions || []).forEach((p) => {
      const grp = groupPermKey(p.perm_key);
      if (!g[grp]) g[grp] = [];
      g[grp].push(p);
    });
    return g;
  }, [data]);

  const selectedRole = useMemo(
    () => (data?.roles || []).find((r) => String(r.id) === String(roleId)),
    [data, roleId],
  );

  const canDeleteRole = selectedRole && !selectedRole.is_system;

  async function save() {
    if (!roleId) return;
    setSaving(true);
    setError("");
    try {
      const permission_keys = Object.entries(selected)
        .filter(([, on]) => on)
        .map(([k]) => k);
      await putPlatformRolePermissions(Number(roleId), permission_keys);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateRole() {
    setCreating(true);
    setError("");
    try {
      await createPlatformRole({
        code: newCode.trim(),
        name: newName.trim() || undefined,
      });
      setCreateOpen(false);
      setNewCode("");
      setNewName("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteRole() {
    if (!roleId || !canDeleteRole) return;
    if (!window.confirm(t("permissions.confirmDeleteRole"))) return;
    setSaving(true);
    setError("");
    try {
      await deletePlatformRole(Number(roleId));
      setRoleId("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  const hierarchy = data?.hierarchy;
  const roles = data?.roles || [];
  const bootstrapping = data === null && loading;
  const roleIdStr = roleId === "" || roleId == null ? "" : String(roleId);
  const selectValue = roles.some((r) => String(r.id) === roleIdStr) ? roleIdStr : "";
  const builtInRoles = roles.filter((r) => r.is_system);
  const customRoles = roles.filter((r) => !r.is_system);

  return (
    <Box>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Stack spacing={1} sx={{ mb: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="flex-start">
            <FormControl sx={{ minWidth: 280 }} variant="outlined" size="small">
              <InputLabel id="platform-role-pick">{t("permissions.role")}</InputLabel>
              <Select
                labelId="platform-role-pick"
                label={t("permissions.role")}
                native
                value={bootstrapping || roles.length === 0 ? "" : selectValue}
                disabled={bootstrapping || roles.length === 0 || (!!error && !data)}
                onChange={(e) => setRoleId(String(e.target.value))}
                inputProps={{ id: "platform-role-native-select", name: "platform_role" }}
              >
                {bootstrapping ? (
                  <option value="">{t("platformOrgs.loading")}</option>
                ) : error && !data ? (
                  <option value="">{t("permissions.matrixLoadError")}</option>
                ) : roles.length === 0 ? (
                  <option value="">{t("permissions.noRoles")}</option>
                ) : (
                  [
                    builtInRoles.length ? (
                      <optgroup key="built-in" label={t("permissions.roleGroupBuiltIn")}>
                        {builtInRoles.map((r) => (
                          <option key={r.id} value={String(r.id)}>
                            {r.code} — {r.name}
                          </option>
                        ))}
                      </optgroup>
                    ) : null,
                    customRoles.length ? (
                      <optgroup key="custom" label={t("permissions.roleGroupCustom")}>
                        {customRoles.map((r) => (
                          <option key={r.id} value={String(r.id)}>
                            {r.code} — {r.name}
                          </option>
                        ))}
                      </optgroup>
                    ) : null,
                  ]
                )}
              </Select>
            </FormControl>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="contained" onClick={save} disabled={saving || !roleId}>
                {saving ? t("common.saving") : t("permissions.save")}
              </Button>
              <Button variant="outlined" onClick={() => setCreateOpen(true)}>
                {t("permissions.createRole")}
              </Button>
              <Button
                variant="outlined"
                color="inherit"
                disabled={!canDeleteRole || saving}
                onClick={handleDeleteRole}
                sx={{ borderColor: "divider" }}
              >
                {t("permissions.deleteRole")}
              </Button>
            </Stack>
          </Stack>
        </Stack>

        <PermissionMatrixHierarchy
          t={t}
          hierarchy={hierarchy}
          groupedFlat={groupedFlat}
          flatPermissions={data?.permissions}
          selected={selected}
          setSelected={setSelected}
          readOnly={false}
          layoutVariant="flatFunctionality"
        />
      </Paper>

      <Dialog open={createOpen} onClose={() => !creating && setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t("permissions.createRole")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t("permissions.newRoleCode")}
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              placeholder="e.g. FLOOR_SUPERVISOR"
              autoFocus
              fullWidth
            />
            <TextField
              label={t("permissions.newRoleName")}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t("permissions.newRoleNamePlaceholder")}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)} disabled={creating}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="contained"
            onClick={handleCreateRole}
            disabled={creating || !newCode.trim()}
          >
            {creating ? t("common.saving") : t("common.add")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default function PlatformAdminPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [mainTab, setMainTab] = useState(0);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [creating, setCreating] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [editName, setEditName] = useState("");
  const [editActive, setEditActive] = useState(true);
  const [editAddress, setEditAddress] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [modules, setModules] = useState({});
  const [savingEdit, setSavingEdit] = useState(false);
  const [userSearchQ, setUserSearchQ] = useState("");
  const [userHits, setUserHits] = useState([]);
  const [userSearchLoading, setUserSearchLoading] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoErr, setLogoErr] = useState("");

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const res = await getPlatformOrganizations();
      setRows(res.data?.organizations || []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Load failed");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (mainTab !== 2) return;
    let cancelled = false;
    (async () => {
      setUserSearchLoading(true);
      try {
        const res = await searchPlatformUsers("");
        if (!cancelled) setUserHits(Array.isArray(res.data) ? res.data : []);
      } catch {
        if (!cancelled) setUserHits([]);
      } finally {
        if (!cancelled) setUserSearchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mainTab]);

  async function runUserSearch() {
    setUserSearchLoading(true);
    try {
      const res = await searchPlatformUsers(userSearchQ.trim());
      setUserHits(Array.isArray(res.data) ? res.data : []);
    } catch {
      setUserHits([]);
    } finally {
      setUserSearchLoading(false);
    }
  }

  const moduleDefaults = useMemo(() => {
    const o = {};
    TENANT_MODULES.forEach((m) => {
      o[m.key] = true;
    });
    return o;
  }, []);

  async function openEdit(r) {
    setEditRow(r);
    setEditName(r.display_name || "");
    setEditActive(!!r.active);
    setEditAddress(r.address || "");
    setEditPhone(r.phone || "");
    setEditEmail(r.email || "");
    setError("");
    try {
      const res = await getPlatformEntitlements(r.id);
      const m = res.data?.modules || {};
      setModules({ ...moduleDefaults, ...m });
    } catch (e) {
      setModules({ ...moduleDefaults });
      setError(e?.response?.data?.error || e?.message || "Could not load modules.");
    }
  }

  async function onCreate(e) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      await createPlatformOrganization({
        slug: slug.trim(),
        display_name: displayName.trim(),
      });
      setSlug("");
      setDisplayName("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function toggleOrgActive(row, nextActive) {
    setError("");
    try {
      await putPlatformOrganization(row.id, { active: nextActive });
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Update failed");
    }
  }

  async function deactivateOrg(row) {
    if (
      !window.confirm(
        t("platform.confirmDeleteTenant").replace(
          "{name}",
          String(row.display_name || row.slug || row.id),
        ),
      )
    )
      return;
    setError("");
    try {
      await deletePlatformOrganization(row.id);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Deactivate failed");
    }
  }

  async function onLogoFile(ev) {
    const f = ev.target?.files?.[0];
    ev.target.value = "";
    if (!f || !editRow) return;
    setLogoErr("");
    setLogoBusy(true);
    try {
      const res = await uploadPlatformOrganizationLogo(editRow.id, f);
      const url = res.data?.logo_url;
      setEditRow((prev) => (prev ? { ...prev, logo_url: url || prev.logo_url } : prev));
      await load();
    } catch (e) {
      setLogoErr(e?.response?.data?.error || e?.message || "Upload failed");
    } finally {
      setLogoBusy(false);
    }
  }

  async function clearOrgLogo() {
    if (!editRow) return;
    setLogoErr("");
    setLogoBusy(true);
    try {
      await putPlatformOrganization(editRow.id, { logo_url: "" });
      setEditRow((prev) => (prev ? { ...prev, logo_url: null } : prev));
      await load();
    } catch (e) {
      setLogoErr(e?.response?.data?.error || e?.message || "Failed");
    } finally {
      setLogoBusy(false);
    }
  }

  async function saveEdit() {
    if (!editRow) return;
    setSavingEdit(true);
    setError("");
    try {
      await putPlatformOrganization(editRow.id, {
        display_name: editName.trim(),
        active: editActive,
        address: editAddress.trim(),
        phone: editPhone.trim(),
        email: editEmail.trim(),
      });
      await putPlatformEntitlements(editRow.id, modules);
      setEditRow(null);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSavingEdit(false);
    }
  }

  function toggleModule(key) {
    setModules((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const platformPageTitle =
    mainTab === 0 ? t("platform.title") : mainTab === 1 ? t("platform.tabRolePackages") : t("platform.tabUsers");

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto", p: { xs: 1.2, md: 2 } }}>
      <Typography variant="h4" sx={{ mb: 2, fontWeight: 700, color: "text.primary" }}>
        {platformPageTitle}
      </Typography>

      <Tabs
        value={mainTab}
        onChange={(_, v) => setMainTab(v)}
        sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
      >
        <Tab label={t("platform.tabTenants")} />
        <Tab label={t("platform.tabRolePackages")} />
        <Tab label={t("platform.tabUsers")} />
      </Tabs>

      {mainTab === 0 && error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {mainTab === 1 ? <PlatformRolePackagesPanel /> : null}

      {mainTab === 2 ? (
        <Paper sx={{ p: 2, borderRadius: 2, mb: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }} alignItems={{ sm: "center" }}>
            <TextField
              size="small"
              fullWidth
              placeholder={t("platform.usersSearchPlaceholder")}
              value={userSearchQ}
              onChange={(e) => setUserSearchQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") runUserSearch();
              }}
            />
            <Button variant="contained" onClick={runUserSearch} disabled={userSearchLoading}>
              {t("common.search")}
            </Button>
          </Stack>
          {userSearchLoading ? (
            <Typography variant="body2">{t("platformOrgs.loading")}</Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>{t("people.colUsername")}</TableCell>
                  <TableCell>{t("people.colDisplay")}</TableCell>
                  <TableCell>organization_id</TableCell>
                  <TableCell>{t("common.active")}</TableCell>
                  <TableCell align="right">{t("common.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {userHits.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.id}</TableCell>
                    <TableCell>{r.username}</TableCell>
                    <TableCell>{r.display_name || "—"}</TableCell>
                    <TableCell>{r.organization_id ?? "—"}</TableCell>
                    <TableCell>{r.active ? t("common.yes") : t("common.no")}</TableCell>
                    <TableCell align="right">
                      <Button size="small" variant="outlined" onClick={() => navigate(`/platform/users/${r.id}`)}>
                        {t("platform.openProfile")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Paper>
      ) : null}

      {mainTab === 0 ? (
        <>
      <Paper sx={{ p: 2, mb: 2, borderRadius: 2, borderColor: "divider", borderWidth: 1, borderStyle: "solid" }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5, color: "text.primary" }}>
          {t("platformOrgs.createHeading")}
        </Typography>
        <Stack
          component="form"
          onSubmit={onCreate}
          spacing={1.5}
          direction={{ xs: "column", sm: "row" }}
          alignItems={{ sm: "flex-start" }}
        >
          <TextField
            label={t("platformOrgs.slug")}
            value={slug}
            onChange={(ev) => setSlug(ev.target.value)}
            size="small"
            sx={{ minWidth: 200 }}
          />
          <TextField
            label={t("platformOrgs.displayName")}
            value={displayName}
            onChange={(ev) => setDisplayName(ev.target.value)}
            required
            size="small"
            sx={{ flex: 1, minWidth: 200 }}
          />
          <Button type="submit" variant="contained" disabled={creating || !displayName.trim()} sx={{ mt: { sm: 0.5 } }}>
            {creating ? t("common.saving") : t("platformOrgs.create")}
          </Button>
        </Stack>
      </Paper>

      <Paper sx={{ borderRadius: 2, overflow: "hidden", borderColor: "divider", borderWidth: 1, borderStyle: "solid" }}>
        <Box sx={{ p: 2, borderBottom: "1px solid", borderColor: "divider", bgcolor: "action.hover" }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, color: "text.primary" }}>
            {t("platformOrgs.listHeading")}
          </Typography>
        </Box>
        {loading ? (
          <Box sx={{ p: 3 }}>
            <Typography>{t("platformOrgs.loading")}</Typography>
          </Box>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>ID</TableCell>
                <TableCell>{t("platformOrgs.slug")}</TableCell>
                <TableCell>{t("platformOrgs.displayName")}</TableCell>
                <TableCell>{t("platformOrgs.teamLogin")}</TableCell>
                <TableCell>{t("common.active")}</TableCell>
                <TableCell align="right">{t("common.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.id}</TableCell>
                  <TableCell>{r.slug}</TableCell>
                  <TableCell>
                    <Stack direction="row" alignItems="center" spacing={1}>
                      {r.logo_url ? (
                        <Box
                          component="img"
                          src={r.logo_url}
                          alt=""
                          sx={{ width: 28, height: 28, objectFit: "contain", borderRadius: 0.5 }}
                        />
                      ) : null}
                      <span>{r.display_name}</span>
                    </Stack>
                  </TableCell>
                  <TableCell sx={{ fontSize: 12, wordBreak: "break-all" }}>{teamLoginHref(r.slug)}</TableCell>
                  <TableCell>
                    <Switch
                      size="small"
                      checked={!!r.active}
                      onChange={(_, v) => toggleOrgActive(r, v)}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={t("common.edit")}>
                      <IconButton size="small" onClick={() => openEdit(r)} sx={{ color: "primary.main" }}>
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t("platform.removeTenant")}>
                      <IconButton size="small" onClick={() => deactivateOrg(r)} sx={{ color: "text.secondary" }}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      <Dialog open={!!editRow} onClose={() => !savingEdit && setEditRow(null)} maxWidth="sm" fullWidth scroll="paper">
        <DialogTitle>{t("platform.editTenantTitle")}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {t("organization.slugReadOnly")}: <strong>{editRow?.slug}</strong>
          </Typography>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            {t("organization.uploadLogo")}
          </Typography>
          {logoErr ? (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setLogoErr("")}>
              {logoErr}
            </Alert>
          ) : null}
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2, flexWrap: "wrap" }}>
            {editRow?.logo_url ? (
              <Box
                component="img"
                src={editRow.logo_url}
                alt=""
                sx={{ maxHeight: 56, maxWidth: 160, objectFit: "contain", borderRadius: 1, border: "1px solid #e2e8f0" }}
              />
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t("organization.logoUrlHelp")}
              </Typography>
            )}
            <Button variant="outlined" component="label" size="small" disabled={logoBusy || !editRow}>
              {logoBusy ? t("organization.uploading") : t("organization.uploadLogo")}
              <input type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif" onChange={onLogoFile} />
            </Button>
            {editRow?.logo_url ? (
              <Button variant="text" color="inherit" size="small" onClick={clearOrgLogo} disabled={logoBusy} sx={{ color: "text.secondary" }}>
                {t("platform.removeLogo")}
              </Button>
            ) : null}
          </Stack>
          <TextField
            label={t("platformOrgs.displayName")}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            fullWidth
            size="small"
            sx={{ mb: 1.5 }}
          />
          <FormControlLabel
            control={<Checkbox checked={editActive} onChange={(e) => setEditActive(e.target.checked)} />}
            label={t("common.active")}
            sx={{ mb: 1 }}
          />
          <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.5 }}>
            {t("platform.contactSection")}
          </Typography>
          <TextField
            label={t("organization.address")}
            value={editAddress}
            onChange={(e) => setEditAddress(e.target.value)}
            fullWidth
            size="small"
            multiline
            minRows={2}
            sx={{ mb: 1 }}
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
            <TextField
              label={t("organization.phone")}
              value={editPhone}
              onChange={(e) => setEditPhone(e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label={t("organization.email")}
              value={editEmail}
              onChange={(e) => setEditEmail(e.target.value)}
              fullWidth
              size="small"
            />
          </Stack>
          <Typography variant="subtitle2" sx={{ mt: 2, mb: 0.5 }}>
            {t("platform.modulesSection")}
          </Typography>
          <Stack spacing={0.25}>
            {TENANT_MODULES.map((m) => (
              <FormControlLabel
                key={m.key}
                control={<Checkbox checked={!!modules[m.key]} onChange={() => toggleModule(m.key)} />}
                label={t(m.labelKey)}
              />
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRow(null)} disabled={savingEdit}>
            {t("common.cancel")}
          </Button>
          <Button onClick={saveEdit} variant="contained" disabled={savingEdit || !editName.trim()}>
            {savingEdit ? t("common.saving") : t("common.save")}
          </Button>
        </DialogActions>
      </Dialog>
        </>
      ) : null}
    </Box>
  );
}
