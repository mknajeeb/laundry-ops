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
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import BlockIcon from "@mui/icons-material/Block";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import {
  createPayrollVendor,
  listPayrollVendors,
  updatePayrollVendor,
} from "../api";

const EMPTY_FORM = {
  name: "",
  address: "",
  logo_url: "",
  representative_name: "",
  representative_title: "",
};

export default function PayrollVendorsPanel() {
  const [vendors, setVendors] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await listPayrollVendors({ includeInactive: true });
      setVendors(res.data?.vendors || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (vendor) => {
    setEditing(vendor);
    setForm({
      name: vendor.name || "",
      address: vendor.address || "",
      logo_url: vendor.logo_url || "",
      representative_name: vendor.representative_name || "",
      representative_title: vendor.representative_title || "",
    });
    setDialogOpen(true);
  };

  const save = async () => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (editing) {
        await updatePayrollVendor(editing.id, form);
        setNotice(`Vendor "${form.name}" updated.`);
      } else {
        await createPayrollVendor(form);
        setNotice(`Vendor "${form.name}" added.`);
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (vendor) => {
    setError("");
    setNotice("");
    try {
      await updatePayrollVendor(vendor.id, { active: !vendor.active });
      setNotice(
        `Vendor "${vendor.name}" ${vendor.active ? "deactivated" : "reactivated"}.`,
      );
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Update failed");
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 1 }}
      >
        <Box>
          <Typography variant="h6">Staffing Vendors</Typography>
          <Typography variant="caption" color="text.secondary">
            Source companies for temp / 1099 workers. Vendor branding appears on the
            Contractor Invoice &amp; Payment Receipt (in place of a paystub). Vendors do
            not affect wages, taxes, gross, net, OT, or YTD amounts.
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          Add Vendor
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {notice ? (
        <Alert severity="success" sx={{ mb: 1 }} onClose={() => setNotice("")}>
          {notice}
        </Alert>
      ) : null}

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Vendor</TableCell>
              <TableCell>Address</TableCell>
              <TableCell>Representative</TableCell>
              <TableCell>Logo</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {vendors.map((v) => (
              <TableRow key={v.id} hover>
                <TableCell>
                  <Typography variant="body2" fontWeight={600}>
                    {v.name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" color="text.secondary">
                    {v.address || "—"}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" color="text.secondary">
                    {v.representative_name
                      ? `${v.representative_name}${
                          v.representative_title ? ` — ${v.representative_title}` : ""
                        }`
                      : "—"}
                  </Typography>
                </TableCell>
                <TableCell>
                  {v.logo_url ? (
                    <img
                      src={v.logo_url}
                      alt={v.name}
                      style={{ maxHeight: 28, maxWidth: 120, objectFit: "contain" }}
                    />
                  ) : (
                    <Typography variant="caption" color="text.secondary">
                      Text letterhead
                    </Typography>
                  )}
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    color={v.active ? "success" : "default"}
                    label={v.active ? "Active" : "Inactive"}
                  />
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="Edit">
                    <IconButton size="small" onClick={() => openEdit(v)}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={v.active ? "Deactivate" : "Reactivate"}>
                    <IconButton size="small" onClick={() => toggleActive(v)}>
                      {v.active ? (
                        <BlockIcon fontSize="small" />
                      ) : (
                        <CheckCircleIcon fontSize="small" />
                      )}
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {!vendors.length ? (
              <TableRow>
                <TableCell colSpan={6}>
                  <Typography variant="body2" color="text.secondary">
                    No vendors yet. Add one to brand temp / 1099 receipts.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "Edit Vendor" : "Add Vendor"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Vendor name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              fullWidth
            />
            <TextField
              label="Address"
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              multiline
              minRows={2}
              fullWidth
              helperText="Shown under the vendor name on the receipt letterhead."
            />
            <TextField
              label="Logo URL (optional)"
              value={form.logo_url}
              onChange={(e) => setForm({ ...form, logo_url: e.target.value })}
              fullWidth
              helperText="Leave blank to use a text letterhead."
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Representative name"
                value={form.representative_name}
                onChange={(e) => setForm({ ...form, representative_name: e.target.value })}
                fullWidth
                helperText="Person authorized to sign for the vendor (e.g. John Smith)."
              />
              <TextField
                label="Representative designation / title"
                value={form.representative_title}
                onChange={(e) => setForm({ ...form, representative_title: e.target.value })}
                fullWidth
                helperText="e.g. Manager"
              />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={save}
            disabled={saving || form.name.trim().length < 2}
          >
            {editing ? "Save Changes" : "Add Vendor"}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
