import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { createWeeklyScheduleRole, updateWeeklyScheduleRole } from "../../api";
import { roleStyle } from "./weeklyScheduleRoles";

const EDITABLE_FIELDS = ["name", "kind", "role_group", "display_order", "active", "remarks_enabled"];

const EMPTY_NEW_ROLE = {
  name: "",
  kind: "role",
  role_group: "RINSE_WF",
  display_order: "",
  active: true,
  remarks_enabled: false,
};

const KIND_OPTIONS = [
  { value: "role", label: "Role — timed production work" },
  { value: "task", label: "Task — by day, instructions only" },
];

function withKind(role) {
  return { ...role, kind: role.kind || (role.uses_time_slots === false ? "task" : "role") };
}

function changedFields(draft, original) {
  const patch = {};
  for (const key of EDITABLE_FIELDS) {
    const a = draft[key] ?? null;
    const b = original[key] ?? null;
    if (key === "display_order" ? Number(a) !== Number(b) : a !== b) patch[key] = draft[key];
  }
  return patch;
}

function FlagSwitch({ label, checked, onChange }) {
  return (
    <FormControlLabel
      sx={{ m: 0, mr: 1 }}
      control={<Switch size="small" checked={Boolean(checked)} onChange={(e) => onChange(e.target.checked)} />}
      label={<Typography variant="caption" fontWeight={700}>{label}</Typography>}
    />
  );
}

