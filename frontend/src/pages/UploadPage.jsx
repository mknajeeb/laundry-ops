import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  FormControl,
  FormControlLabel,
  InputLabel,
  Paper,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { Refresh } from "@mui/icons-material";
import {
  addUploadBatchRow,
  confirmUploadBatch,
  deleteUploadBatch,
  deleteUploadBatchRow,
  getRinseBagExportConfig,
  getUploadBatches,
  getCurrentUploadBatch,
  getUploadBatchRows,
  overrideUploadBatchRow,
  postRinseBagExport,
  uploadOrders,
  uploadPortalOrdersCsv,
  uploadRinseDualCsv,
  uploadRinseScanEventsCsv,
} from "../api";
import StagingOrderManagementTable from "../components/StagingOrderManagementTable";
import { formatBusinessDateTime, hasExplicitTzOffset } from "../utils/rinseTimeFormat";
import { useAuth } from "../context/AuthContext";
import { formatCalendarDateLabel, toDateInputValue } from "../utils/datetimeFormat";
import { easternTzLabel, getTodayYmdEastern } from "../utils/estWallClock";

const EMPTY_FORM = {
  date_clean: "",
  name_clean: "",
  weight_num: "",
  service_type: "WF",
  rush_type: "NON-RUSH",
  row_status: "OVERRIDDEN",
  reason: "",
};

function rowStatusOrReason(row) {
  const re = String(row?.reason || "").trim();
  if (re) return re;
  return String(row?.row_status || "").trim() || "—";
}

