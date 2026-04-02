import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
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
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  createTaAdminRole,
  deleteTaAdminRole,
  getPermissionMatrix,
  putRolePermissions,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function groupPermKey(key) {
  const i = String(key).indexOf(".");
  return i === -1 ? "other" : key.slice(0, i);
}

export default function PermissionsPage() {
  const { hasPerm } = useAuth();
  const { t } = useI18n();
  const can = hasPerm("ta.settings");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [roleId, setRoleId] = useState("");
  const [selected, setSelected] = useState({});
  const [createOpen, setCreateOpen] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!can) return;
    setError("");
    try {
      const res = await getPermissionMatrix();
      setData(res.data);
      const roles = res.data?.roles || [];
      setRoleId((prev) => {
        if (prev && roles.some((r) => String(r.id) === String(prev))) return prev;
        return roles[0] ? String(roles[0].id) : "";
      });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Load failed");
    }
  }, [can]);

  useEffect(() => {
    load();
  }, [load]);

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
    [data, roleId]
  );

  const canDeleteRole =
    selectedRole &&
    Number(selectedRole.organization_id) > 0 &&
    !selectedRole.is_system;

  async function save() {
    if (!roleId) return;
    setSaving(true);
    setError("");
    try {
      const permission_keys = Object.entries(selected)
        .filter(([, on]) => on)
        .map(([k]) => k);
      await putRolePermissions(Number(roleId), permission_keys);
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
      await createTaAdminRole({
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
      await deleteTaAdminRole(Number(roleId));
      setRoleId("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  if (!can) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("permissions.needSettings")}</Alert>
      </Box>
    );
  }

  const hierarchy = data?.hierarchy;

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 960 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        {t("permissions.title")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("permissions.blurb")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("permissions.hierarchyHint")}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }} alignItems="flex-start">
          <FormControl sx={{ minWidth: 280 }}>
            <InputLabel id="role-pick">{t("permissions.role")}</InputLabel>
            <Select
              labelId="role-pick"
              label={t("permissions.role")}
              value={roleId}
              onChange={(e) => setRoleId(e.target.value)}
            >
              {(data?.roles || []).map((r) => (
                <MenuItem key={r.id} value={String(r.id)}>
                  {r.code} — {r.name}
                  {Number(r.organization_id) > 0
                    ? ` (${t("permissions.customRoleBadge")})`
                    : r.is_system
                      ? ` (${t("permissions.platformRole")})`
                      : ""}
                </MenuItem>
              ))}
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
              color="error"
              disabled={!canDeleteRole || saving}
              onClick={handleDeleteRole}
            >
              {t("permissions.deleteRole")}
            </Button>
          </Stack>
        </Stack>

        {hierarchy && hierarchy.length ? (
          <Stack spacing={1}>
            {hierarchy.map((route) => (
              <Accordion key={route.route_key} defaultExpanded disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography fontWeight={600}>{route.route_label}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {route.route_key}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  {(route.sections || []).map((sec) => (
                    <Box key={`${route.route_key}-${sec.section_key}`} sx={{ mb: 2 }}>
                      <Typography variant="subtitle2" sx={{ mb: 1 }}>
                        {sec.section_label}
                      </Typography>
                      {(sec.resources || []).map((res) => (
                        <Table size="small" key={`${res.resource_key}-${sec.section_key}`} sx={{ mb: 2 }}>
                          <TableHead>
                            <TableRow>
                              <TableCell width={100}>{t("permissions.colAction")}</TableCell>
                              <TableCell>{t("permissions.colPermission")}</TableCell>
                              <TableCell>{t("permissions.colDescription")}</TableCell>
                              <TableCell align="right" width={90}>
                                {t("permissions.colAllow")}
                              </TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {(res.actions || []).map((a) => (
                              <TableRow key={a.perm_key}>
                                <TableCell sx={{ textTransform: "capitalize" }}>{a.action_key}</TableCell>
                                <TableCell>
                                  <Typography variant="body2" component="code" sx={{ fontSize: 13 }}>
                                    {a.perm_key}
                                  </Typography>
                                </TableCell>
                                <TableCell>
                                  <Typography variant="body2" color="text.secondary">
                                    {a.description || "—"}
                                  </Typography>
                                </TableCell>
                                <TableCell align="right">
                                  <Checkbox
                                    size="small"
                                    checked={!!selected[a.perm_key]}
                                    onChange={(e) =>
                                      setSelected((prev) => ({
                                        ...prev,
                                        [a.perm_key]: e.target.checked,
                                      }))
                                    }
                                  />
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      ))}
                    </Box>
                  ))}
                </AccordionDetails>
              </Accordion>
            ))}
          </Stack>
        ) : (
          Object.keys(groupedFlat)
            .sort()
            .map((grp) => (
              <Box key={grp} sx={{ mb: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5, textTransform: "capitalize" }}>
                  {grp}
                </Typography>
                <Stack spacing={0.5}>
                  {groupedFlat[grp].map((p) => (
                    <FormControlLabel
                      key={p.perm_key}
                      control={
                        <Checkbox
                          checked={!!selected[p.perm_key]}
                          onChange={(e) =>
                            setSelected((prev) => ({ ...prev, [p.perm_key]: e.target.checked }))
                          }
                        />
                      }
                      label={
                        <span>
                          <strong>{p.perm_key}</strong>
                          {p.description ? (
                            <Typography
                              component="span"
                              variant="caption"
                              color="text.secondary"
                              sx={{ ml: 1 }}
                            >
                              {p.description}
                            </Typography>
                          ) : null}
                        </span>
                      }
                    />
                  ))}
                </Stack>
              </Box>
            ))
        )}
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
