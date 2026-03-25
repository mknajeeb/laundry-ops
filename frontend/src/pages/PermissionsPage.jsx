import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormGroup,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { getPermissionMatrix, putRolePermissions } from "../api";
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

  const load = useCallback(async () => {
    if (!can) return;
    setError("");
    try {
      const res = await getPermissionMatrix();
      setData(res.data);
      const roles = res.data?.roles || [];
      setRoleId((prev) => prev || (roles[0] ? String(roles[0].id) : ""));
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

  const grouped = useMemo(() => {
    const g = {};
    (data?.permissions || []).forEach((p) => {
      const grp = groupPermKey(p.perm_key);
      if (!g[grp]) g[grp] = [];
      g[grp].push(p);
    });
    return g;
  }, [data]);

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

  if (!can) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("permissions.needSettings")}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 900 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        {t("permissions.title")}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("permissions.blurb")}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }} alignItems="flex-start">
          <FormControl sx={{ minWidth: 260 }}>
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
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="contained" onClick={save} disabled={saving || !roleId}>
            {saving ? t("common.saving") : t("permissions.save")}
          </Button>
        </Stack>

        {Object.keys(grouped)
          .sort()
          .map((grp) => (
            <Box key={grp} sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 0.5, textTransform: "capitalize" }}>
                {grp}
              </Typography>
              <FormGroup>
                {grouped[grp].map((p) => (
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
                          <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                            {p.description}
                          </Typography>
                        ) : null}
                      </span>
                    }
                  />
                ))}
              </FormGroup>
            </Box>
          ))}
      </Paper>
    </Box>
  );
}
