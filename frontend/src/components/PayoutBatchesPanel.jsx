import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
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
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import PrintIcon from "@mui/icons-material/Print";
import VisibilityIcon from "@mui/icons-material/Visibility";
import {
  deletePayoutBatch,
  getContractors,
  getPayoutBatch,
  getPayoutBatches,
  patchPayoutBatch,
  postPayoutBatch,
} from "../api";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { ContractorPrintLetterhead } from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const BATCH_STATUS_FLOW = [
  { value: "draft", label: "Draft" },
  { value: "hours_reviewed", label: "Hours reviewed" },
  { value: "sent_to_accountant", label: "Sent to accountant" },
  { value: "accountant_reviewed", label: "Accountant reviewed" },
  { value: "approved_for_payment", label: "Approved for payment" },
  { value: "paid", label: "Paid" },
  { value: "closed", label: "Closed" },
];

const CATEGORY_BATCH = WORKER_CATEGORY_OPTIONS.filter((o) => o.value !== "all");

function lineStatusLabel(st) {
  if (st === "pending" || st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  return st || "—";
}

function PayoutBatchSummaryPrint({ batch }) {
  const b = batch || {};
  const lines = b.lines || [];
  return (
    <div className="contractor-print-root">
      <ContractorPrintLetterhead
        prefill={{ company_name: "VeeWash / Washpro" }}
        documentTitle="Payroll / Contractor Payout Summary"
      />
      <p className="cform-p">
        <strong>Pay period:</strong> {b.pay_period_start} – {b.pay_period_end}
        <br />
        <strong>Category:</strong> {b.worker_category_label || b.worker_category}
        <br />
        <strong>Status:</strong> {b.status}
      </p>
      <table className="contractor-payment-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Worker</th>
            <th>Hours</th>
            <th>Rate</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((ln) => (
            <tr key={ln.id}>
              <td style={{ textAlign: "left" }}>{ln.worker_name_snapshot}</td>
              <td>{Number(ln.approved_hours || 0).toFixed(2)}</td>
              <td>${Number(ln.rate || 0).toFixed(2)}</td>
              <td>
                <strong>${Number(ln.total_amount || 0).toFixed(2)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PayoutBatchesPanel() {
  const printRef = useRef(null);
  const [filterCat, setFilterCat] = useState("all");
  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [lineEdit, setLineEdit] = useState(null);
  const [draft, setDraft] = useState({
    batch_name: "",
    worker_category: "temp",
    pay_period_start: "",
    pay_period_end: "",
    payout_frequency: "biweekly",
    notes: "",
  });
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);

  const loadList = useCallback(async () => {
    setError("");
    try {
      const params = filterCat !== "all" ? { worker_category: filterCat } : {};
      const res = await getPayoutBatches(params);
      setBatches(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [filterCat]);

  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const res = await getPayoutBatch(id);
      setDetail(res.data);
      setSelectedId(id);
    } catch (e) {
      setError(e.response?.data?.error || "Load batch failed");
    }
  }, []);

  useEffect(() => {
    loadList();
    getContractors().catch(() => {});
  }, [loadList]);

  const createBatch = async () => {
    try {
      const res = await postPayoutBatch(draft);
      setCreateOpen(false);
      setInfo("Batch created. Approve time on the Time Records tab, then pull hours here.");
      await loadList();
      await loadDetail(res.data.id);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Create failed");
    }
  };

  const saveBatchEdit = async () => {
    try {
      const res = await patchPayoutBatch(selectedId, {
        action: "update_batch",
        batch_name: draft.batch_name,
        pay_period_start: draft.pay_period_start,
        pay_period_end: draft.pay_period_end,
        payout_frequency: draft.payout_frequency,
        notes: draft.notes,
      });
      setDetail(res.data);
      setEditOpen(false);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    }
  };

  const confirmDeleteBatch = async () => {
    try {
      await deletePayoutBatch(selectedId);
      setDeleteOpen(false);
      setDetail(null);
      setSelectedId(null);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    }
  };

  const pullHours = async () => {
    if (!selectedId || !detail) return;
    setInfo("");
    setError("");
    try {
      const res = await patchPayoutBatch(selectedId, {
        action: "build_from_time_records",
        from_date: detail.pay_period_start,
        to_date: detail.pay_period_end,
      });
      setDetail(res.data);
      setInfo(`Pulled ${res.data?.lines?.length || 0} worker line(s) from approved time records.`);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Pull failed");
    }
  };

  const setBatchStatus = async (status) => {
    try {
      const res = await patchPayoutBatch(selectedId, { status });
      setDetail(res.data);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Status update failed");
    }
  };

  const saveLineEdit = async () => {
    if (!lineEdit?.id) return;
    try {
      await patchPayoutBatch(selectedId, {
        action: "update_line",
        line_id: lineEdit.id,
        approved_hours: lineEdit.approved_hours,
        rate: lineEdit.rate,
        adjustments: lineEdit.adjustments,
      });
      setLineEdit(null);
      await loadDetail(selectedId);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Line save failed");
    }
  };

  const removeLine = async (lineId) => {
    if (!window.confirm("Remove this worker from the batch?")) return;
    try {
      const res = await patchPayoutBatch(selectedId, { action: "delete_line", line_id: lineId });
      setDetail(res.data);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete line failed");
    }
  };

  const downloadCsv = () => {
    if (!detail?.lines?.length) return;
    const header = ["Worker", "Hours", "Rate", "Gross", "Adjustments", "Total"];
    const lines = detail.lines.map((ln) =>
      [ln.worker_name_snapshot, ln.approved_hours, ln.rate, ln.gross_amount, ln.adjustments, ln.total_amount].join(
        ",",
      ),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `payout-batch-${detail.id}.csv`;
    a.click();
  };

  const isDraft = detail?.status === "draft";

  const openEditBatch = () => {
    setDraft({
      batch_name: detail.batch_name || "",
      worker_category: detail.worker_category || "temp",
      pay_period_start: detail.pay_period_start || "",
      pay_period_end: detail.pay_period_end || "",
      payout_frequency: detail.payout_frequency || "biweekly",
      notes: detail.notes || "",
    });
    setEditOpen(true);
  };

  const batchFormFields = (
    <Stack spacing={2}>
      <TextField
        label="Batch name"
        size="small"
        value={draft.batch_name}
        onChange={(e) => setDraft({ ...draft, batch_name: e.target.value })}
      />
      <FormControl fullWidth size="small" disabled={!!detail}>
        <InputLabel>Worker category</InputLabel>
        <Select
          label="Worker category"
          value={draft.worker_category}
          onChange={(e) => setDraft({ ...draft, worker_category: e.target.value })}
        >
          {CATEGORY_BATCH.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          fullWidth
          size="small"
          type="date"
          label="Period start"
          InputLabelProps={{ shrink: true }}
          value={draft.pay_period_start}
          onChange={(e) => setDraft({ ...draft, pay_period_start: e.target.value })}
        />
        <TextField
          fullWidth
          size="small"
          type="date"
          label="Period end"
          InputLabelProps={{ shrink: true }}
          value={draft.pay_period_end}
          onChange={(e) => setDraft({ ...draft, pay_period_end: e.target.value })}
        />
      </Stack>
      <FormControl fullWidth size="small">
        <InputLabel>Frequency</InputLabel>
        <Select
          label="Frequency"
          value={draft.payout_frequency}
          onChange={(e) => setDraft({ ...draft, payout_frequency: e.target.value })}
        >
          <MenuItem value="weekly">Weekly</MenuItem>
          <MenuItem value="biweekly">Biweekly</MenuItem>
        </Select>
      </FormControl>
      <TextField
        label="Notes"
        size="small"
        multiline
        minRows={2}
        value={draft.notes}
        onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
      />
    </Stack>
  );

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {info ? (
        <Alert severity="info" onClose={() => setInfo("")}>
          {info}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Box>
            <Typography variant="h6">Payout batches</Typography>
            <Typography variant="body2" color="text.secondary">
              Step 1: Approve hours on <strong>Time Records</strong>. Step 2: Create a batch and
              pull approved hours. One batch per worker category.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Filter</InputLabel>
              <Select label="Filter" value={filterCat} onChange={(e) => setFilterCat(e.target.value)}>
                {WORKER_CATEGORY_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              New batch
            </Button>
          </Stack>
        </Stack>
      </Paper>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch">
        <Paper sx={{ width: { xs: "100%", lg: 280 }, flexShrink: 0 }}>
          <Typography variant="subtitle2" sx={{ px: 2, pt: 1.5 }}>
            Batches
          </Typography>
          <List dense sx={{ maxHeight: 480, overflow: "auto" }}>
            {batches.map((b) => (
              <ListItemButton
                key={b.id}
                selected={selectedId === b.id}
                onClick={() => loadDetail(b.id)}
              >
                <ListItemText
                  primary={b.batch_name}
                  secondary={`${b.pay_period_start} – ${b.pay_period_end}`}
                  primaryTypographyProps={{ noWrap: true }}
                />
                <Chip size="small" label={b.status} sx={{ ml: 1 }} />
              </ListItemButton>
            ))}
            {!batches.length ? (
              <Typography sx={{ p: 2 }} variant="body2" color="text.secondary">
                No batches yet.
              </Typography>
            ) : null}
          </List>
        </Paper>

        <Paper sx={{ flex: 1, p: 2, minWidth: 0 }}>
          {!detail ? (
            <Typography color="text.secondary">Select a batch to view or edit.</Typography>
          ) : (
            <>
              <Stack
                direction={{ xs: "column", md: "row" }}
                justifyContent="space-between"
                spacing={1}
                sx={{ mb: 2 }}
              >
                <Box>
                  <Typography variant="h6">{detail.batch_name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {detail.worker_category_label} · {detail.pay_period_start} –{" "}
                    {detail.pay_period_end}
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5 }}>
                    <strong>${Number(detail.total_payout_amount || 0).toFixed(2)}</strong> ·{" "}
                    {detail.worker_count} worker(s) · {Number(detail.total_approved_hours || 0).toFixed(2)}{" "}
                    hrs
                  </Typography>
                </Box>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  <Tooltip title="View details">
                    <IconButton size="small" onClick={() => loadDetail(detail.id)}>
                      <VisibilityIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Edit batch">
                    <span>
                      <IconButton size="small" onClick={openEditBatch} disabled={!isDraft}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Tooltip title="Delete batch">
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setDeleteOpen(true)}
                        disabled={!isDraft}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Stack>
              </Stack>

              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
                <Button size="small" variant="contained" onClick={pullHours}>
                  Pull approved hours
                </Button>
                <FormControl size="small" sx={{ minWidth: 200 }}>
                  <InputLabel>Batch status</InputLabel>
                  <Select
                    label="Batch status"
                    value={detail.status || "draft"}
                    onChange={(e) => setBatchStatus(e.target.value)}
                  >
                    {BATCH_STATUS_FLOW.map((s) => (
                      <MenuItem key={s.value} value={s.value}>
                        {s.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button size="small" variant="outlined" startIcon={<PrintIcon />} onClick={() => setPrintPreviewOpen(true)}>
                  Print preview
                </Button>
                <Button size="small" variant="outlined" onClick={() => openPrintWindow(printRef.current)}>
                  Print
                </Button>
                <Button size="small" variant="outlined" onClick={downloadCsv} disabled={!detail.lines?.length}>
                  CSV
                </Button>
              </Stack>

              <Divider sx={{ mb: 2 }} />

              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Worker</TableCell>
                      <TableCell align="right">Hours</TableCell>
                      <TableCell align="right">Rate</TableCell>
                      <TableCell align="right">Total</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(detail.lines || []).map((ln) => (
                      <TableRow key={ln.id} hover>
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                        <TableCell align="right">{Number(ln.approved_hours || 0).toFixed(2)}</TableCell>
                        <TableCell align="right">${Number(ln.rate || 0).toFixed(2)}</TableCell>
                        <TableCell align="right">${Number(ln.total_amount || 0).toFixed(2)}</TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={ln.line_status === "approved" ? "success" : "warning"}
                            label={lineStatusLabel(ln.line_status)}
                          />
                        </TableCell>
                        <TableCell align="right">
                          <IconButton size="small" onClick={() => setLineEdit({ ...ln })} disabled={!isDraft}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => removeLine(ln.id)}
                            disabled={!isDraft}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    ))}
                    {!detail.lines?.length ? (
                      <TableRow>
                        <TableCell colSpan={6}>
                          <Typography variant="body2" color="text.secondary">
                            No workers in this batch. Approve time records, then click Pull approved hours.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </Paper>
      </Stack>

      <ContractorPrintPreviewDialog
        open={printPreviewOpen}
        onClose={() => setPrintPreviewOpen(false)}
        title="Payout summary"
        printRef={printRef}
      />
      <Box ref={printRef} sx={{ position: "absolute", left: -9999, visibility: "hidden", width: "7.5in" }}>
        {detail ? <PayoutBatchSummaryPrint batch={detail} /> : null}
      </Box>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New payout batch</DialogTitle>
        <DialogContent>{batchFormFields}</DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={createBatch}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit batch</DialogTitle>
        <DialogContent>{batchFormFields}</DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveBatchEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}>
        <DialogTitle>Delete batch?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Delete <strong>{detail?.batch_name}</strong>? Only draft batches can be deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDeleteBatch}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!lineEdit} onClose={() => setLineEdit(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Edit line</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2">{lineEdit?.worker_name_snapshot}</Typography>
            <TextField
              size="small"
              type="number"
              label="Hours"
              value={lineEdit?.approved_hours ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, approved_hours: e.target.value })}
            />
            <TextField
              size="small"
              type="number"
              label="Rate"
              value={lineEdit?.rate ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, rate: e.target.value })}
            />
            <TextField
              size="small"
              type="number"
              label="Adjustments"
              value={lineEdit?.adjustments ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, adjustments: e.target.value })}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLineEdit(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveLineEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
