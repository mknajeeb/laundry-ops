import { useEffect, useMemo, useRef, useState } from "react";
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
  getRinseBagExportConfig,
  getUploadBatches,
  getCurrentUploadBatch,
  getUploadBatchRows,
  getRinseImportUploadBatchJob,
  cancelRinseImportUploadBatchJob,
  overrideUploadBatchRow,
  postRinseBagExport,
  startRinseImportUploadBatchJob,
  uploadOrders,
  uploadPortalOrdersCsv,
} from "../api";
import StagingOrderManagementTable from "../components/StagingOrderManagementTable";
import { useAuth } from "../context/AuthContext";
import { formatCalendarDateLabel, toDateInputValue } from "../utils/datetimeFormat";

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
  const { hasPerm } = useAuth();
  const [file, setFile] = useState(null);
  const [portalCsvFile, setPortalCsvFile] = useState(null);
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

  const [rinseExportLoading, setRinseExportLoading] = useState(false);
  const [rinseImportJobId, setRinseImportJobId] = useState(null);
  const [rinseImportStopBusy, setRinseImportStopBusy] = useState(false);
  const [rinseExportHint, setRinseExportHint] = useState("");
  const [portalScrapeLog, setPortalScrapeLog] = useState("");
  const portalLogRef = useRef(null);

  const isRinseExportAdmin = useMemo(() => {
    const r = (user?.roles || []).map((x) => String(x).toUpperCase());
    return r.includes("ADMIN") || r.includes("SUPER_ADMIN") || r.includes("PLATFORM_ADMIN");
  }, [user?.roles]);
  const canRunPortalScrape = isRinseExportAdmin || hasPerm("upload.create");

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

  useEffect(() => {
    const el = portalLogRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [portalScrapeLog]);

  useEffect(() => {
    if (!canRunPortalScrape) return;
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
  }, [canRunPortalScrape]);

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
        text: `Downloaded ${filename}. Bag-ID export for bag / QR workflows. For order staging, use portal CSV upload or “Run portal scrape & load draft” above.`,
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

  const runRinseImportToBatch = async () => {
    const ok = window.confirm(
      "Run the Rinse portal scrape on the API server and add rows to your draft batch for the Batch Date above? " +
        "This is the same flow as run-local-portal-csv.sh: Playwright expands tickets, writes a temporary CSV, " +
        "then the server parses it with the portal mapper and commits the draft (no file download). " +
        "This page will poll for status; several minutes is normal."
    );
    if (!ok) return;

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    try {
      setRinseExportLoading(true);
      setPortalScrapeLog("");
      setMessage({ type: "info", text: "Starting Rinse import job on the server…" });
      const startRes = await startRinseImportUploadBatchJob({ batch_date: batchDate });
      const jobId = startRes.data?.job_id;
      if (!jobId) {
        setMessage({ type: "error", text: "Server did not return a job id for Rinse import." });
        return;
      }
      setRinseImportJobId(jobId);

      const deadline = Date.now() + 55 * 60 * 1000;
      /** If API never marks the job failed, stop spinning when MySQL updated_at stops moving. */
      const STUCK_RUNNING_MS = 3 * 60 * 1000;
      let lastUpdatedAt = null;
      let runningQuietSince = null;

      while (Date.now() < deadline) {
        const st = await getRinseImportUploadBatchJob(jobId);
        const row = st.data || {};
        const status = row.status;
        const note = row.progress_note || status || "…";
        const updatedAt = row.updated_at != null ? String(row.updated_at) : "";
        const outLog = row.stdout_tail != null ? String(row.stdout_tail) : "";
        const errLog = row.stderr_tail != null ? String(row.stderr_tail).trim() : "";
        let combined = errLog ? `${outLog}\n--- stderr ---\n${errLog}` : outLog;
        if (!combined.trim() && (status === "running" || status === "queued")) {
          combined =
            (note && String(note).trim()) ||
            "Server is running Playwright; live log lines appear once rinse.com emits output (often after the browser starts).";
        }
        setPortalScrapeLog(combined);
        setMessage({
          type: "info",
          text: `Rinse import (${jobId.slice(0, 8)}…): ${note}`,
        });

        if (status === "running") {
          if (updatedAt !== lastUpdatedAt) {
            lastUpdatedAt = updatedAt;
            runningQuietSince = Date.now();
          } else if (runningQuietSince != null && Date.now() - runningQuietSince > STUCK_RUNNING_MS) {
            setMessage({
              type: "error",
              text:
                `Rinse import (${jobId.slice(0, 8)}…) looks stuck: no job progress in the API for ${Math.round(
                  STUCK_RUNNING_MS / 60000
                )} minutes (updated_at unchanged). The worker may have been killed when the app restarted. ` +
                "In MySQL, set this job to failed or wait for the API deploy that auto-fails stale jobs, then refresh and start a new import. Enable Always On on the API app.",
            });
            return;
          }
        } else {
          lastUpdatedAt = null;
          runningQuietSince = null;
        }

        if (status === "cancelled") {
          setMessage({
            type: "info",
            text: row.message || row.progress_note || "Rinse import was stopped. No new rows were committed after the stop point.",
          });
          return;
        }

        if (status === "succeeded") {
          const d = row.result || {};
          setMessage({
            type: "success",
            text: `Rinse import complete. Accepted: ${d.rows_inserted ?? 0}, Rejected: ${d.rejected_rows ?? 0}, Needs attention: ${d.needs_attention_rows ?? 0}.`,
          });
          await loadCurrentBatch("ALL");
          await loadBatchHistory();
          const cfg = await getRinseBagExportConfig();
          setRinseExportHint(cfg.data?.hint || "");
          return;
        }

        if (status === "failed") {
          let text =
            row.error ||
            row.stderr_tail ||
            row.stdout_tail ||
            "Rinse import failed (see Azure Log stream for details).";
          if (typeof text === "string" && text.length > 1200) {
            text = `${text.slice(0, 1200)}…`;
          }
          setMessage({ type: "error", text });
          return;
        }

        /* Queued: pick up "running" quickly. Running: poll slower to halve OPTIONS+XHR load on the API. */
        const pollMs = status === "queued" ? 1200 : status === "running" ? 4500 : 2000;
        await sleep(pollMs);
      }

      setMessage({
        type: "error",
        text:
          "Stopped waiting for Rinse import after 55 minutes. The job may still be running — check Azure Log stream and the upload batch list.",
      });
    } catch (error) {
      console.error(error);
      const d = error?.response?.data;
      let text =
        d?.error ||
        d?.message ||
        error?.message ||
        "Rinse import failed.";
      if (
        error?.response?.status === 503 &&
        d &&
        Object.prototype.hasOwnProperty.call(d, "rinse_export_env_key_present")
      ) {
        if (d.rinse_export_env_key_present === false) {
          text =
            "Rinse import is off: the running API workers do not see RINSE_BAG_EXPORT_ENABLED. On this API App Service, set the app setting to 1, Save, then Restart (gunicorn must reload; SSH printenv alone does not update workers).";
        } else if (Number(d.rinse_export_env_value_len) === 0) {
          text =
            "Rinse import is off: the flag is empty in the API environment. Set Value to 1, Save, then Restart.";
        } else {
          text =
            "Rinse import is off: the value is not treated as on. Use 1 (no quotes), Save, then Restart.";
        }
      }
      const msg = String(error?.message || "");
      const code = error?.code;
      if (!error?.response && (code === "ECONNABORTED" || code === "ERR_CANCELED" || /network error|canceled/i.test(msg))) {
        text =
          "A request to the API timed out or was canceled while the import was running. " +
          "Often this is the parallel “current batch” call (nav badge) when the server is busy — the Rinse job may still be running. " +
          "Refresh this page in a minute and check Azure Log stream; if you saw HTTP 202 with a job id, the scrape can finish without this tab staying open.";
      }
      setMessage({ type: "error", text });
    } finally {
      setRinseImportJobId(null);
      setRinseExportLoading(false);
    }
  };

  const stopRinsePortalImport = async () => {
    if (!rinseImportJobId || rinseImportStopBusy) return;
    try {
      setRinseImportStopBusy(true);
      await cancelRinseImportUploadBatchJob(rinseImportJobId);
      setMessage({
        type: "info",
        text: "Stop requested — the server will kill Playwright as soon as it sees this (usually within a few seconds).",
      });
    } catch (error) {
      console.error(error);
      const d = error?.response?.data;
      setMessage({
        type: "error",
        text: d?.error || error?.message || "Could not request stop for this import job.",
      });
    } finally {
      setRinseImportStopBusy(false);
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
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 0.5 }}>Batch date (staging)</Typography>
        <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1.2 }}>
          Applies to Excel upload, portal CSV upload, and the server-side portal scrape → draft job.
        </Typography>
        <TextField
          type="date"
          size="small"
          label="Batch date"
          InputLabelProps={{ shrink: true }}
          value={batchDate}
          onChange={(e) => setBatchDate(e.target.value)}
        />
      </Paper>

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>Excel Upload (w/o bag id)</Typography>
        <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1.2 }}>
          Legacy workbook path: <code>pd.read_excel</code> → <code>transform_orders</code>. Does not use Rinse portal bag
          columns. Use portal import below when you need bag id / service columns.
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

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 15, mb: 1 }}>Rinse portal CSV (with bag id)</Typography>
        <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1.2 }}>
          Portal columns (Date, Customer, Weight, Bag ID, service fields, etc.). Parsed with{" "}
          <code>portal_csv_to_orders_df</code> — not the Excel pipeline. Rows go to the same draft batch for the batch
          date above; confirm batch when ready.
        </Typography>

        <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 0.5 }}>Scrape progress</Typography>
        <Typography color="text.secondary" sx={{ fontSize: 12, mb: 0.8 }}>
          {canRunPortalScrape
            ? "Live log while the API runs Playwright (same as your local terminal scrape). Then the server applies the portal mapper to the temp CSV and loads the draft."
            : "Ask an admin to run the server scrape, or upload a portal CSV you exported elsewhere."}
        </Typography>
        <Box
          ref={portalLogRef}
          sx={{
            maxHeight: 360,
            overflow: "auto",
            p: 1.5,
            borderRadius: 1,
            bgcolor: "grey.900",
            color: "grey.100",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            fontSize: 12,
            lineHeight: 1.45,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            mb: 2,
          }}
        >
          {portalScrapeLog ||
            (rinseExportLoading
              ? "Waiting for log output from the server…"
              : "Run a server scrape or upload a CSV — scrape output appears here in real time.")}
        </Box>

        {canRunPortalScrape && (
          <>
            <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 0.5 }}>Server scrape → temp CSV → draft</Typography>
            <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>
              Same as <code>run-local-portal-csv.sh</code>, but on the API host: <code>scrape.mjs</code> with{" "}
              <code>RINSE_CSV_LAYOUT=portal</code>, temp file, then import. Needs Node, Playwright, session in{" "}
              <code>scripts/rinse-cleanertickets/</code>, and{" "}
              <Typography component="span" sx={{ fontFamily: "monospace", fontSize: 12 }}>
                RINSE_BAG_EXPORT_ENABLED=1
              </Typography>
              . {rinseExportHint ? rinseExportHint : ""}
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} sx={{ mb: 2 }} alignItems="stretch">
              <Button
                variant="contained"
                onClick={runRinseImportToBatch}
                disabled={rinseExportLoading || loading}
              >
                {rinseExportLoading ? "Scrape / import running…" : "Run portal scrape & load draft batch"}
              </Button>
              <Button
                variant="outlined"
                color="warning"
                onClick={stopRinsePortalImport}
                disabled={
                  !rinseImportJobId || !rinseExportLoading || rinseImportStopBusy || loading
                }
              >
                {rinseImportStopBusy ? "Sending stop…" : "Stop scrape / import"}
              </Button>
            </Stack>
          </>
        )}

        <Typography sx={{ fontWeight: 600, fontSize: 14, mb: 0.5 }}>Upload CSV from this computer</Typography>
        <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>
          If you already ran <code>run-local-portal-csv.sh</code> (or any portal-layout export), pick the file here.
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.2} alignItems="flex-end">
          <Stack spacing={0.6}>
            <Typography sx={{ fontWeight: 500, fontSize: 14 }}>Portal CSV</Typography>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setPortalCsvFile(e.target.files?.[0] || null)}
            />
          </Stack>
          <Button variant="contained" color="secondary" onClick={uploadPortalCsv} disabled={loading}>
            {loading ? "Uploading…" : "Upload portal CSV to draft"}
          </Button>
        </Stack>
      </Paper>

      {isRinseExportAdmin && (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
          <Typography sx={{ fontWeight: 500, fontSize: 16, mb: 0.5 }}>Rinse — bag ID export (admin)</Typography>
          <Typography color="text.secondary" sx={{ fontSize: 13, mb: 1 }}>
            Download-only: runs the server scraper and returns that CSV to your browser. It does <strong>not</strong> add
            rows to the draft batch (use Option A or B above for staging).
          </Typography>
          <Button variant="outlined" onClick={runRinseBagExport} disabled={rinseExportLoading || loading}>
            {rinseExportLoading ? "Rinse job running…" : "Download bag IDs CSV from Rinse"}
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
                  <TableCell>Bag ID</TableCell>
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