function UploadPage({ user }) {
  const { hasPerm, opsUi } = useAuth();
  const canEditBatchRows = hasPerm("upload.rows.edit");
  const canDeleteBatchRows = hasPerm("upload.rows.delete");
  const [file, setFile] = useState(null);
  const [portalCsvFile, setPortalCsvFile] = useState(null);
  const [scanEventsCsvFile, setScanEventsCsvFile] = useState(null);
  const [scanEventsCount, setScanEventsCount] = useState(0);
  const [batchDate, setBatchDate] = useState(() => getTodayYmdEastern());
  const [batchDateUnlocked, setBatchDateUnlocked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [batch, setBatch] = useState(null);
  const [batches, setBatches] = useState([]);
  const [batchListRange, setBatchListRange] = useState("last_3_days");
  const [batchListFrom, setBatchListFrom] = useState("");
  const [batchListTo, setBatchListTo] = useState("");
  const [rows, setRows] = useState([]);
  const [viewTab, setViewTab] = useState("REVIEW");
  const [rowStatusFilter, setRowStatusFilter] = useState("ALL");

  const [editOpen, setEditOpen] = useState(false);
  const [editRowId, setEditRowId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState(EMPTY_FORM);

  const [message, setMessage] = useState({ type: "info", text: "" });

  const [rinseExportLoading, setRinseExportLoading] = useState(false);
  const [rinseExportHint, setRinseExportHint] = useState("");

  const isRinseExportAdmin = useMemo(() => {
    const r = (user?.roles || []).map((x) => String(x).toUpperCase());
    return r.includes("ADMIN") || r.includes("SUPER_ADMIN") || r.includes("PLATFORM_ADMIN");
  }, [user?.roles]);

  const isConfirmed = (batch?.state || "").toUpperCase() === "CONFIRMED";
  const isDraft = (batch?.state || "").toUpperCase() === "DRAFT";

  const requireBothCsv = opsUi?.upload_batch_require_both_csv !== false;
  const uploadFiles = batch?.upload_files || null;
  const hasOrderRows = uploadFiles?.has_order_rows ?? rows.some(
    (r) => !["DELETED"].includes(String(r.row_status || "").toUpperCase()),
  );
  const hasScanEvents = (uploadFiles?.has_scan_events ?? scanEventsCount > 0) === true;
  const canConfirmBatch = requireBothCsv
    ? hasOrderRows && hasScanEvents
    : hasOrderRows || hasScanEvents;
  const dualCsvBlockHint = useMemo(() => {
    if (!isDraft || !batch?.id || canConfirmBatch) return "";
    if (requireBothCsv) {
      const missing = [];
      if (!hasOrderRows) missing.push("portal order CSV (order rows in the batch)");
      if (!hasScanEvents) missing.push("Rinse scan-events CSV");
      return `Before confirming: upload ${missing.join(" and ")}.`;
    }
    return "Before confirming: upload at least a portal order CSV or a scan-events CSV.";
  }, [requireBothCsv, isDraft, batch?.id, hasOrderRows, hasScanEvents, canConfirmBatch]);

  const halfDraftWithoutEvents = requireBothCsv && isDraft && batch?.id && hasOrderRows && !hasScanEvents;
  const dualUploadReady = Boolean(portalCsvFile && scanEventsCsvFile);

  const formatBatchCreatedLabel = (row) => {
    if (!row) return "No time";
    const et = row.batch_created_at || row.created_at;
    const formatted = formatBusinessDateTime(et);
    if (formatted !== "—") return formatted;
    const dtSource = row.created_at || row.updated_at;
    if (dtSource && hasExplicitTzOffset(String(dtSource))) {
      return formatBusinessDateTime(dtSource);
    }
    return "No time";
  };

  const formatBatchLabel = (row) => {
    if (!row) return "No active batch";
    const timeLabel = row.batch_time_label || (row.scheduled_scrape ? "Imported at" : "Batch created");
    return `Batch #${row.id} • ${timeLabel} ${formatBatchCreatedLabel(row)}`;
  };

  const formatBatchTimingSecondary = (row) => {
    const scrape = row?.scheduled_scrape;
    if (scrape?.timing_summary) return scrape.timing_summary;
    if (row?.batch_confirmed_at) {
      return `Confirmed ${formatBusinessDateTime(row.batch_confirmed_at)}`;
    }
    return null;
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
      const apiErr =
        error?.response?.data?.error ||
        (typeof error?.response?.data === "string" ? error.response.data : "");
      setMessage({
        type: "error",
        text: apiErr ? String(apiErr) : "Failed to load batch rows.",
      });
    } finally {
      setLoadingRows(false);
    }
  };

  const loadCurrentBatch = async (statusFilter = rowStatusFilter) => {
    try {
      const res = await getCurrentUploadBatch();
      const current = res?.data || null;
      setBatch(current);
      const uf = current?.upload_files;
      setScanEventsCount(Number(uf?.scan_events_count ?? current?.scan_events_count) || 0);

      if (batchDateUnlocked && current?.batch_date) {
        const d = toDateInputValue(current.batch_date);
        if (d) setBatchDate(d);
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
      const params = { range: batchListRange };
      if (batchListRange === "custom") {
        if (!batchListFrom || !batchListTo) return;
        params.from_date = batchListFrom;
        params.to_date = batchListTo;
      }
      const res = await getUploadBatches(params);
      const payload = res.data;
      setBatches(Array.isArray(payload?.items) ? payload.items : Array.isArray(payload) ? payload : []);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    loadBatchHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchListRange, batchListFrom, batchListTo]);

  useEffect(() => {
    loadCurrentBatch("ALL");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (batchDateUnlocked) return;
    if (batch?.batch_date) {
      const d = toDateInputValue(batch.batch_date);
      if (d) setBatchDate(d);
    } else {
      setBatchDate(getTodayYmdEastern());
    }
  }, [batchDateUnlocked, batch?.id, batch?.batch_date]);

  useEffect(() => {
    if (!isRinseExportAdmin) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getRinseBagExportConfig();
        if (cancelled) return;
        const d = res.data || {};
        let hint = d.hint || "";
        if (!d.enabled) {
          if (d.rinse_export_env_key_present === false) {
            hint +=
              " Workers may not see the flag until you Restart the API App Service (Save settings first). SSH can show printenv=1 before gunicorn reloads.";
          } else {
            hint +=
              " Set Value to 1 (no quotes), Save, then Restart the App Service.";
          }
        }
        setRinseExportHint(hint.trim());
      } catch {
        if (!cancelled) setRinseExportHint("");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isRinseExportAdmin]);

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

  const uploadScanEventsCsv = async () => {
    if (!scanEventsCsvFile) {
      setMessage({ type: "warning", text: "Choose a scan-events CSV (.csv) first." });
      return;
    }
    if (!batch?.id) {
      setMessage({
        type: "warning",
        text: "Upload the regular portal order CSV first to create a draft batch, then add scan-events.",
      });
      return;
    }
    if (isConfirmed) {
      setMessage({ type: "warning", text: "Cannot add scan-events to a confirmed batch." });
      return;
    }

    const formData = new FormData();
    formData.append("file", scanEventsCsvFile);

    try {
      setLoading(true);
      const res = await uploadRinseScanEventsCsv(batch.id, formData);
      const d = res.data || {};
      const warn = Array.isArray(d.warnings) && d.warnings.length ? ` (${d.warnings.join(" ")})` : "";
      setScanEventsCount(d.rows_inserted ?? 0);
      setMessage({
        type: "success",
        text: `Scan-events uploaded: ${d.rows_inserted ?? 0} row(s), ${d.bags_with_events ?? 0} bag(s).${warn}`,
      });
      await loadCurrentBatch("ALL");
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Scan-events upload failed";
      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const uploadPortalCsv = async () => {
    if (!portalCsvFile) {
      setMessage({ type: "warning", text: "Choose a portal CSV (.csv) first." });
      return;
    }
    const formData = new FormData();
    formData.append("file", portalCsvFile);
    formData.append("batch_date", batchDate);
    try {
      setLoading(true);
      const res = await uploadPortalOrdersCsv(formData);
      setMessage({
        type: "success",
        text: `Portal CSV draft uploaded. Accepted: ${res.data.rows_inserted}, Rejected: ${res.data.rejected_rows}, Needs Attention: ${res.data.needs_attention_rows}`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Portal CSV upload failed";
      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const uploadDualCsv = async () => {
    if (!portalCsvFile || !scanEventsCsvFile) {
      setMessage({
        type: "warning",
        text: "Select both portal order CSV and Rinse scan-events CSV.",
      });
      return;
    }
    const formData = new FormData();
    formData.append("portal_csv", portalCsvFile);
    formData.append("scan_events_csv", scanEventsCsvFile);
    formData.append("batch_date", batchDate);
    try {
      setLoading(true);
      const res = await uploadRinseDualCsv(formData);
      const d = res.data || {};
      const warn = Array.isArray(d.warnings) && d.warnings.length ? ` (${d.warnings.join(" ")})` : "";
      setScanEventsCount(d.upload_files?.scan_events_count ?? d.scan_events_batch?.rows_inserted ?? 0);
      setMessage({
        type: "success",
        text: `Draft created from both files. Accepted: ${d.rows_inserted}, Rejected: ${d.rejected_rows}, Needs Attention: ${d.needs_attention_rows}.${warn}`,
      });
      await loadCurrentBatch("ALL");
      await loadBatchHistory();
    } catch (error) {
      console.error(error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        "Combined upload failed";
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

  const confirmSummaryMessage = (data) => {
    const parts = [];
    const accepted = Number(data?.accepted_portal_rows ?? 0);
    const rejectedCompleted = Number(data?.rejected_already_completed_rows ?? 0);
    const newlyCompleted = Number(data?.newly_completed_clean_rack_count ?? 0);
    const stagingApplied = Number(data?.staging_orders_applied_count ?? 0);
    if (accepted || rejectedCompleted) {
      parts.push(
        `Accepted: ${accepted}, already completed (rejected): ${rejectedCompleted}.`
      );
    }
    if (newlyCompleted) {
      parts.push(`Newly completed from Clean rack: ${newlyCompleted}.`);
    }
    if (stagingApplied) {
      parts.push(`Staging orders applied: ${stagingApplied}.`);
    }
    const calculated = Number(data?.folding_recompute_calculated ?? 0);
    const exceptions = Number(data?.folding_recompute_exceptions ?? 0);
    if (calculated || exceptions) {
      parts.push(
        `Folding updated: ${calculated} calculated, ${exceptions} exceptions.`
      );
    }
    return parts.length ? ` ${parts.join(" ")}` : "";
  };

  const handleConfirm = async () => {
    if (!batch?.id) return;
    if (!canConfirmBatch) {
      setMessage({
        type: "warning",
        text: dualCsvBlockHint || "Upload required files before confirming this batch.",
      });
      return;
    }

    try {
      setLoading(true);
      const res = await confirmUploadBatch(batch.id, false);
      const data = res?.data || {};
      setMessage({
        type: "success",
        text: `Batch confirmed and applied to staging.${confirmSummaryMessage(data)}`,
      });
      await loadCurrentBatch(rowStatusFilter);
      await loadBatchHistory();
      window.dispatchEvent(new CustomEvent("washpro-upload-batch-changed"));
    } catch (error) {
      const status = error?.response?.status;
      const data = error?.response?.data || {};

      if (status === 409 && data.missing?.length) {
        setMessage({
          type: "error",
          text: data.error || "Upload portal order CSV and scan-events CSV before confirming.",
        });
      } else if (status === 409 && data.attention_count) {
        const ok = window.confirm(
          `${data.attention_count} rows still need attention. Confirm anyway?`
        );
        if (ok) {
          const res = await confirmUploadBatch(batch.id, true);
          const data = res?.data || {};
          setMessage({
            type: "success",
            text: `Batch force-confirmed and applied.${confirmSummaryMessage(data)}`,
          });
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

  const runRinseBagExport = async () => {
    const ok = window.confirm(
      "Run Rinse cleaner-tickets export on the server? This can take several minutes. Your browser must stay open until the download starts."
    );
    if (!ok) return;

    try {
      setRinseExportLoading(true);
      setMessage({ type: "info", text: "Running Rinse export on server…" });
      const res = await postRinseBagExport();
      const cd = res.headers["content-disposition"] || "";
      let filename = `rinse-bag-export-${Date.now()}.csv`;
      const star = /filename\*=UTF-8''([^;\n]+)/i.exec(cd);
      const quoted = /filename="([^"]+)"/i.exec(cd);
      const plain = /filename=([^;\n]+)/i.exec(cd);
      if (star) {
        filename = decodeURIComponent(star[1].trim());
      } else if (quoted) {
        filename = quoted[1].trim();
      } else if (plain) {
        filename = plain[1].trim().replace(/^["']|["']$/g, "");
      }
      if (!filename.endsWith(".csv")) filename += ".csv";
      const blob = new Blob([res.data], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      setMessage({
        type: "success",
        text: `Downloaded ${filename}. Bag-ID export for bag / QR workflows. For order staging, use portal CSV upload above.`,
      });
      const cfg = await getRinseBagExportConfig();
      setRinseExportHint(cfg.data?.hint || "");
    } catch (error) {
      console.error(error);
      let text = error?.response?.data?.error || error?.message || "Rinse export failed.";
      const data = error?.response?.data;
      if (data instanceof Blob) {
        try {
          const raw = await data.text();
          try {
            const j = JSON.parse(raw);
            if (j?.error) text = j.error;
            if (j?.stdout_tail) text = `${text}\n${String(j.stdout_tail).slice(-800)}`;
            if (j?.stderr_tail) text = `${text}\n${String(j.stderr_tail).slice(-1200)}`;
          } catch {
            if (raw && raw.trim()) {
              const snippet = raw.trim().slice(0, 800);
              if (
                /<html/i.test(snippet) ||
                /Internal Server Error/i.test(snippet) ||
                /502 Bad Gateway/i.test(snippet) ||
                /504 Gateway/i.test(snippet)
              ) {
                text =
                  "Rinse export failed: the API returned a generic HTML error (not JSON). " +
                  "Common causes: Azure/proxy timeout (~2–4 min), Gunicorn worker killed (OOM/timeout), or an uncaught server crash. " +
                  "Check Azure → laundryops-api → Log stream. Try RINSE_MAX_PAGES=3 for a shorter run, " +
                  "ensure GUNICORN_TIMEOUT≥1200 on the API, and use a larger App Service SKU if the worker runs out of memory.";
              } else {
                text = snippet;
              }
            }
          }
        } catch {
          /* ignore */
        }
      }
      setMessage({ type: "error", text });
    } finally {
      setRinseExportLoading(false);
    }
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

      <Paper sx={{ mt: 1, p: 1.25, borderRadius: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} flexWrap="wrap">
          <FormControlLabel
            sx={{ mr: 0, ml: 0 }}
            control={
              <Checkbox
                size="small"
                checked={batchDateUnlocked}
                onChange={(e) => setBatchDateUnlocked(e.target.checked)}
              />
            }
            label="Edit batch date (emergency / test)"
          />
          <TextField
            type="date"
            size="small"
            label={`Batch date (US Eastern — ${easternTzLabel()})`}
            InputLabelProps={{ shrink: true }}
            value={batchDate}
            onChange={(e) => setBatchDate(e.target.value)}
            disabled={!batchDateUnlocked}
            sx={{ width: { xs: "100%", sm: 220 } }}
            helperText={batchDateUnlocked ? "" : "Locked to Eastern calendar date for new uploads; check the box to override."}
          />
        </Stack>
      </Paper>

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

      {(message.text || isDraft || dualCsvBlockHint) && (
        <Alert
          severity={message.type === "error" ? "error" : message.type === "warning" ? "warning" : "success"}
          sx={{ mt: 1, borderRadius: 2, py: 0.5 }}
        >
          {message.text ||
            (dualCsvBlockHint ||
              (isDraft ? "Draft — confirm batch when ready." : "Ready."))}
        </Alert>
      )}

      {requireBothCsv && isDraft && batch?.id && (
        <Stack direction="row" spacing={1} sx={{ mt: 0.8, flexWrap: "wrap" }}>
          <Chip
            size="small"
            label={hasOrderRows ? "Order CSV: uploaded" : "Order CSV: missing"}
            color={hasOrderRows ? "success" : "warning"}
            variant={hasOrderRows ? "filled" : "outlined"}
          />
          <Chip
            size="small"
            label={hasScanEvents ? "Scan-events CSV: uploaded" : "Scan-events CSV: missing"}
            color={hasScanEvents ? "success" : "warning"}
            variant={hasScanEvents ? "filled" : "outlined"}
          />
        </Stack>
      )}

      {halfDraftWithoutEvents && (
        <Alert severity="warning" sx={{ mt: 1, borderRadius: 2 }}>
          This draft was started without scan-events. Reset draft and use Upload both.
        </Alert>
      )}

      {requireBothCsv ? (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
          <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 0.5 }}>
            Portal + scan-events (required)
          </Typography>
          <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>
            Both CSV files are required to create a draft. Scan-events are applied before order rows
            are classified.
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap">
            <Stack spacing={0.6}>
              <Typography sx={{ fontWeight: 500, fontSize: 13 }}>Portal order CSV</Typography>
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setPortalCsvFile(e.target.files?.[0] || null)}
              />
            </Stack>
            <Stack spacing={0.6}>
              <Typography sx={{ fontWeight: 500, fontSize: 13 }}>Scan-events CSV</Typography>
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setScanEventsCsvFile(e.target.files?.[0] || null)}
              />
            </Stack>
            <Button
              variant="contained"
              color="secondary"
              onClick={uploadDualCsv}
              disabled={loading || !dualUploadReady}
            >
              {loading ? "…" : "Upload both / create draft"}
            </Button>
          </Stack>
          {batch?.id && scanEventsCount > 0 && (
            <Typography sx={{ mt: 1, fontSize: 13, color: "text.secondary" }}>
              This draft batch has {scanEventsCount} stored scan-event row(s).
            </Typography>
          )}
        </Paper>
      ) : (
        <>
          <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
            <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>Portal CSV (primary)</Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
              <Stack spacing={0.6}>
                <Typography sx={{ fontWeight: 500, fontSize: 13 }}>CSV file</Typography>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setPortalCsvFile(e.target.files?.[0] || null)}
                />
              </Stack>
              <Button variant="contained" color="secondary" onClick={uploadPortalCsv} disabled={loading}>
                {loading ? "…" : "Upload CSV draft"}
              </Button>
            </Stack>
          </Paper>

          <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
            <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 0.5 }}>
              Optional: Rinse scan-events CSV
            </Typography>
            <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>
              Bag scan history only (Bag ID + scan columns). Does not replace the portal order CSV.
              Events will be linked to orders later using Bag ID.
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
              <Stack spacing={0.6}>
                <Typography sx={{ fontWeight: 500, fontSize: 13 }}>Events CSV</Typography>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setScanEventsCsvFile(e.target.files?.[0] || null)}
                />
              </Stack>
              <Button
                variant="outlined"
                color="secondary"
                onClick={uploadScanEventsCsv}
                disabled={loading || isConfirmed || !batch?.id}
              >
                {loading ? "…" : "Upload scan-events CSV"}
              </Button>
            </Stack>
            {batch?.id && scanEventsCount > 0 && (
              <Typography sx={{ mt: 1, fontSize: 13, color: "text.secondary" }}>
                This draft batch has {scanEventsCount} stored scan-event row(s).
              </Typography>
            )}
            {!batch?.id && (
              <Typography sx={{ mt: 1, fontSize: 13, color: "warning.main" }}>
                Upload the portal order CSV first to create a draft batch.
              </Typography>
            )}
          </Paper>
        </>
      )}

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>
          Excel (no bag id | backup)
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 14 }}>Workbook</Typography>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </Stack>

          <Button variant="contained" onClick={uploadFile} disabled={loading}>
            {loading ? "Uploading..." : "Upload draft"}
          </Button>

          <Button variant="outlined" onClick={() => loadCurrentBatch(rowStatusFilter)} disabled={loading || loadingRows}>
            Refresh staging
          </Button>
        </Stack>
      </Paper>

      {isRinseExportAdmin && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 1 }}>Rinse export (admin)</Typography>
          <Button variant="outlined" size="small" onClick={runRinseBagExport} disabled={rinseExportLoading || loading}>
            {rinseExportLoading ? "…" : "Download CSV"}
          </Button>
        </Paper>
      )}

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
                Date {formatCalendarDateLabel(batch.batch_date)} • State {batch.state || "DRAFT"}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1}>
              <Button variant="outlined" onClick={() => setAddOpen(true)} disabled={isConfirmed || loading}>
                Add Row
              </Button>
              <Button
                variant="contained"
                onClick={handleConfirm}
                disabled={isConfirmed || loading || !canConfirmBatch}
                title={!canConfirmBatch ? dualCsvBlockHint : ""}
              >
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
                  <TableCell>Bag ID</TableCell>
                  <TableCell>Registry</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Rush</TableCell>
                  <TableCell>Status / reason</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.id}</TableCell>
                    <TableCell>{formatCalendarDateLabel(row.date_clean)}</TableCell>
                    <TableCell>{row.name_clean}</TableCell>
                    <TableCell>
                      {String(row.service_type || "").toUpperCase() === "HD"
                        ? `${Math.round(Number(row.weight_num || 0))} pcs`
                        : row.weight_num == null
                          ? "-"
                          : `${Number(row.weight_num).toFixed(2)} lb`}
                    </TableCell>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 13 }}>
                      {row.ticket_id ? String(row.ticket_id) : "—"}
                    </TableCell>
                    <TableCell>
                      {!row.ticket_id ? (
                        "—"
                      ) : row.registry_not_found ? (
                        <Chip size="small" label="No registry" variant="outlined" />
                      ) : (
                        <Tooltip
                          title={
                            row.registry_status === "COMPLETED"
                              ? `Completed${row.completion_reason ? `: ${row.completion_reason}` : ""}${
                                  row.completed_at ? ` @ ${row.completed_at}` : ""
                                }`
                              : row.registry_status === "INCOMPLETE"
                                ? "Incomplete — scan-events may still be pending"
                                : ""
                          }
                        >
                          <Chip
                            size="small"
                            label={row.registry_status || "—"}
                            color={row.registry_status === "COMPLETED" ? "success" : "warning"}
                            variant={row.registry_status === "COMPLETED" ? "filled" : "outlined"}
                          />
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>{row.service_type}</TableCell>
                    <TableCell>{row.rush_type}</TableCell>
                    <TableCell>{rowStatusOrReason(row)}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.6}>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => openEdit(row)}
                          disabled={isConfirmed || !canEditBatchRows}
                        >
                          Edit
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          onClick={() => handleDelete(row.id)}
                          disabled={isConfirmed || !canDeleteBatchRows}
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
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} sx={{ mb: 2 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 500, flex: 1 }}>Uploaded Batches</Typography>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Date filter</InputLabel>
            <Select label="Date filter" value={batchListRange} onChange={(e) => setBatchListRange(e.target.value)}>
              <MenuItem value="today">Today</MenuItem>
              <MenuItem value="last_3_days">Last 3 days</MenuItem>
              <MenuItem value="last_7_days">Last 7 days</MenuItem>
              <MenuItem value="custom">Custom range</MenuItem>
            </Select>
          </FormControl>
          {batchListRange === "custom" ? (
            <>
              <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={batchListFrom} onChange={(e) => setBatchListFrom(e.target.value)} />
              <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={batchListTo} onChange={(e) => setBatchListTo(e.target.value)} />
            </>
          ) : null}
          <Button size="small" variant="outlined" onClick={loadBatchHistory}>Refresh</Button>
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          Default shows last 3 days (America/New_York). Purged batches keep their header with summary counts.
        </Typography>
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
                <Stack spacing={0.25} sx={{ flex: 1, minWidth: 0 }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap" }}>
                    <Typography sx={{ fontWeight: 500 }}>{formatBatchLabel(b)}</Typography>
                    <Chip
                      size="small"
                      label={(b.state || "DRAFT").toUpperCase()}
                      color={String(b.state || "").toUpperCase() === "CONFIRMED" ? "success" : "warning"}
                    />
                    {b.heavy_rows_purged || b.raw_rows_purged_at ? (
                      <Chip size="small" variant="outlined" label="Raw rows purged" />
                    ) : null}
                    {b.scheduled_scrape ? (
                      <Chip size="small" variant="outlined" label="Scheduled scrape" color="info" />
                    ) : null}
                  </Stack>
                  {formatBatchTimingSecondary(b) ? (
                    <Typography variant="caption" color="text.secondary">
                      {formatBatchTimingSecondary(b)}
                    </Typography>
                  ) : null}
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography color="text.secondary">
                    {b.scheduled_scrape?.rows_imported != null
                      ? `${b.scheduled_scrape.rows_imported} portal rows`
                      : `Loaded ${b.orders_loaded || 0}`}
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={async () => {
                      setBatch(b);
                      if (b.heavy_rows_purged || b.raw_rows_purged_at) {
                        setMessage({
                          type: "info",
                          text: "Raw portal/scan rows were purged per retention policy. Summary counts remain on the batch header.",
                        });
                      }
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
