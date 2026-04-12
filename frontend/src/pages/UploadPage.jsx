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
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Refresh } from "@mui/icons-material";
import {
  addUploadBatchRow,
  confirmUploadBatch,
  deleteUploadBatch,
  deleteUploadBatchRow,
  getUploadBatches,
  getCurrentUploadBatch,
  getUploadBatchRows,
  overrideUploadBatchRow,
  uploadOrders,
} from "../api";
import StagingOrderManagementTable from "../components/StagingOrderManagementTable";

const EMPTY_FORM = {
  date_clean: "",
  name_clean: "",
  weight_num: "",
  service_type: "WF",
  rush_type: "NON-RUSH",
  row_status: "OVERRIDDEN",
  reason: "",
};

function UploadPage({ user }) {
  const [file, setFile] = useState(null);
  const [batchDate, setBatchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [batch, setBatch] = useState(null);
  const [batches, setBatches] = useState([]);
  const [rows, setRows] = useState([]);
  const [viewTab, setViewTab] = useState("REVIEW");
  const [rowStatusFilter, setRowStatusFilter] = useState("ALL");

  const [editOpen, setEditOpen] = useState(false);
  const [editRowId, setEditRowId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState(EMPTY_FORM);

  const [message, setMessage] = useState({ type: "info", text: "" });

  const isConfirmed = (batch?.state || "").toUpperCase() === "CONFIRMED";
  const isDraft = (batch?.state || "").toUpperCase() === "DRAFT";

  const formatBatchLabel = (row) => {
    if (!row) return "No active batch";
    const dtSource = row.created_at || row.updated_at || row.confirmed_at || row.closed_at;
    const dt = dtSource ? new Date(dtSource) : null;
    const dtLabel = dt && !Number.isNaN(dt.getTime())
      ? dt.toLocaleString(undefined, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "No time";
    return `Batch #${row.id} • ${dtLabel}`;
  };

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
        setViewTab("REVIEW");
      } else {
        setRows([]);
      }
    } catch (error) {
      console.error(error);
      setMessage({ type: "error", text: "Failed to load current batch." });
    }
  };

  const loadBatchHistory = async () => {
    try {
      const res = await getUploadBatches(15);
      setBatches(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    loadCurrentBatch("ALL");
    loadBatchHistory();
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
      await loadBatchHistory();
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
      row_status: row.row_status || "OVERRIDDEN",
      reason: row.reason || "",
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
      await loadBatchHistory();
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
      await loadBatchHistory();
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
      await loadBatchHistory();
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
      await loadBatchHistory();
      window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
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
          await loadBatchHistory();
          window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
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

  const handleDeleteBatch = async (batchId) => {
    const ok = window.confirm(
      `Delete batch #${batchId}? This removes the batch and will also clean matching staging/final/checkout/processing records.`
    );
    if (!ok) return;

    try {
      setLoading(true);
      const res = await deleteUploadBatch(batchId, true);
      if (batch?.id === batchId) {
        setBatch(null);
        setRows([]);
      }
      const c = res?.data?.cascade_deleted || {};
      setMessage({
        type: "success",
        text: `Batch #${batchId} deleted. Cleared staging:${c.orders_staging || 0}, final:${c.orders_final || 0}, checkout:${c.checkout_log || 0}, processing:${c.order_processing || 0}.`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
      window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Batch delete failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box className="page">
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 28, fontWeight: 500 }}>Upload Orders</Typography>
        <Button
          variant="text"
          size="small"
          startIcon={<Refresh />}
          onClick={() => {
            loadCurrentBatch("ALL");
            loadBatchHistory();
          }}
          disabled={loading || loadingRows}
        >
          Refresh
        </Button>
      </Stack>

      {batch && (
        <Stack direction="row" spacing={1} sx={{ mt: 0.8, flexWrap: "wrap" }}>
          <Chip
            label={formatBatchLabel(batch)}
            color="primary"
            variant="outlined"
          />
          <Chip
            label={(batch.state || "DRAFT").toUpperCase()}
            color={isConfirmed ? "success" : "warning"}
          />
        </Stack>
      )}

      {(message.text || isDraft) && (
        <Alert
          severity={message.type === "error" ? "error" : message.type === "warning" ? "warning" : "success"}
          sx={{ mt: 1, borderRadius: 2 }}
        >
          {message.text || "Ready."}
          {isDraft ? " • Draft only, not live until Confirm Batch." : ""}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 14 }}>Batch Date</Typography>
            <TextField
              type="date"
              size="small"
              value={batchDate}
              onChange={(e) => setBatchDate(e.target.value)}
            />
          </Stack>

          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 14 }}>File</Typography>
            <input
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </Stack>

          <Button variant="contained" onClick={uploadFile} disabled={loading}>
            {loading ? "Uploading..." : "Upload Draft"}
          </Button>

          <Button variant="outlined" onClick={() => loadCurrentBatch(rowStatusFilter)} disabled={loading || loadingRows}>
            Refresh
          </Button>
        </Stack>
      </Paper>

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs
          value={viewTab}
          onChange={(_, next) => setViewTab(next)}
          variant="fullWidth"
        >
          <Tab value="REVIEW" label="Draft Review" />
          <Tab value="BATCHES" label="Uploaded Batches" />
        </Tabs>
      </Paper>

      {batch && viewTab === "REVIEW" && (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} justifyContent="space-between" alignItems={{ md: "center" }}>
            <Box>
              <Typography sx={{ fontSize: 20, fontWeight: 500 }}>{formatBatchLabel(batch)}</Typography>
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
                    <TableCell>
                      {String(row.service_type || "").toUpperCase() === "HD"
                        ? `${Math.round(Number(row.weight_num || 0))} pcs`
                        : row.weight_num == null
                          ? "-"
                          : `${Number(row.weight_num).toFixed(2)} lb`}
                    </TableCell>
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

          {isConfirmed && batch?.batch_date && (
            <StagingOrderManagementTable
              batchDate={batch.batch_date}
              user={user}
              onOrdersChanged={() => window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"))}
            />
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
            <TextField
              select
              label="Row Status"
              value={editForm.row_status}
              onChange={(e) => setEditForm((p) => ({ ...p, row_status: e.target.value }))}
            >
              <MenuItem value="ACCEPTED">ACCEPTED</MenuItem>
              <MenuItem value="OVERRIDDEN">OVERRIDDEN</MenuItem>
              <MenuItem value="NEEDS_ATTENTION">NEEDS_ATTENTION</MenuItem>
              <MenuItem value="REJECTED_DUPLICATE">REJECTED_DUPLICATE</MenuItem>
              <MenuItem value="DELETED">DELETED</MenuItem>
            </TextField>
            <TextField
              label="Reason"
              value={editForm.reason}
              onChange={(e) => setEditForm((p) => ({ ...p, reason: e.target.value }))}
            />
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

      {viewTab === "BATCHES" && (
      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontSize: 18, fontWeight: 500, mb: 1 }}>Uploaded Batches</Typography>
        <Stack spacing={0.8}>
          {batches.length === 0 ? (
            <Typography color="text.secondary">No batches yet.</Typography>
          ) : (
            batches.map((b) => (
              <Stack
                key={b.id}
                direction="row"
                spacing={1}
                alignItems="center"
                justifyContent="space-between"
                sx={{ border: "1px solid #e5e7eb", borderRadius: 1.5, p: 1 }}
              >
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap" }}>
                  <Typography sx={{ fontWeight: 500 }}>{formatBatchLabel(b)}</Typography>
                  <Chip
                    size="small"
                    label={(b.state || "DRAFT").toUpperCase()}
                    color={String(b.state || "").toUpperCase() === "CONFIRMED" ? "success" : "warning"}
                  />
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography color="text.secondary">
                    Loaded {b.orders_loaded || 0}
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={async () => {
                      setBatch(b);
                      await loadRows(b.id, "ALL");
                      setRowStatusFilter("ALL");
                      setViewTab("REVIEW");
                    }}
                  >
                    View
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    onClick={() => handleDeleteBatch(b.id)}
                    disabled={loading}
                  >
                    Delete
                  </Button>
                </Stack>
              </Stack>
            ))
          )}
        </Stack>
      </Paper>
      )}
    </Box>
  );
}

export default UploadPage;
