import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Switch,
  FormControlLabel,
  TextField,
  Typography,
} from "@mui/material";
import {
  getManagementTaskCatalog,
  upsertManagementTaskDefinition,
  upsertManagementTaskActivityGroup,
} from "../../api";

/**
 * Lightweight Manage Tasks surface embedded in the Task Dashboard.
 * Full editor remains at /management/task-management.
 */
export default function TaskManageDialog({ open, onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [categories, setCategories] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [activityGroups, setActivityGroups] = useState([]);
  const [draft, setDraft] = useState(null);
  const [groupDraft, setGroupDraft] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementTaskCatalog();
      setCategories(res.data?.categories || []);
      setTasks(res.data?.tasks || []);
      setActivityGroups(res.data?.activity_groups || []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const saveTask = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    setOkMsg("");
    try {
      await upsertManagementTaskDefinition({
        code: draft.code,
        name: draft.name,
        category_code: draft.category_code,
        instructions: draft.instructions || "",
        active: draft.active !== false,
        completion_type: draft.completion_type || "simple",
        timer_enabled: draft.timer_enabled !== false,
        verification_required: draft.verification_required !== false,
        verification_method: draft.verification_method || "employee",
      });
      setOkMsg("Task saved. Historical completions keep prior labels where recorded.");
      setDraft(null);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const saveGroup = async () => {
    if (!groupDraft) return;
    setBusy(true);
    setError("");
    try {
      const itemCodes = String(groupDraft.item_codes_text || "")
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      await upsertManagementTaskActivityGroup({
        id: groupDraft.id,
        name: groupDraft.name,
        category_code: groupDraft.category_code || "intra_day",
        active: groupDraft.active !== false,
        items: itemCodes.map((task_code, idx) => ({ task_code, required: true, display_order: idx })),
      });
      setOkMsg("Activity Group saved.");
      setGroupDraft(null);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="md">
      <DialogTitle>Manage Tasks</DialogTitle>
      <DialogContent>
        {error ? (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        ) : null}
        {okMsg ? (
          <Alert severity="success" sx={{ mb: 1 }}>
            {okMsg}
          </Alert>
        ) : null}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Add, rename, or deactivate tasks without deleting history. Assignments stay on Weekly
          Schedule.{" "}
          <Button component={RouterLink} to="/management/task-management" size="small">
            Open full Task Management
          </Button>
        </Typography>
        {loading ? (
          <Typography variant="body2">Loading…</Typography>
        ) : (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant="outlined"
                onClick={() =>
                  setDraft({
                    code: `custom_${Date.now().toString(36)}`,
                    name: "",
                    category_code: categories[0]?.code || "intra_day",
                    active: true,
                    instructions: "",
                  })
                }
              >
                Add task
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={() =>
                  setGroupDraft({
                    name: "",
                    category_code: "intra_day",
                    active: true,
                    item_codes_text: "",
                  })
                }
              >
                Add Activity Group
              </Button>
            </Stack>

            {draft ? (
              <Stack spacing={1} sx={{ p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
                <Typography sx={{ fontWeight: 700 }}>
                  {draft.id ? "Edit task" : "New task"}
                </Typography>
                <TextField
                  size="small"
                  label="Name"
                  value={draft.name || ""}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  fullWidth
                />
                <TextField
                  select
                  size="small"
                  label="Category"
                  value={draft.category_code || ""}
                  onChange={(e) => setDraft({ ...draft, category_code: e.target.value })}
                  fullWidth
                >
                  {categories.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  label="Instructions"
                  value={draft.instructions || ""}
                  onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
                  fullWidth
                  multiline
                  minRows={2}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={draft.active !== false}
                      onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
                    />
                  }
                  label="Active"
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy || !draft.name} onClick={saveTask}>
                    Save task
                  </Button>
                  <Button disabled={busy} onClick={() => setDraft(null)}>
                    Cancel
                  </Button>
                </Stack>
              </Stack>
            ) : null}

            {groupDraft ? (
              <Stack spacing={1} sx={{ p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
                <Typography sx={{ fontWeight: 700 }}>Activity Group</Typography>
                <TextField
                  size="small"
                  label="Name"
                  value={groupDraft.name || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, name: e.target.value })}
                  fullWidth
                />
                <TextField
                  select
                  size="small"
                  label="Category"
                  value={groupDraft.category_code || "intra_day"}
                  onChange={(e) => setGroupDraft({ ...groupDraft, category_code: e.target.value })}
                  fullWidth
                >
                  {categories.map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  label="Member task codes (one per line)"
                  value={groupDraft.item_codes_text || ""}
                  onChange={(e) => setGroupDraft({ ...groupDraft, item_codes_text: e.target.value })}
                  fullWidth
                  multiline
                  minRows={3}
                  helperText="Use existing task codes. Deactivating does not erase history."
                />
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" disabled={busy || !groupDraft.name} onClick={saveGroup}>
                    Save group
                  </Button>
                  <Button disabled={busy} onClick={() => setGroupDraft(null)}>
                    Cancel
                  </Button>
                </Stack>
              </Stack>
            ) : null}

            <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
              Tasks
            </Typography>
            {tasks.slice(0, 40).map((t) => (
              <Stack
                key={t.code}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ py: 0.5, borderBottom: "1px solid", borderColor: "divider" }}
              >
                <Typography variant="body2">
                  {t.name}{" "}
                  <Typography component="span" variant="caption" color="text.secondary">
                    ({t.category_code}) {t.active === false ? "· inactive" : ""}
                  </Typography>
                </Typography>
                <Button size="small" onClick={() => setDraft({ ...t })}>
                  Edit
                </Button>
              </Stack>
            ))}

            <Typography variant="subtitle2" sx={{ fontWeight: 800, mt: 1 }}>
              Activity Groups
            </Typography>
            {activityGroups.map((g) => (
              <Stack
                key={g.id || g.role_code}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ py: 0.5, borderBottom: "1px solid", borderColor: "divider" }}
              >
                <Typography variant="body2">
                  {g.name}{" "}
                  <Typography component="span" variant="caption" color="text.secondary">
                    ({(g.items || []).length} items)
                  </Typography>
                </Typography>
                <Button
                  size="small"
                  onClick={() =>
                    setGroupDraft({
                      ...g,
                      item_codes_text: (g.items || []).map((i) => i.task_code).join("\n"),
                    })
                  }
                >
                  Edit
                </Button>
              </Stack>
            ))}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
