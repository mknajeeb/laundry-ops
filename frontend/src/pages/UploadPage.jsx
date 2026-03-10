import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Paper,
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
  addUploadBatchRow,
  confirmUploadBatch,
  deleteUploadBatchRow,
  getCurrentUploadBatch,
  getUploadBatchRows,
  overrideUploadBatchRow,
  uploadOrders,
} from "../api";

const EMPTY_FORM = {
  date_clean: "",
  name_clean: "",
  weight_num: "",
  service_type: "WF",
  rush_type: "NON-RUSH",
};

function UploadPage() {
  const [file, setFile] = useState(null);
  const [batchDate, setBatchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [batch, setBatch] = useState(null);
  const [rows, setRows] = useState([]);
  const [rowStatusFilter, setRowStatusFilter] = useState("ALL");

  const [editOpen, setEditOpen] = useState(false);
  const [editRowId, setEditRowId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState(EMPTY_FORM);

  const [message, setMessage] = useState({ type: "info", text: "" });

  const isConfirmed = (batch?.state || "").toUpperCase() === "CONFIRMED";

  const filteredRows = useMemo(() => {
    if (rowStatusFilter === "ALL") return rows;
    return rows.filter((r) => String(r.row_status || "").toUpperCase() === rowStatusFilter);
  }, [rows, rowStatusFilter]);

  const rowSummary = useMemo(() => {
    const byStatus = {
      ACCEPTED: 0,
      OVERRIDDEN: 0,
      REJECTED_DUPLICATE: 0,
      NEEDS_ATTENTION: 0,
      DELETED: 0,
    };

    rows.forEach((r) => {
      const key = String(r.row_status || "").toUpperCase();
      if (Object.prototype.hasOwnProperty.call(byStatus, key)) byStatus[key] += 1;
    });

    return byStatus;
  }, [rows]);

  const loadRows = async (batchId, statusFilter = "") => {
    if (!batchId) {
      setRows([]);
      return;
    }

    try {
      setLoadingRows(true);
      const res = await getUploadBatchRows(batchId, statusFilter === "ALL" ? "" : statusFilter);
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      setRows([]);
      setMessage({ type: "error", text: "Failed to load batch rows." });
    } finally {
      setLoadingRows(false);
    }
  };

  const loadCurrentBatch = async (statusFilter = rowStatusFilter) => {
    try {
      const res = await getCurrentUploadBatch();
      const current = res?.data || null;
      setBatch(current);

      if (current?.batch_date) {
        const d = String(current.batch_date).slice(0, 10);
        setBatchDate(d);
      }

      if (current?.id) {
        await loadRows(current.id, statusFilter);
      } else {
        setRows([]);
      }
    } catch (error) {
      console.error(error);
      setMessage({ type: "error", text: "Failed to load current batch." });
    }
  };

  useEffect(() => {
    loadCurrentBatch("ALL");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const uploadFile = async () => {
    if (!file) {
      setMessage({ type: "warning", text: "Please choose a file first." });
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("batch_date", batchDate);

    try {
      setLoading(true);
      const res = await uploadOrders(formData);
      setMessage({
        type: "success",
        text: `Draft uploaded. Accepted: ${res.data.rows_inserted}, Rejected: ${res.data.rejected_rows}, Needs Attention: ${res.data.needs_attention_rows}`,
      });
      await loadCurrentBatch("ALL");
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Upload failed";
      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const openEdit = (row) => {
    setEditRowId(row.id);
    setEditForm({
      date_clean: String(row.date_clean || "").slice(0, 10),
      name_clean: row.name_clean || "",
      weight_num: row.weight_num ?? "",
      service_type: row.service_type || "WF",
      rush_type: row.rush_type || "NON-RUSH",
    });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    if (!batch?.id || !editRowId) return;

    try {
      setLoading(true);
      await overrideUploadBatchRow(batch.id, editRowId, {
        ...editForm,
        weight_num: editForm.weight_num === "" ? null : Number(editForm.weight_num),
      });
      setEditOpen(false);
      setMessage({ type: "success", text: "Row updated." });
      await loadCurrentBatch(rowStatusFilter);
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Row update failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (rowId) => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await deleteUploadBatchRow(batch.id, rowId);
      setMessage({ type: "success", text: "Row deleted from batch." });
      await loadCurrentBatch(rowStatusFilter);
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Delete failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await addUploadBatchRow(batch.id, {
        ...addForm,
        weight_num: addForm.weight_num === "" ? null : Number(addForm.weight_num),
      });
      setAddOpen(false);
      setAddForm(EMPTY_FORM);
      setMessage({ type: "success", text: "Row added to batch." });
      await loadCurrentBatch(rowStatusFilter);
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Add row failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!batch?.id) return;

    try {
      setLoading(true);
      await confirmUploadBatch(batch.id, false);
      setMessage({ type: "success", text: "Batch confirmed and applied to staging." });
      await loadCurrentBatch(rowStatusFilter);
    } catch (error) {
      const status = error?.response?.status;
      const data = error?.response?.data || {};

      if (status === 409 && data.attention_count) {
        const ok = window.confirm(
          `${data.attention_count} rows still need attention. Confirm anyway?`
        );
        if (ok) {
          await confirmUploadBatch(batch.id, true);
          setMessage({ type: "success", text: "Batch force-confirmed and applied." });
          await loadCurrentBatch(rowStatusFilter);
        }
      } else {
        setMessage({
          type: "error",
          text: data.error || "Batch confirm failed.",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const onFilterChange = async (nextFilter) => {
    setRowStatusFilter(nextFilter);
    await loadRows(batch?.id, nextFilter);
  };

  return (
    <Box className="page">
      <Typography sx={{ fontSize: 28, fontWeight: 900 }}>Upload Orders</Typography>

      {message.text && (
        <Alert severity={message.type} sx={{ mt: 1.2 }}>
          {message.text}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 700, fontSize: 14 }}>Batch Date</Typography>
            <TextField
              type="date"
              size="small"
              value={batchDate}
              onChange={(e) => setBatchDate(e.target.value)}
            />
          </Stack>

          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 700, fontSize: 14 }}>File</Typography>
            <input
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </Stack>

          <Button variant="contained" onClick={uploadFile} disabled={loading}>
            {loading ? "Uploading..." : "Upload Draft"}
          </Button>

          <Button
            variant="outlined"
            onClick={() => loadCurrentBatch(rowStatusFilter)}
            disabled={loading || loadingRows}
          >
            Refresh
          </Button>
        </Stack>
      </Paper>

      {batch && (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} justifyContent="space-between" alignItems={{ md: "center" }}>
            <Box>
              <Typography sx={{ fontSize: 20, fontWeight: 900 }}>Batch #{batch.id}</Typography>
              <Typography color="text.secondary">
                Date {String(batch.batch_date || "").slice(0, 10)} • State {batch.state || "DRAFT"}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1}>
              <Button variant="outlined" onClick={() => setAddOpen(true)} disabled={isConfirmed || loading}>
                Add Row
              </Button>
              <Button variant="contained" onClick={handleConfirm} disabled={isConfirmed || loading}>
                {isConfirmed ? "Confirmed" : "Confirm Batch"}
              </Button>
            </Stack>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ mt: 1.2, flexWrap: "wrap" }}>
            <Chip label={`Accepted ${rowSummary.ACCEPTED + rowSummary.OVERRIDDEN}`} color="success" />
            <Chip label={`Needs Attention ${rowSummary.NEEDS_ATTENTION}`} color="warning" />
            <Chip label={`Rejected ${rowSummary.REJECTED_DUPLICATE}`} color="error" />
            <Chip label={`Deleted ${rowSummary.DELETED}`} variant="outlined" />
          </Stack>

          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
            {["ALL", "ACCEPTED", "OVERRIDDEN", "NEEDS_ATTENTION", "REJECTED_DUPLICATE", "DELETED"].map((x) => (
              <Chip
                key={x}
                label={x}
                clickable
                color={rowStatusFilter === x ? "primary" : "default"}
                onClick={() => onFilterChange(x)}
              />
            ))}
          </Stack>

          {loadingRows ? (
            <Stack alignItems="center" sx={{ py: 2 }}>
              <CircularProgress size={24} />
            </Stack>
          ) : (
            <Table size="small" sx={{ mt: 1 }}>
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Date</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Weight/Count</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Rush</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Reason</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.id}</TableCell>
                    <TableCell>{String(row.date_clean || "").slice(0, 10)}</TableCell>
                    <TableCell>{row.name_clean}</TableCell>
                    <TableCell>{row.weight_num ?? "-"}</TableCell>
                    <TableCell>{row.service_type}</TableCell>
                    <TableCell>{row.rush_type}</TableCell>
                    <TableCell>{row.row_status}</TableCell>
                    <TableCell>{row.reason || "-"}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.6}>
                        <Button size="small" variant="outlined" onClick={() => openEdit(row)} disabled={isConfirmed}>
                          Edit
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          onClick={() => handleDelete(row.id)}
                          disabled={isConfirmed}
                        >
                          Delete
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Paper>
      )}

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Batch Row</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.6 }}>
            <TextField
              label="Date"
              type="date"
              value={editForm.date_clean}
              onChange={(e) => setEditForm((p) => ({ ...p, date_clean: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Name"
              value={editForm.name_clean}
              onChange={(e) => setEditForm((p) => ({ ...p, name_clean: e.target.value }))}
            />
            <TextField
              label="Weight / Count"
              type="number"
              value={editForm.weight_num}
              onChange={(e) => setEditForm((p) => ({ ...p, weight_num: e.target.value }))}
            />
            <TextField
              select
              label="Service"
              value={editForm.service_type}
              onChange={(e) => setEditForm((p) => ({ ...p, service_type: e.target.value }))}
            >
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <TextField
              select
              label="Rush"
              value={editForm.rush_type}
              onChange={(e) => setEditForm((p) => ({ ...p, rush_type: e.target.value }))}
            >
              <MenuItem value="RUSH">RUSH</MenuItem>
              <MenuItem value="NON-RUSH">NON-RUSH</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveEdit} disabled={loading}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add New Batch Row</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.6 }}>
            <TextField
              label="Date"
              type="date"
              value={addForm.date_clean}
              onChange={(e) => setAddForm((p) => ({ ...p, date_clean: e.target.value }))}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="Name"
              value={addForm.name_clean}
              onChange={(e) => setAddForm((p) => ({ ...p, name_clean: e.target.value }))}
            />
            <TextField
              label="Weight / Count"
              type="number"
              value={addForm.weight_num}
              onChange={(e) => setAddForm((p) => ({ ...p, weight_num: e.target.value }))}
            />
            <TextField
              select
              label="Service"
              value={addForm.service_type}
              onChange={(e) => setAddForm((p) => ({ ...p, service_type: e.target.value }))}
            >
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </TextField>
            <TextField
              select
              label="Rush"
              value={addForm.rush_type}
              onChange={(e) => setAddForm((p) => ({ ...p, rush_type: e.target.value }))}
            >
              <MenuItem value="RUSH">RUSH</MenuItem>
              <MenuItem value="NON-RUSH">NON-RUSH</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleAdd} disabled={loading}>Add</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default UploadPage;
