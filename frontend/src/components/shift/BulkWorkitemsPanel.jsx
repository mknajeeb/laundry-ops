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
  Stack,
  Switch,
  FormControlLabel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  createBulkWorkitem,
  deleteBulkWorkitem,
  getBulkWorkitems,
  updateBulkWorkitem,
} from "../../api";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

export default function BulkWorkitemsPanel() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({
    name: "",
    current_unit_price: "4.00",
    display_order: "100",
    active: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getBulkWorkitems({ include_inactive: true });
      setRows(res?.data?.workitems || []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load bulk workitems");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openNew = () => {
    setEdit({ mode: "create" });
    setForm({ name: "", current_unit_price: "4.00", display_order: "100", active: true });
  };

  const openEdit = (row) => {
    setEdit({ mode: "edit", id: row.id });
    setForm({
      name: row.name || "",
      current_unit_price: money(row.current_unit_price),
      display_order: String(row.display_order ?? 100),
      active: Boolean(row.active),
    });
  };

  const save = async () => {
    setError("");
    setMessage("");
    try {
      const body = {
        name: form.name.trim(),
        current_unit_price: Number(form.current_unit_price),
        display_order: Number(form.display_order) || 100,
        active: Boolean(form.active),
      };
      if (!body.name) {
        setError("Name is required");
        return;
      }
      if (edit?.mode === "create") {
        await createBulkWorkitem(body);
        setMessage("Workitem created.");
      } else {
        await updateBulkWorkitem(edit.id, body);
        setMessage("Workitem updated. Historical bag prices are unchanged.");
      }
      setEdit(null);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    }
  };

  const toggleActive = async (row) => {
    try {
      await updateBulkWorkitem(row.id, { active: !row.active });
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Update failed");
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`Delete "${row.name}"? Only unused workitems can be deleted.`)) return;
    try {
      await deleteBulkWorkitem(row.id);
      setMessage("Deleted.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Delete failed");
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="body2" color="text.secondary">
          Maintain chargeable bulk workitems (Bath Mat, Comforter, …). Price changes never rewrite
          historical bag totals.
        </Typography>
        <Button variant="contained" onClick={openNew} disabled={loading}>
          Add workitem
        </Button>
      </Stack>
      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {message ? (
        <Alert severity="success" sx={{ mb: 1 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Unit Price</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Order</TableCell>
            <TableCell>Updated</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>{row.name}</TableCell>
              <TableCell>${money(row.current_unit_price)}</TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={row.active ? "Active" : "Inactive"}
                  color={row.active ? "success" : "default"}
                  variant="outlined"
                />
              </TableCell>
              <TableCell>{row.display_order}</TableCell>
              <TableCell>
                <Typography variant="caption" display="block">
                  {row.updated_by_display_name || "—"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {row.updated_at ? String(row.updated_at).slice(0, 19) : "—"}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                  <Button size="small" onClick={() => openEdit(row)}>
                    Edit
                  </Button>
                  <Button size="small" onClick={() => toggleActive(row)}>
                    {row.active ? "Deactivate" : "Activate"}
                  </Button>
                  <Button size="small" color="error" onClick={() => remove(row)}>
                    Delete
                  </Button>
                </Stack>
              </TableCell>
            </TableRow>
          ))}
          {!rows.length && !loading ? (
            <TableRow>
              <TableCell colSpan={6}>No workitems yet — defaults seed on first load.</TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>

      <Dialog open={Boolean(edit)} onClose={() => setEdit(null)} fullWidth maxWidth="sm">
        <DialogTitle>{edit?.mode === "create" ? "Add bulk workitem" : "Edit bulk workitem"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              fullWidth
              size="small"
            />
            <TextField
              label="Unit price"
              type="number"
              value={form.current_unit_price}
              onChange={(e) => setForm((f) => ({ ...f, current_unit_price: e.target.value }))}
              fullWidth
              size="small"
              inputProps={{ min: 0, step: 0.01 }}
            />
            <TextField
              label="Display order"
              type="number"
              value={form.display_order}
              onChange={(e) => setForm((f) => ({ ...f, display_order: e.target.value }))}
              fullWidth
              size="small"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.active}
                  onChange={(e) => setForm((f) => ({ ...f, active: e.target.checked }))}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="contained" onClick={save}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
