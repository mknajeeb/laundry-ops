import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import {
  getCategoryRoleTrackingFeatureFlag,
  getTaskTrackingCategories,
  getTaskTrackingCategoryRoles,
  getTaskTrackingRoles,
  patchTaskTrackingCategory,
  patchTaskTrackingCategoryRole,
  patchTaskTrackingRole,
  postTaskTrackingCategoriesReorder,
  postTaskTrackingCategory,
  postTaskTrackingCategoryRole,
  postTaskTrackingCategoryRolesReorder,
  postTaskTrackingRole,
} from "../api";

/**
 * Category and Role Maintenance — left panel categories, right panel assigned roles.
 */
export default function CategoryRoleMaintenancePage() {
  const [categories, setCategories] = useState([]);
  const [roles, setRoles] = useState([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [catDialog, setCatDialog] = useState(null); // { id?, name, active }
  const [roleDialog, setRoleDialog] = useState(null); // { name, active, assign }
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [assignRoleId, setAssignRoleId] = useState("");
  const [trackingEnabled, setTrackingEnabled] = useState(false);

  const loadCategories = useCallback(async () => {
    const res = await getTaskTrackingCategories({ include_inactive: "1", include_usage: "1" });
    const rows = Array.isArray(res.data) ? res.data : [];
    setCategories(rows);
    return rows;
  }, []);

  const loadRoles = useCallback(async () => {
    const res = await getTaskTrackingRoles({ include_inactive: "1", include_usage: "1" });
    setRoles(Array.isArray(res.data) ? res.data : []);
  }, []);

  const loadAssignments = useCallback(async (categoryId) => {
    if (!categoryId) {
      setAssignments([]);
      return;
    }
    const res = await getTaskTrackingCategoryRoles(categoryId, { include_inactive: "1" });
    setAssignments(Array.isArray(res.data) ? res.data : []);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const cats = await loadCategories();
      await loadRoles();
      const nextId = selectedCategoryId || cats[0]?.id || null;
      setSelectedCategoryId(nextId);
      await loadAssignments(nextId);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [loadAssignments, loadCategories, loadRoles, selectedCategoryId]);

  useEffect(() => {
    refresh();
    getCategoryRoleTrackingFeatureFlag()
      .then((res) => setTrackingEnabled(!!res.data?.category_role_tracking_enabled))
      .catch(() => setTrackingEnabled(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectCategory = async (id) => {
    setSelectedCategoryId(id);
    try {
      await loadAssignments(id);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load roles");
    }
  };

  const saveCategory = async () => {
    if (!catDialog?.name?.trim()) return;
    setBusy(true);
    setError("");
    try {
      if (catDialog.id) {
        await patchTaskTrackingCategory(catDialog.id, {
          name: catDialog.name.trim(),
          active: catDialog.active,
        });
      } else {
        await postTaskTrackingCategory({ name: catDialog.name.trim(), active: catDialog.active !== false });
      }
      setCatDialog(null);
      const cats = await loadCategories();
      const keep = catDialog.id || cats[cats.length - 1]?.id;
      setSelectedCategoryId(keep);
      await loadAssignments(keep);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const moveCategory = async (index, direction) => {
    const next = [...categories];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setCategories(next);
    try {
      await postTaskTrackingCategoriesReorder({ ordered_ids: next.map((c) => c.id) });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Reorder failed");
      await loadCategories();
    }
  };

  const createAndAssignRole = async () => {
    if (!roleDialog?.name?.trim() || !selectedCategoryId) return;
    setBusy(true);
    setError("");
    try {
      const res = await postTaskTrackingRole({
        name: roleDialog.name.trim(),
        active: true,
        category_ids: roleDialog.assign ? [selectedCategoryId] : [],
      });
      if (roleDialog.assign && res.data?.id) {
        // already assigned via category_ids
      }
      setRoleDialog(null);
      await loadRoles();
      await loadAssignments(selectedCategoryId);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const assignExistingRole = async () => {
    if (!assignRoleId || !selectedCategoryId) return;
    setBusy(true);
    setError("");
    try {
      await postTaskTrackingCategoryRole(selectedCategoryId, { role_id: Number(assignRoleId) });
      setAssignDialogOpen(false);
      setAssignRoleId("");
      await loadAssignments(selectedCategoryId);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Assign failed");
    } finally {
      setBusy(false);
    }
  };

  const moveAssignment = async (index, direction) => {
    const next = [...assignments];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setAssignments(next);
    try {
      await postTaskTrackingCategoryRolesReorder(selectedCategoryId, {
        ordered_ids: next.map((a) => a.id),
      });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Reorder failed");
      await loadAssignments(selectedCategoryId);
    }
  };

  const toggleAssignment = async (row) => {
    try {
      await patchTaskTrackingCategoryRole(row.id, { active: !row.active });
      await loadAssignments(selectedCategoryId);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Update failed");
    }
  };

  const selectedCategory = categories.find((c) => Number(c.id) === Number(selectedCategoryId));
  const unassignedRoles = roles.filter(
    (r) => r.active && !assignments.some((a) => Number(a.role_id) === Number(r.id))
  );

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5 }}>
        Category & Role Maintenance
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Categories and roles employees select during check-in. New categories automatically get Operator and Folder.
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {!trackingEnabled ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Category & Role Tracking is currently disabled. Changes made here will become available
          when the feature is enabled.
        </Alert>
      ) : null}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="stretch">
        <Paper variant="outlined" sx={{ p: 2, flex: 1, borderRadius: 2, minHeight: 360 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Typography fontWeight={800}>Categories</Typography>
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={() => setCatDialog({ name: "", active: true })}
            >
              Add
            </Button>
          </Stack>
          {loading ? (
            <Typography color="text.secondary">Loading…</Typography>
          ) : (
            <Stack spacing={0.75}>
              {categories.map((cat, idx) => (
                <Paper
                  key={cat.id}
                  variant="outlined"
                  onClick={() => selectCategory(cat.id)}
                  sx={{
                    p: 1.25,
                    cursor: "pointer",
                    borderColor: Number(selectedCategoryId) === Number(cat.id) ? "primary.main" : "divider",
                    bgcolor: Number(selectedCategoryId) === Number(cat.id) ? "action.selected" : "background.paper",
                  }}
                >
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <Stack direction="row" spacing={0}>
                      <IconButton size="small" disabled={idx === 0} onClick={(e) => { e.stopPropagation(); moveCategory(idx, -1); }}>
                        <ArrowUpwardIcon fontSize="inherit" />
                      </IconButton>
                      <IconButton size="small" disabled={idx === categories.length - 1} onClick={(e) => { e.stopPropagation(); moveCategory(idx, 1); }}>
                        <ArrowDownwardIcon fontSize="inherit" />
                      </IconButton>
                    </Stack>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography fontWeight={700} noWrap>
                        {cat.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {cat.code}
                      </Typography>
                    </Box>
                    <Chip size="small" label={cat.active ? "Active" : "Inactive"} color={cat.active ? "success" : "default"} />
                    <Button
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        setCatDialog({ id: cat.id, name: cat.name, active: !!cat.active });
                      }}
                    >
                      Edit
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </Paper>

        <Paper variant="outlined" sx={{ p: 2, flex: 1.2, borderRadius: 2, minHeight: 360 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Box>
              <Typography fontWeight={800}>
                Roles{selectedCategory ? ` — ${selectedCategory.name}` : ""}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Available under this category
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                disabled={!selectedCategoryId}
                onClick={() => setAssignDialogOpen(true)}
              >
                Add existing
              </Button>
              <Button
                size="small"
                startIcon={<AddIcon />}
                disabled={!selectedCategoryId}
                onClick={() => setRoleDialog({ name: "", assign: true })}
              >
                New role
              </Button>
            </Stack>
          </Stack>

          {!selectedCategoryId ? (
            <Typography color="text.secondary">Select a category</Typography>
          ) : assignments.length === 0 ? (
            <Typography color="text.secondary">No roles assigned yet.</Typography>
          ) : (
            <Stack spacing={0.75}>
              {assignments.map((row, idx) => (
                <Paper key={row.id} variant="outlined" sx={{ p: 1.25 }}>
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <Stack direction="row" spacing={0}>
                      <IconButton size="small" disabled={idx === 0} onClick={() => moveAssignment(idx, -1)}>
                        <ArrowUpwardIcon fontSize="inherit" />
                      </IconButton>
                      <IconButton
                        size="small"
                        disabled={idx === assignments.length - 1}
                        onClick={() => moveAssignment(idx, 1)}
                      >
                        <ArrowDownwardIcon fontSize="inherit" />
                      </IconButton>
                    </Stack>
                    <Box sx={{ flex: 1 }}>
                      <Typography fontWeight={700}>{row.role_name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {selectedCategory?.name} — {row.role_name}
                      </Typography>
                    </Box>
                    <Chip
                      size="small"
                      label={row.active ? "Active" : "Inactive"}
                      color={row.active ? "success" : "default"}
                      onClick={() => toggleAssignment(row)}
                    />
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </Paper>
      </Stack>

      <Dialog open={!!catDialog} onClose={() => !busy && setCatDialog(null)} fullWidth maxWidth="xs">
        <DialogTitle>{catDialog?.id ? "Edit category" : "Add category"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="Category name"
              value={catDialog?.name || ""}
              onChange={(e) => setCatDialog((p) => ({ ...p, name: e.target.value }))}
              fullWidth
              autoFocus
              helperText={catDialog?.id ? "Code stays the same when renamed." : "Operator and Folder will be assigned automatically."}
            />
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography variant="body2">Active</Typography>
              <Switch
                checked={!!catDialog?.active}
                onChange={(e) => setCatDialog((p) => ({ ...p, active: e.target.checked }))}
              />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCatDialog(null)} disabled={busy}>Cancel</Button>
          <Button variant="contained" onClick={saveCategory} disabled={busy || !catDialog?.name?.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!roleDialog} onClose={() => !busy && setRoleDialog(null)} fullWidth maxWidth="xs">
        <DialogTitle>Create role</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="Role name"
              value={roleDialog?.name || ""}
              onChange={(e) => setRoleDialog((p) => ({ ...p, name: e.target.value }))}
              fullWidth
              autoFocus
              placeholder="e.g. Quality Control"
            />
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography variant="body2">Assign to selected category</Typography>
              <Switch
                checked={!!roleDialog?.assign}
                onChange={(e) => setRoleDialog((p) => ({ ...p, assign: e.target.checked }))}
              />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRoleDialog(null)} disabled={busy}>Cancel</Button>
          <Button variant="contained" onClick={createAndAssignRole} disabled={busy || !roleDialog?.name?.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={assignDialogOpen} onClose={() => !busy && setAssignDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Add existing role</DialogTitle>
        <DialogContent>
          <FormControl fullWidth size="small" sx={{ mt: 1 }}>
            <InputLabel>Role</InputLabel>
            <Select
              label="Role"
              value={assignRoleId}
              onChange={(e) => setAssignRoleId(e.target.value)}
            >
              {unassignedRoles.map((r) => (
                <MenuItem key={r.id} value={String(r.id)}>
                  {r.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {unassignedRoles.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              All active roles are already assigned, or create a new role.
            </Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAssignDialogOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="contained" onClick={assignExistingRole} disabled={busy || !assignRoleId}>
            Assign
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