function RoleFields({ draft, groups, onChange }) {
  const isTask = draft.kind === "task";
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr 1fr",
          md: "minmax(150px, 1.3fr) minmax(190px, 1.3fr) minmax(120px, 1fr) 80px",
        },
        gap: 1,
        alignItems: "center",
      }}
    >
      <TextField
        size="small"
        label="Name"
        value={draft.name}
        onChange={(e) => onChange({ name: e.target.value })}
        inputProps={{ maxLength: 64 }}
        sx={{ gridColumn: { xs: "1 / -1", md: "auto" } }}
      />
      <TextField
        select
        size="small"
        label="Type"
        value={draft.kind || "role"}
        onChange={(e) => onChange({ kind: e.target.value })}
        sx={{ gridColumn: { xs: "1 / -1", md: "auto" } }}
      >
        {KIND_OPTIONS.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        size="small"
        label="Group"
        value={draft.role_group || ""}
        onChange={(e) => onChange({ role_group: e.target.value || null })}
      >
        <MenuItem value="">
          <em>None</em>
        </MenuItem>
        {groups.map((group) => (
          <MenuItem key={group.code} value={group.code}>
            {group.label}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        size="small"
        label="Order"
        type="number"
        value={draft.display_order}
        onChange={(e) => onChange({ display_order: e.target.value })}
        inputProps={{ step: 10 }}
      />
      <Stack direction="row" flexWrap="wrap" useFlexGap sx={{ gridColumn: "1 / -1" }}>
        <FlagSwitch label="Active" checked={draft.active} onChange={(v) => onChange({ active: v })} />
        {isTask ? (
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
            Assigned per day with instructions. No start/end time, hours, or attendance window.
          </Typography>
        ) : (
          <FlagSwitch label="Enable remarks" checked={draft.remarks_enabled} onChange={(v) => onChange({ remarks_enabled: v })} />
        )}
      </Stack>
    </Box>
  );
}

export default function WeeklyScheduleManageRolesDialog({ open, onClose, roles = [], groups = [], onCatalogChange }) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const [drafts, setDrafts] = useState({});
  const [newRole, setNewRole] = useState(EMPTY_NEW_ROLE);
  const [savingCode, setSavingCode] = useState(null);
  const [error, setError] = useState("");

  const originals = useRef({});

  useEffect(() => {
    if (!open) return;
    originals.current = {};
    setDrafts({});
    setNewRole(EMPTY_NEW_ROLE);
    setError("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setDrafts((prev) => {
      const next = {};
      for (const raw of roles) {
        const role = withKind(raw);
        const before = originals.current[role.code];
        const unchanged = before && !Object.keys(changedFields(before, role)).length;
        next[role.code] = prev[role.code] && unchanged ? prev[role.code] : role;
      }
      return next;
    });
    originals.current = Object.fromEntries(roles.map((role) => [role.code, withKind(role)]));
  }, [open, roles]);

  const rows = useMemo(() => roles.map(withKind), [roles]);

  const groupLabel = useMemo(() => Object.fromEntries(groups.map((g) => [g.code, g.label])), [groups]);

  const saveRole = async (role) => {
    const draft = drafts[role.code];
    const patch = changedFields(draft, role);
    if (!Object.keys(patch).length) return;
    if ("display_order" in patch) patch.display_order = Number(patch.display_order) || 0;
    setSavingCode(role.code);
    setError("");
    try {
      const res = await updateWeeklyScheduleRole(role.code, patch);
      onCatalogChange?.(res.data?.roles || []);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save");
    } finally {
      setSavingCode(null);
    }
  };

  const addRole = async () => {
    if (!newRole.name.trim()) return;
    setSavingCode("__new__");
    setError("");
    try {
      const body = { ...newRole, role_group: newRole.role_group || null };
      if (body.display_order === "") delete body.display_order;
      else body.display_order = Number(body.display_order) || 0;
      const res = await createWeeklyScheduleRole(body);
      onCatalogChange?.(res.data?.roles || []);
      setNewRole(EMPTY_NEW_ROLE);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to add");
    } finally {
      setSavingCode(null);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth fullScreen={fullScreen}>
      <DialogTitle>Roles &amp; tasks</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          <strong>Roles</strong> are timed production work inside a shift (weighing, sorting, washing, drying, folding,
          post-weighing) and count toward scheduled hours. <strong>Tasks</strong> (cleaning, Self Service, Drop Off
          customer attendance) are assigned to an employee for a day with instructions only — no times, no hours. These
          are separate from login permissions. Deactivating hides an item from new assignments; existing schedules keep
          showing it. Changing the type applies to new assignments only.
        </Typography>
        {error ? (
          <Alert severity="error" sx={{ mb: 1.5 }}>
            {error}
          </Alert>
        ) : null}
        <Stack spacing={1}>
          {rows.map((role) => {
            const draft = drafts[role.code];
            if (!draft) return null;
            const dirty = Object.keys(changedFields(draft, role)).length > 0;
            const style = roleStyle(role.code);
            return (
              <Box
                key={role.code}
                sx={{
                  border: "1px solid #e2e8f0",
                  borderLeft: `4px solid ${style.accent}`,
                  borderRadius: 1.5,
                  p: 1.25,
                  opacity: role.active === false ? 0.7 : 1,
                }}
              >
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1 }}>
                  <Typography variant="subtitle2" fontWeight={800} sx={{ flex: 1, minWidth: 0 }} noWrap>
                    {role.name}
                  </Typography>
                  {role.role_group ? <Chip size="small" label={groupLabel[role.role_group] || role.role_group} /> : null}
                  <Chip
                    size="small"
                    variant="outlined"
                    color={role.kind === "task" ? "secondary" : "primary"}
                    label={role.kind === "task" ? "Task" : "Role"}
                  />
                  {role.active === false ? <Chip size="small" color="default" label="Inactive" /> : null}
                  <Button
                    size="small"
                    variant={dirty ? "contained" : "outlined"}
                    disabled={!dirty || savingCode === role.code || !String(draft.name || "").trim()}
                    onClick={() => saveRole(role)}
                    sx={{ fontWeight: 700 }}
                  >
                    {savingCode === role.code ? "Saving…" : "Save"}
                  </Button>
                </Stack>
                <RoleFields
                  draft={draft}
                  groups={groups}
                  onChange={(patch) => setDrafts((prev) => ({ ...prev, [role.code]: { ...prev[role.code], ...patch } }))}
                />
              </Box>
            );
          })}

          <Box sx={{ border: "1.5px dashed #cbd5e1", borderRadius: 1.5, p: 1.25 }}>
            <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
              Add role or task
            </Typography>
            <RoleFields draft={newRole} groups={groups} onChange={(patch) => setNewRole((prev) => ({ ...prev, ...patch }))} />
            <Button
              variant="contained"
              size="small"
              sx={{ mt: 1, fontWeight: 700 }}
              disabled={!newRole.name.trim() || savingCode === "__new__"}
              onClick={addRole}
            >
              {savingCode === "__new__" ? "Adding…" : newRole.kind === "task" ? "Add task" : "Add role"}
            </Button>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Done</Button>
      </DialogActions>
    </Dialog>
  );
}
